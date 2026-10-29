import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

const auth = { getSession: vi.fn(), signOut: vi.fn() };
vi.mock("./supabase/client", () => ({
  createSupabaseBrowserClient: () => ({ auth }),
}));

describe("Supabase-authenticated API client", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    auth.getSession.mockReset();
    auth.signOut.mockReset();
  });

  it("sends the current Supabase access token to the app-user endpoint", async () => {
    vi.stubGlobal("window", {});
    auth.getSession.mockResolvedValue({ data: { session: { access_token: "supabase-access-token" } } });
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ user_id: 12 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await api.me();
    const request = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(request.headers).get("Authorization")).toBe("Bearer supabase-access-token");
    expect(fetchMock.mock.calls[0][0]).toContain("/auth/me");
  });

  it("clears the local Supabase session after an API 401", async () => {
    vi.stubGlobal("window", {});
    auth.getSession.mockResolvedValue({ data: { session: { access_token: "expired-token" } } });
    auth.signOut.mockResolvedValue({ error: null });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "invalid" }), { status: 401 })));

    await expect(api.me()).rejects.toMatchObject({ status: 401 });
    expect(auth.signOut).toHaveBeenCalledWith({ scope: "local" });
  });
});
