"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  useCallback,
  useState,
  type ReactNode,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import { api } from "../lib/api";
import { createSupabaseBrowserClient } from "../lib/supabase/client";
import type { User } from "../lib/types";

export type AuthStatus = "INITIALIZING" | "AUTHENTICATED" | "UNAUTHENTICATED";

export type AuthContextType = {
  user: User | null;
  status: AuthStatus;
  loading: boolean;
  hasSession: boolean;
  authError: string;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, displayName: string, nextPath?: string) => Promise<boolean>;
  resetPassword: (email: string) => Promise<void>;
  updatePassword: (password: string) => Promise<void>;
  signInWithGoogle: (nextPath?: string) => Promise<void>;
  linkGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
};

// =========================================================================
// Module-level Singleton Authentication Store
// Persists auth state across Next.js route group layout unmounts/remounts.
// =========================================================================

type AuthSnapshot = {
  user: User | null;
  status: AuthStatus;
  loading: boolean;
  hasSession: boolean;
  authError: string;
};

const serverSnapshot: AuthSnapshot = {
  user: null,
  status: "INITIALIZING",
  loading: true,
  hasSession: false,
  authError: "",
};

let clientSnapshot: AuthSnapshot = {
  user: null,
  status: "INITIALIZING",
  loading: true,
  hasSession: false,
  authError: "",
};

const storeListeners = new Set<() => void>();

function notifyStoreChange() {
  for (const listener of storeListeners) {
    listener();
  }
}

function updateSnapshot(partial: Partial<AuthSnapshot>) {
  clientSnapshot = { ...clientSnapshot, ...partial };
  notifyStoreChange();
}

function subscribe(listener: () => void) {
  storeListeners.add(listener);
  return () => {
    storeListeners.delete(listener);
  };
}

export function getSnapshot(): AuthSnapshot {
  return clientSnapshot;
}

export { getSnapshot as getAuthSnapshot };

function getServerSnapshot(): AuthSnapshot {
  return serverSnapshot;
}

let activeSupabaseId: string | null = null;
let inFlightFetch: Promise<void> | null = null;
let subscriptionInitialized = false;
let authSubscription: { unsubscribe: () => void } | null = null;

async function fetchUser(force = false, suppressError = false): Promise<void> {
  if (inFlightFetch) {
    return inFlightFetch;
  }

  const task = (async () => {
    try {
      const supabase = createSupabaseBrowserClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) {
        activeSupabaseId = null;
        updateSnapshot({
          user: null,
          status: "UNAUTHENTICATED",
          loading: false,
          hasSession: false,
          authError: "",
        });
        return;
      }

      const supabaseId = session.user.id;

      // If user profile is already loaded for this exact session and we're not forcing refresh, reuse it
      if (!force && clientSnapshot.user && activeSupabaseId === supabaseId) {
        if (clientSnapshot.status !== "AUTHENTICATED" || !clientSnapshot.hasSession) {
          updateSnapshot({
            status: "AUTHENTICATED",
            loading: false,
            hasSession: true,
          });
        }
        return;
      }

      const user = await api.me();
      activeSupabaseId = supabaseId;
      updateSnapshot({
        user,
        status: "AUTHENTICATED",
        loading: false,
        hasSession: true,
        authError: "",
      });
    } catch (cause) {
      activeSupabaseId = null;
      updateSnapshot({
        user: null,
        status: "UNAUTHENTICATED",
        loading: false,
        hasSession: false,
        authError: cause instanceof Error ? cause.message : "Unable to load your PlacPrep account.",
      });
      if (!suppressError) throw cause;
    } finally {
      inFlightFetch = null;
    }
  })();

  inFlightFetch = task;
  return task;
}

function initAuthSubscription() {
  if (typeof window === "undefined" || subscriptionInitialized) return;
  subscriptionInitialized = true;

  window.localStorage.removeItem("prepwise_token");
  const supabase = createSupabaseBrowserClient();

  const { data: { subscription } } = supabase.auth.onAuthStateChange(async (event, session) => {
    if (event === "SIGNED_OUT" || !session) {
      activeSupabaseId = null;
      updateSnapshot({
        user: null,
        status: "UNAUTHENTICATED",
        loading: false,
        hasSession: false,
        authError: "",
      });
      return;
    }

    if (event === "TOKEN_REFRESHED") {
      updateSnapshot({ hasSession: true });
      if (!clientSnapshot.user) {
        void fetchUser(false, true);
      }
      return;
    }

    const isNewUser = session.user.id !== activeSupabaseId;
    if (!clientSnapshot.user || isNewUser || event === "USER_UPDATED") {
      void fetchUser(event === "USER_UPDATED", true);
    } else {
      updateSnapshot({
        hasSession: true,
        status: "AUTHENTICATED",
        loading: false,
      });
    }
  });
  authSubscription = subscription;
}

function stopAuthSubscription() {
  authSubscription?.unsubscribe();
  authSubscription = null;
  subscriptionInitialized = false;
}

// Global actions operating on the singleton store
async function signIn(email: string, password: string) {
  const supabase = createSupabaseBrowserClient();
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) throw error;
  // SIGNED_IN also arrives through the auth subscription. The shared request
  // and cached identity check keep that callback from issuing a second /auth/me.
  await fetchUser(false, false);
}

