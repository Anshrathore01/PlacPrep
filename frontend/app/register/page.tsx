"use client";

import Link from "next/link";
import { FormEvent, useState, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/components/providers";
import { Sparkles } from "lucide-react";
import { GoogleOAuthButton } from "@/components/google-oauth-button";

function RegisterForm() {
  const { user, loading, signUp } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmationSent, setConfirmationSent] = useState(false);

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
      const needsConfirmation = await signUp(email, password, name, next || "/dashboard");
      if (needsConfirmation) setConfirmationSent(true);
      else router.replace(next?.startsWith("/") && !next.startsWith("//") ? next : "/dashboard");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to create your account right now. Please try again.");
    } finally {
      setBusy(false);
    }
  };

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
          <p className="mt-2 text-xs text-slate-500">
            Migrating an existing PlacPrep account? Use its same email and confirm it. Your existing profile and history will be linked after verification; choose a new Supabase password.
          </p>

          <div className="mt-7 mb-5">
            <GoogleOAuthButton onError={setError} />
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

            {confirmationSent && (
              <p role="status" className="rounded-xl border border-green-200 bg-green-50 p-3 text-sm text-green-700">
                Check your email for the Supabase confirmation link. It will return you to PlacPrep to finish setting up your account.
              </p>
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
