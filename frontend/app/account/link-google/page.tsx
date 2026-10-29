"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/providers";

export default function LinkGooglePage() {
  const { user, loading, linkGoogle } = useAuth();
  const router = useRouter();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace("/login?next=%2Faccount%2Flink-google");
  }, [loading, router, user]);

  const startLink = async () => {
    setBusy(true);
    setError("");
    try {
      await linkGoogle();
    } catch (cause) {
      setBusy(false);
      setError(cause instanceof Error ? cause.message : "Unable to link Google right now.");
    }
  };

  if (loading || !user) return <main className="p-10 text-center text-slate-500">Loading account…</main>;
  return <main className="mx-auto max-w-lg px-5 py-16">
    <section className="card p-7">
      <h1 className="text-2xl font-bold text-slate-900">Link a Google account</h1>
      <p className="mt-2 text-sm text-slate-600">Link Google through Supabase Auth to your signed-in account, <strong>{user.email}</strong>.</p>
      <button type="button" disabled={busy} onClick={startLink} className="mt-6 w-full rounded-xl border border-slate-200 bg-white py-3 font-semibold text-slate-700 disabled:opacity-50">
        {busy ? "Redirecting to Google…" : "Link Google account"}
      </button>
      {error && <p role="alert" className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-600">{error}</p>}
      <Link href="/dashboard" className="mt-6 inline-block text-sm font-semibold text-indigo-600">Return to dashboard</Link>
    </section>
  </main>;
}
