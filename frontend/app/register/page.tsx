"use client";

import Link from "next/link";
import { FormEvent, useCallback, useState, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/components/providers";
import { api, ApiError } from "@/lib/api";
import { Sparkles } from "lucide-react";
import { GoogleSignIn } from "@/components/google-sign-in";

function RegisterForm() {
  const { user, loading, signInWithGoogle } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const next = searchParams.get("next");

  useEffect(() => {
    if (!loading && user) {
      router.replace(next || "/dashboard");
    }
  }, [loading, user, router, next]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");

    try {
      await api.register({
        display_name: name,
        email,
        password,
      });
      // Redirect to login preserving next route
      router.replace(next ? `/login?next=${encodeURIComponent(next)}` : "/login");
    } catch (cause) {
      if (cause instanceof ApiError) {
        setError(
          cause.status === 409
            ? "An account with this email already exists. Please sign in."
            : cause.status >= 500
            ? "Unable to create your account right now. Please try again."
            : cause.message,
        );
      } else {
        setError("Unable to create your account right now. Please try again.");
      }
    } finally {
      setBusy(false);
    }
  };

  const googleSignup = useCallback(async (credential: string, nonce: string) => {
    setError("");
    try {
      await signInWithGoogle(credential, nonce);
      const destination = next?.startsWith("/") && !next.startsWith("//") ? next : "/dashboard";
      router.replace(destination);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Google sign-up failed. Please try again.");
    }
  }, [next, router, signInWithGoogle]);

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
          <h1 className="text-2xl font-bold text-slate-900">Create your workspace</h1>
          <p className="mt-2 text-sm text-slate-500">
            Start a focused path to placement readiness.
          </p>

          <div className="mt-7 mb-5">
            <GoogleSignIn disabled={busy} onCredential={googleSignup} />
          </div>
          <div className="mb-5 flex items-center gap-3 text-xs text-slate-400"><span className="h-px flex-1 bg-slate-200" />OR CREATE WITH EMAIL<span className="h-px flex-1 bg-slate-200" /></div>
          <form onSubmit={submit} className="space-y-4">
            <label className="block text-sm font-medium text-slate-700">
              Display name
              <input
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Your Name"
                className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
              />
            </label>

            <label className="block text-sm font-medium text-slate-700">
              Email
              <input
                required
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="student@example.com"
                className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
              />
            </label>

            <label className="block text-sm font-medium text-slate-700">
              Password
              <input
                required
                minLength={8}
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3 outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
              />
              <span className="mt-1 block text-xs text-slate-400">At least 8 characters.</span>
            </label>

            {error && (
              <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-600">
                {error}
              </div>
            )}

            <button
              disabled={busy}
              className="w-full rounded-xl bg-indigo-600 py-3 font-semibold text-white shadow-sm hover:bg-indigo-700 disabled:opacity-50 transition"
            >
              {busy ? "Creating workspace…" : "Create account"}
            </button>
          </form>

          <p className="mt-6 text-center text-sm text-slate-500">
            Already have an account?{" "}
            <Link
              href={next ? `/login?next=${encodeURIComponent(next)}` : "/login"}
              className="font-semibold text-indigo-600 hover:text-indigo-700"
            >
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </main>
  );
}

export default function RegisterPage() {
  return (
    <Suspense fallback={<div className="grid min-h-screen place-items-center text-slate-500">Loading…</div>}>
      <RegisterForm />
    </Suspense>
  );
}
