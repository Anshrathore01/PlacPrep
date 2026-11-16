import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockAuth = {
  getSession: vi.fn(),
  signInWithPassword: vi.fn(),
  signUp: vi.fn(),
  signInWithOAuth: vi.fn(),
  resetPasswordForEmail: vi.fn(),
  updateUser: vi.fn(),
  linkIdentity: vi.fn(),
  signOut: vi.fn(),
  onAuthStateChange: vi.fn(),
};

vi.mock("./supabase/client", () => ({
  createSupabaseBrowserClient: () => ({ auth: mockAuth }),
}));

const mockApi = {
  me: vi.fn(),
};

vi.mock("./api", () => ({
  api: mockApi,
}));

describe("Authentication architecture and session persistence", () => {
  let authCallback: ((event: string, session: unknown) => Promise<void>) | null = null;

  beforeEach(() => {
    vi.stubGlobal("window", {
      location: { origin: "http://localhost:3000" },
      localStorage: { removeItem: vi.fn() },
    });
    mockAuth.onAuthStateChange.mockImplementation((callback) => {
      authCallback = callback;
      return { data: { subscription: { unsubscribe: vi.fn() } } };
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("1. Email login: signs in and loads user profile with exactly 1 /auth/me call", async () => {
    mockAuth.getSession.mockResolvedValue({
      data: { session: { user: { id: "user-101" }, access_token: "tok-101" } },
    });
    mockApi.me.mockResolvedValue({
      user_id: 101,
      email: "email@example.com",
      display_name: "Email User",
    });

    const { AuthProvider, useAuth, getAuthSnapshot } = await import("../components/providers");

    let capturedAuth: ReturnType<typeof useAuth> | null = null;
    function TestConsumer() {
      capturedAuth = useAuth();
      return null;
    }

    const { createElement } = await import("react");
    const { renderToStaticMarkup } = await import("react-dom/server");
    renderToStaticMarkup(createElement(AuthProvider, null, createElement(TestConsumer)));

    mockAuth.signInWithPassword.mockResolvedValue({ error: null });
    mockApi.me.mockClear();

    await capturedAuth!.signIn("email@example.com", "validPass123");

    expect(mockAuth.signInWithPassword).toHaveBeenCalledWith({
      email: "email@example.com",
      password: "validPass123",
    });
    expect(mockApi.me).toHaveBeenCalledTimes(1);
    expect(getAuthSnapshot().status).toBe("AUTHENTICATED");
    expect(getAuthSnapshot().user?.display_name).toBe("Email User");
  });

  it("2. Login -> Dashboard: state remains AUTHENTICATED on remount with 0 additional /auth/me calls", async () => {
    mockAuth.getSession.mockResolvedValue({
      data: { session: { user: { id: "user-102" }, access_token: "tok-102" } },
    });
    mockApi.me.mockResolvedValue({
      user_id: 102,
      email: "dashboard@example.com",
      display_name: "Dashboard User",
    });

    const { AuthProvider, useAuth, getAuthSnapshot } = await import("../components/providers");

    let capturedAuth: ReturnType<typeof useAuth> | null = null;
    function TestConsumer() {
      capturedAuth = useAuth();
      return null;
    }

    const { createElement } = await import("react");
    const { renderToStaticMarkup } = await import("react-dom/server");

    // Login layout mounts
    renderToStaticMarkup(createElement(AuthProvider, null, createElement(TestConsumer)));
    mockAuth.signInWithPassword.mockResolvedValue({ error: null });
    mockApi.me.mockClear();
    await capturedAuth!.signIn("dashboard@example.com", "pass");

    expect(mockApi.me).toHaveBeenCalledTimes(1);
    expect(getAuthSnapshot().status).toBe("AUTHENTICATED");

    // Simulate navigation: Login layout unmounts, Protected Dashboard layout mounts
    mockApi.me.mockClear();
    // Re-mount AuthProvider (simulating cross-route-group navigation)
    renderToStaticMarkup(createElement(AuthProvider, null, createElement(() => null)));

    // Crucial check: singleton store remains AUTHENTICATED — 0 extra /auth/me calls!
    // useSyncExternalStore returns getServerSnapshot() in SSR (renderToStaticMarkup),
    // so we read the actual module-level store via getAuthSnapshot().
    expect(getAuthSnapshot().status).toBe("AUTHENTICATED");
    expect(getAuthSnapshot().user?.display_name).toBe("Dashboard User");
    expect(getAuthSnapshot().loading).toBe(false);
    expect(mockApi.me).not.toHaveBeenCalled();
  });

  it("3. Login -> Companies (public) & Login -> Coding (protected): auth state persists across both", async () => {
    mockAuth.getSession.mockResolvedValue({
      data: { session: { user: { id: "user-103" }, access_token: "tok-103" } },
    });
    mockApi.me.mockResolvedValue({
      user_id: 103,
      email: "multi@example.com",
      display_name: "Multi Nav",
    });

    const { AuthProvider, useAuth, getAuthSnapshot } = await import("../components/providers");
    const { createElement } = await import("react");
    const { renderToStaticMarkup } = await import("react-dom/server");

    let authInstance: ReturnType<typeof useAuth> | null = null;
    renderToStaticMarkup(createElement(AuthProvider, null, createElement(() => {
      authInstance = useAuth();
      return null;
    })));

    mockAuth.signInWithPassword.mockResolvedValue({ error: null });
    await authInstance!.signIn("multi@example.com", "pass");
    expect(getAuthSnapshot().status).toBe("AUTHENTICATED");

    mockApi.me.mockClear();

    // Nav to Public /companies — re-mount AuthProvider (simulates cross-route-group nav)
    renderToStaticMarkup(createElement(AuthProvider, null, createElement(() => null)));
    // Read singleton store (not SSR context — useSyncExternalStore uses getServerSnapshot in SSR)
    expect(getAuthSnapshot().status).toBe("AUTHENTICATED");
    expect(getAuthSnapshot().user?.display_name).toBe("Multi Nav");
    expect(mockApi.me).not.toHaveBeenCalled();

    // Nav to Protected /coding
    renderToStaticMarkup(createElement(AuthProvider, null, createElement(() => null)));
    expect(getAuthSnapshot().status).toBe("AUTHENTICATED");
    expect(getAuthSnapshot().user?.user_id).toBe(103);
    expect(mockApi.me).not.toHaveBeenCalled();
  });

  it("4. Dashboard -> Analytics: internal navigation within protected routes keeps auth state warm", async () => {
    mockAuth.getSession.mockResolvedValue({
      data: { session: { user: { id: "user-104" }, access_token: "tok-104" } },
    });
    mockApi.me.mockResolvedValue({
      user_id: 104,
      email: "analytics@example.com",
      display_name: "Analytics User",
    });

    const { AuthProvider, useAuth, getAuthSnapshot } = await import("../components/providers");
    const { createElement } = await import("react");
    const { renderToStaticMarkup } = await import("react-dom/server");

    let authRef: ReturnType<typeof useAuth> | null = null;
    renderToStaticMarkup(createElement(AuthProvider, null, createElement(() => {
      authRef = useAuth();
      return null;
    })));
    mockAuth.signInWithPassword.mockResolvedValue({ error: null });
    await authRef!.signIn("analytics@example.com", "pass");

    mockApi.me.mockClear();
    // Re-mount AuthProvider simulating navigation to analytics page
    renderToStaticMarkup(createElement(AuthProvider, null, createElement(() => null)));

    // Read singleton store — useSyncExternalStore uses getServerSnapshot() during SSR (renderToStaticMarkup)
    expect(getAuthSnapshot().status).toBe("AUTHENTICATED");
    expect(getAuthSnapshot().user?.user_id).toBe(104);
    expect(mockApi.me).not.toHaveBeenCalled();
  });

  it("5. Logout -> Login: signs out and clears user state to UNAUTHENTICATED", async () => {
    mockAuth.getSession.mockResolvedValue({
      data: { session: { user: { id: "user-105" }, access_token: "tok-105" } },
    });
    mockApi.me.mockResolvedValue({
      user_id: 105,
      email: "logout@example.com",
      display_name: "Logout User",
    });

    const { AuthProvider, useAuth, getAuthSnapshot } = await import("../components/providers");
    const { createElement } = await import("react");
    const { renderToStaticMarkup } = await import("react-dom/server");

    let authRef: ReturnType<typeof useAuth> | null = null;
    renderToStaticMarkup(createElement(AuthProvider, null, createElement(() => {
      authRef = useAuth();
      return null;
    })));
    mockAuth.signInWithPassword.mockResolvedValue({ error: null });
    await authRef!.signIn("logout@example.com", "pass");
    expect(getAuthSnapshot().status).toBe("AUTHENTICATED");

    mockAuth.signOut.mockResolvedValue({ error: null });
    mockApi.me.mockClear();

    await authRef!.signOut();

    expect(mockAuth.signOut).toHaveBeenCalled();
    expect(getAuthSnapshot().status).toBe("UNAUTHENTICATED");
    expect(getAuthSnapshot().user).toBeNull();
    expect(getAuthSnapshot().hasSession).toBe(false);
    expect(mockApi.me).not.toHaveBeenCalled();
  });

  it("6. Expired or invalid session: properly handles null session and transitions to UNAUTHENTICATED", async () => {
    const { AuthProvider, useAuth, getAuthSnapshot } = await import("../components/providers");
    const { createElement } = await import("react");
    const { renderToStaticMarkup } = await import("react-dom/server");

    let authRef: ReturnType<typeof useAuth> | null = null;
    renderToStaticMarkup(createElement(AuthProvider, null, createElement(() => {
      authRef = useAuth();
      return null;
    })));

    mockApi.me.mockClear();
    if (authCallback) {
      await authCallback("SIGNED_OUT", null);
    }

    expect(getAuthSnapshot().status).toBe("UNAUTHENTICATED");
    expect(getAuthSnapshot().user).toBeNull();
    expect(mockApi.me).not.toHaveBeenCalled();
  });

  it("7. Google login: initiates OAuth redirect with correct parameters", async () => {
    mockAuth.signInWithOAuth.mockResolvedValue({ error: null });

    const { AuthProvider, useAuth } = await import("../components/providers");
    const { createElement } = await import("react");
    const { renderToStaticMarkup } = await import("react-dom/server");

    let authRef: ReturnType<typeof useAuth> | null = null;
    renderToStaticMarkup(createElement(AuthProvider, null, createElement(() => {
      authRef = useAuth();
      return null;
    })));

    await authRef!.signInWithGoogle("/custom-dest");

    expect(mockAuth.signInWithOAuth).toHaveBeenCalledWith({
      provider: "google",
      options: {
        redirectTo: "http://localhost:3000/auth/callback?next=%2Fcustom-dest",
        skipBrowserRedirect: false,
      },
    });
  });

  it("8. Registration: calls signUp and returns confirmation status", async () => {
    mockAuth.signUp.mockResolvedValue({
      data: { session: null, user: { id: "new-user-id" } },
      error: null,
    });

    const { AuthProvider, useAuth } = await import("../components/providers");
    const { createElement } = await import("react");
    const { renderToStaticMarkup } = await import("react-dom/server");

    let authRef: ReturnType<typeof useAuth> | null = null;
    renderToStaticMarkup(createElement(AuthProvider, null, createElement(() => {
      authRef = useAuth();
      return null;
    })));

    const needsConfirmation = await authRef!.signUp(
      "new@example.com",
      "password123",
      "New Student",
      "/dashboard"
    );

    expect(needsConfirmation).toBe(true);
    expect(mockAuth.signUp).toHaveBeenCalledWith({
      email: "new@example.com",
      password: "password123",
      options: {
        data: { display_name: "New Student" },
        emailRedirectTo: "http://localhost:3000/auth/callback?next=%2Fdashboard",
      },
    });
  });

  it("9. Password reset & update: calls resetPasswordForEmail and updateUser", async () => {
    mockAuth.resetPasswordForEmail.mockResolvedValue({ error: null });
    mockAuth.updateUser.mockResolvedValue({ error: null });

    const { AuthProvider, useAuth } = await import("../components/providers");
    const { createElement } = await import("react");
    const { renderToStaticMarkup } = await import("react-dom/server");

    let authRef: ReturnType<typeof useAuth> | null = null;
    renderToStaticMarkup(createElement(AuthProvider, null, createElement(() => {
      authRef = useAuth();
      return null;
    })));

    await authRef!.resetPassword("reset@example.com");
    expect(mockAuth.resetPasswordForEmail).toHaveBeenCalledWith(
      "reset@example.com",
      { redirectTo: "http://localhost:3000/auth/callback?next=%2Fupdate-password" }
    );

    await authRef!.updatePassword("newPassword123");
    expect(mockAuth.updateUser).toHaveBeenCalledWith({ password: "newPassword123" });
  });

  it("10. Page refresh while authenticated: restores user from session with exactly 1 /auth/me call", async () => {
    mockAuth.getSession.mockResolvedValue({
      data: { session: { user: { id: "refresh-user" }, access_token: "tok-refresh" } },
    });
    mockApi.me.mockResolvedValue({
      user_id: 999,
      email: "refresh@example.com",
      display_name: "Refresh User",
    });

    const { AuthProvider, useAuth, getAuthSnapshot } = await import("../components/providers");
    const { createElement } = await import("react");
    const { renderToStaticMarkup } = await import("react-dom/server");

    mockApi.me.mockClear();

    renderToStaticMarkup(createElement(AuthProvider, null, createElement(() => {
      useAuth();
      return null;
    })));

    // Simulate Supabase emitting INITIAL_SESSION on page load
    if (authCallback) {
      await authCallback("INITIAL_SESSION", {
        user: { id: "refresh-user" },
        access_token: "tok-refresh",
      });
    }

    expect(mockApi.me).toHaveBeenCalledTimes(1);
    await vi.waitFor(() => expect(getAuthSnapshot().status).toBe("AUTHENTICATED"));
    expect(getAuthSnapshot().user?.display_name).toBe("Refresh User");
  });
});
