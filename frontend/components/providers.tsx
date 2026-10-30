"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { createSupabaseBrowserClient } from "@/lib/supabase/client";
import type { User } from "@/lib/types";

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

const AuthContext = createContext<AuthContextType | null>(null);

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AppProviders");
  }
  return context;
}

function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [hasSession, setHasSession] = useState(false);
  const [authError, setAuthError] = useState("");
  const [status, setStatus] = useState<AuthStatus>("INITIALIZING");
  const inFlightUserRef = useRef<Promise<void> | null>(null);
  const supabase = createSupabaseBrowserClient();

  const fetchUser = useCallback(async (suppressError = false) => {
    const { data: { session } } = await supabase.auth.getSession();
    if (!session) {
      setHasSession(false);
      setUser(null);
      setAuthError("");
      setStatus("UNAUTHENTICATED");
      return;
    }
    setHasSession(true);

    if (inFlightUserRef.current) {
      return inFlightUserRef.current;
    }

    const task = (async () => {
      try {
        const data = await api.me();
        setUser(data);
        setAuthError("");
        setStatus("AUTHENTICATED");
      } catch (cause) {
        setUser(null);
        setAuthError(cause instanceof Error ? cause.message : "Unable to load your PlacPrep account.");
        setStatus("UNAUTHENTICATED");
        if (!suppressError) throw cause;
      } finally {
        inFlightUserRef.current = null;
      }
    })();

    inFlightUserRef.current = task;
    return task;
  }, [supabase]);

  const refresh = useCallback(async () => {
    await fetchUser(false);
  }, [fetchUser]);

  useEffect(() => {
    window.localStorage.removeItem("prepwise_token");
    const initialSync = window.setTimeout(() => void fetchUser(true), 0);
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setHasSession(Boolean(session));
      setTimeout(() => void fetchUser(true), 0);
    });
    return () => {
      window.clearTimeout(initialSync);
      subscription.unsubscribe();
    };
  }, [fetchUser, supabase]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) throw error;
      await refresh();
    },
    [refresh, supabase],
  );

  const signUp = useCallback(async (email: string, password: string, displayName: string, nextPath = "/dashboard") => {
    const callback = new URL("/auth/callback", window.location.origin);
    callback.searchParams.set("next", nextPath.startsWith("/") && !nextPath.startsWith("//") ? nextPath : "/dashboard");
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: { display_name: displayName },
        emailRedirectTo: callback.toString(),
      },
    });
    if (error) throw error;
    if (data.session) await refresh();
    return !data.session;
  }, [refresh, supabase]);

  const signInWithGoogle = useCallback(async (nextPath = "/dashboard") => {
    const safeNext = nextPath.startsWith("/") && !nextPath.startsWith("//") ? nextPath : "/dashboard";
    const callback = new URL("/auth/callback", window.location.origin);
    callback.searchParams.set("next", safeNext);
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: callback.toString(), skipBrowserRedirect: false },
    });
    if (error) throw error;
  }, [supabase]);

  const resetPassword = useCallback(async (email: string) => {
    const callback = new URL("/auth/callback", window.location.origin);
    callback.searchParams.set("next", "/update-password");
    const { error } = await supabase.auth.resetPasswordForEmail(email, { redirectTo: callback.toString() });
    if (error) throw error;
  }, [supabase]);

  const updatePassword = useCallback(async (password: string) => {
    const { error } = await supabase.auth.updateUser({ password });
    if (error) throw error;
  }, [supabase]);

  const linkGoogle = useCallback(async () => {
    const callback = new URL("/auth/callback", window.location.origin);
    callback.searchParams.set("next", "/account/link-google");
    const { error } = await supabase.auth.linkIdentity({
      provider: "google",
      options: { redirectTo: callback.toString() },
    });
    if (error) throw error;
  }, [supabase]);

  const signOut = useCallback(async () => {
    const { error } = await supabase.auth.signOut();
    if (error) throw error;
    setUser(null);
    setHasSession(false);
    setAuthError("");
    setStatus("UNAUTHENTICATED");
  }, [supabase]);

  const loading = status === "INITIALIZING";

  return (
    <AuthContext.Provider
      value={{
        user,
        status,
        loading,
        hasSession,
        authError,
        signIn,
        signUp,
        resetPassword,
        updatePassword,
        signInWithGoogle,
        linkGoogle,
        signOut,
        refresh,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

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
    throw new Error("usePlaco must be used inside AppProviders");
  }
  return context;
}

function PlacoProvider({ children }: { children: ReactNode }) {
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

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <AuthProvider>
      <PlacoProvider>{children}</PlacoProvider>
    </AuthProvider>
  );
}
