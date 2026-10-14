"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";

export type AuthStatus = "INITIALIZING" | "AUTHENTICATED" | "UNAUTHENTICATED";

export type AuthContextType = {
  user: User | null;
  status: AuthStatus;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signInWithGoogle: (credential: string, nonce: string) => Promise<void>;
  signOut: () => void;
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
  const [status, setStatus] = useState<AuthStatus>("INITIALIZING");

  const fetchUser = useCallback(async () => {
    try {
      const data = await api.me();
      setUser(data);
      setStatus("AUTHENTICATED");
    } catch {
      if (typeof window !== "undefined") {
        localStorage.removeItem("prepwise_token");
      }
      setUser(null);
      setStatus("UNAUTHENTICATED");
    }
  }, []);

  const refresh = useCallback(async () => {
    const token = typeof window !== "undefined" ? localStorage.getItem("prepwise_token") : null;
    if (!token) {
      setUser(null);
      setStatus("UNAUTHENTICATED");
      return;
    }
    await fetchUser();
  }, [fetchUser]);

  useEffect(() => {
    let active = true;
    const token = typeof window !== "undefined" ? localStorage.getItem("prepwise_token") : null;
    if (!token) {
      const timer = setTimeout(() => {
        if (active) setStatus("UNAUTHENTICATED");
      }, 0);
      return () => {
        active = false;
        clearTimeout(timer);
      };
    }

    api.me()
      .then((data) => {
        if (active) {
          setUser(data);
          setStatus("AUTHENTICATED");
        }
      })
      .catch(() => {
        if (active) {
          if (typeof window !== "undefined") {
            localStorage.removeItem("prepwise_token");
          }
          setUser(null);
          setStatus("UNAUTHENTICATED");
        }
      });

    return () => {
      active = false;
    };
  }, []);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const result = await api.login({ email, password });
      if (typeof window !== "undefined") {
        localStorage.setItem("prepwise_token", result.access_token);
      }
      await refresh();
    },
    [refresh],
  );

  const signInWithGoogle = useCallback(async (credential: string, nonce: string) => {
    const result = await api.googleLogin({ credential, nonce });
    if (typeof window !== "undefined") localStorage.setItem("prepwise_token", result.access_token);
    await refresh();
  }, [refresh]);

  const signOut = useCallback(() => {
    if (typeof window !== "undefined") {
      localStorage.removeItem("prepwise_token");
    }
    setUser(null);
    setStatus("UNAUTHENTICATED");
  }, []);

  const loading = status === "INITIALIZING";

  return (
    <AuthContext.Provider
      value={{
        user,
        status,
        loading,
        signIn,
        signInWithGoogle,
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
  const [context, setContext] = useState<PlacoContextData>({});

  const openPanel = useCallback((next: PlacoContextData = {}) => {
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
