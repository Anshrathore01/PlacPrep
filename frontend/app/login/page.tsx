"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState, Suspense } from "react";
import { Sparkles } from "lucide-react";
import { useAuth } from "@/components/providers";
import { ApiError } from "@/lib/api";
import { GoogleSignIn } from "@/components/google-sign-in";

function LoginForm() {
  const { signIn, signInWithGoogle, user, loading } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const next = searchParams.get("next");
  const destination =
    next?.startsWith("/") && !next.startsWith("//") ? next : "/dashboard";

  useEffect(() => {
    if (!loading && user) {
      router.replace(destination);
    }
  }, [destination, loading, router, user]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await signIn(email, password);
      router.replace(destination);
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Unable to sign in. Please check your credentials.",
      );
    } finally {
      setBusy(false);
    }
  };

  const googleLogin = useCallback(async (credential: string, nonce: string) => {
    setError("");
    try {
      await signInWithGoogle(credential, nonce);
      router.replace(destination);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Google sign-in failed. Please try again.");
    }
  }, [destination, router, signInWithGoogle]);

  return (
    <AuthFrame
      title="Welcome back"
      subtitle="Continue your placement preparation journey."
    >
      <div className="mb-5">
        <GoogleSignIn disabled={busy} onCredential={googleLogin} />
      </div>
      <div className="mb-5 flex items-center gap-3 text-xs text-slate-400"><span className="h-px flex-1 bg-slate-200" />OR CONTINUE WITH EMAIL<span className="h-px flex-1 bg-slate-200" /></div>
      <form onSubmit={submit} className="space-y-4">
        <label className="block text-sm font-medium text-slate-700">
          Email
          <input
            required
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
            placeholder="student@example.com"
          />
        </label>
        <label className="block text-sm font-medium text-slate-700">
          Password
          <input
            required
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
            placeholder="••••••••"
          />
        </label>
        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-600">
            {error}
            {error.includes("account linking page") && <Link href="/account/link-google" className="ml-1 font-semibold underline">Link Google</Link>}
          </div>
        )}
        <button
          disabled={busy}
          className="w-full rounded-xl bg-indigo-600 py-3 font-semibold text-white shadow-sm hover:bg-indigo-700 disabled:opacity-50 transition"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
      <p className="mt-6 text-center text-sm text-slate-500">
        New to prepwise?{" "}
        <Link
          href={next ? `/register?next=${encodeURIComponent(next)}` : "/register"}
          className="font-semibold text-indigo-600 hover:text-indigo-700"
        >
          Create an account
        </Link>
      </p>
    </AuthFrame>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="grid min-h-screen place-items-center text-slate-500">Loading sign in…</div>}>
      <LoginForm />
    </Suspense>
  );
}

function AuthFrame({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <main className="grid min-h-screen place-items-center bg-slate-50 px-5 py-10">
      <div className="w-full max-w-md">
        <Link
          href="/"
          className="mx-auto mb-8 flex w-fit items-center gap-2 text-lg font-bold text-slate-900"
        >
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-indigo-600 text-white shadow-sm">
            <Sparkles size={18} />
          </span>
          prepwise
        </Link>
        <div className="card p-7 md:p-9 shadow-md">
          <h1 className="text-2xl font-bold text-slate-900">{title}</h1>
          <p className="mt-2 text-sm text-slate-500">{subtitle}</p>
          <div className="mt-7">{children}</div>
        </div>
      </div>
    </main>
  );
}
