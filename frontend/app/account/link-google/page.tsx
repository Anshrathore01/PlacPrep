"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { GoogleSignIn } from "@/components/google-sign-in";
import { useAuth } from "@/components/providers";
import { api, ApiError } from "@/lib/api";

export default function LinkGooglePage() {
  const { user, loading, refresh } = useAuth();
  const router = useRouter();
  const [error, setError] = useState("");
  const [complete, setComplete] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace("/login?next=%2Faccount%2Flink-google");
  }, [loading, router, user]);

  const link = useCallback(async (credential: string, nonce: string) => {
    setError("");
    try {
      await api.linkGoogle({ credential, nonce });
      await refresh();
      setComplete(true);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Unable to link Google right now.");
    }
  }, [refresh]);

  if (loading || !user) return <main className="p-10 text-center text-slate-500">Loading account…</main>;
  return <main className="mx-auto max-w-lg px-5 py-16">
    <section className="card p-7">
      <h1 className="text-2xl font-bold text-slate-900">Link a Google account</h1>
      <p className="mt-2 text-sm text-slate-600">Sign in with the Google account whose verified email matches <strong>{user.email}</strong>. Your existing account and password will remain unchanged.</p>
      <div className="mt-6"><GoogleSignIn onCredential={link} /></div>
      {error && <p role="alert" className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-600">{error}</p>}
      {complete && <p role="status" className="mt-4 text-sm text-green-700">Google account linked. You can now use it to sign in.</p>}
      <Link href="/dashboard" className="mt-6 inline-block text-sm font-semibold text-indigo-600">Return to dashboard</Link>
    </section>
  </main>;
}