async function signUp(email: string, password: string, displayName: string, nextPath = "/dashboard") {
  const callback = new URL("/auth/callback", window.location.origin);
  callback.searchParams.set("next", nextPath.startsWith("/") && !nextPath.startsWith("//") ? nextPath : "/dashboard");
  const supabase = createSupabaseBrowserClient();
  const { data, error } = await supabase.auth.signUp({
    email,
    password,
    options: {
      data: { display_name: displayName },
      emailRedirectTo: callback.toString(),
    },
  });
  if (error) throw error;
  if (data.session) await fetchUser(true, false);
  return !data.session;
}

async function signInWithGoogle(nextPath = "/dashboard") {
  const safeNext = nextPath.startsWith("/") && !nextPath.startsWith("//") ? nextPath : "/dashboard";
  const callback = new URL("/auth/callback", window.location.origin);
  callback.searchParams.set("next", safeNext);
  const supabase = createSupabaseBrowserClient();
  const { error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo: callback.toString(), skipBrowserRedirect: false },
  });
  if (error) throw error;
}

async function resetPassword(email: string) {
  const callback = new URL("/auth/callback", window.location.origin);
  callback.searchParams.set("next", "/update-password");
  const supabase = createSupabaseBrowserClient();
  const { error } = await supabase.auth.resetPasswordForEmail(email, { redirectTo: callback.toString() });
  if (error) throw error;
}

async function updatePassword(password: string) {
  const supabase = createSupabaseBrowserClient();
  const { error } = await supabase.auth.updateUser({ password });
  if (error) throw error;
}

async function linkGoogle() {
  const callback = new URL("/auth/callback", window.location.origin);
  callback.searchParams.set("next", "/account/link-google");
  const supabase = createSupabaseBrowserClient();
  const { error } = await supabase.auth.linkIdentity({
    provider: "google",
    options: { redirectTo: callback.toString() },
  });
  if (error) throw error;
}

async function signOut() {
  const supabase = createSupabaseBrowserClient();
  const { error } = await supabase.auth.signOut();
  if (error) throw error;
  activeSupabaseId = null;
  updateSnapshot({
    user: null,
    status: "UNAUTHENTICATED",
    loading: false,
    hasSession: false,
    authError: "",
  });
}

async function refresh() {
  await fetchUser(true, false);
}

// React Context & Provider
const AuthContext = createContext<AuthContextType | null>(null);

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider (or AppProviders)");
  }
  return context;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  if (typeof window !== "undefined") {
    initAuthSubscription();
  }

  const currentSnapshot = useSyncExternalStore(
    subscribe,
    getSnapshot,
    getServerSnapshot,
  );

  useEffect(() => {
    initAuthSubscription();
    return stopAuthSubscription;
  }, []);

  const value = useMemo<AuthContextType>(
    () => ({
      ...currentSnapshot,
      signIn,
      signUp,
      resetPassword,
      updatePassword,
      signInWithGoogle,
      linkGoogle,
      signOut,
      refresh,
    }),
    [currentSnapshot],
  );

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

// =========================================================================
// Placo AI Panel Provider (Separated from root auth)
// =========================================================================

type PlacoContextData = {
  questionId?: number;
  attemptId?: number;
  mode?: string;
  request?: string;
  requestKey?: number;
};

type PlacoState = {
  open: boolean;
  hasOpened: boolean;
  context: PlacoContextData;
  openPanel: (context?: PlacoContextData) => void;
  closePanel: () => void;
};

const PlacoContext = createContext<PlacoState | null>(null);

export function usePlaco() {
  const context = useContext(PlacoContext);
  if (!context) {
    throw new Error("usePlaco must be used inside PlacoProvider (or AppProviders)");
  }
  return context;
}

export function PlacoProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [hasOpened, setHasOpened] = useState(false);
  const [context, setContext] = useState<PlacoContextData>({});

  const openPanel = useCallback((next: PlacoContextData = {}) => {
    setHasOpened(true);
    setContext({ ...next, requestKey: next.request ? Date.now() : undefined });
    setOpen(true);
  }, []);

  const closePanel = useCallback(() => {
    setOpen(false);
    setContext({});
  }, []);

  return (
    <PlacoContext.Provider
      value={{
        open,
        hasOpened,
        context,
        openPanel,
        closePanel,
      }}
    >
      {children}
    </PlacoContext.Provider>
  );
}

// =========================================================================
// Protected Route Guard
// =========================================================================

export function Protected({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (status === "UNAUTHENTICATED") {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [status, router, pathname]);

  if (status === "INITIALIZING") {
    return (
      <div className="flex min-h-screen items-center justify-center text-slate-500">
        Loading your workspace…
      </div>
    );
  }

  if (status === "UNAUTHENTICATED") {
    return (
      <div className="flex min-h-screen items-center justify-center text-slate-500">
        Redirecting to login…
      </div>
    );
  }

  return <>{children}</>;
}

// =========================================================================
// Composite AppProviders (For backwards compatibility)
// =========================================================================

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <AuthProvider>
      <PlacoProvider>{children}</PlacoProvider>
    </AuthProvider>
  );
}
