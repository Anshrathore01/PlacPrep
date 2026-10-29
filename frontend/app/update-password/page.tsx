"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/providers";

export default function UpdatePasswordPage() {
  const { hasSession, loading, updatePassword, refresh } = useAuth();
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && !hasSession) router.replace("/login");
  }, [hasSession, loading, router]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await updatePassword(password);
      await refresh();
      router.replace("/dashboard");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to update your password.");
    } finally {
      setBusy(false);
    }
  };

  if (loading || !hasSession) return <main className="p-10 text-center text-slate-500">Loading reset session…</main>;
  return <main className="grid min-h-screen place-items-center bg-slate-50 px-5 py-10">
    <section className="card w-full max-w-md p-7 md:p-9">
      <h1 className="text-2xl font-bold text-slate-900">Choose a new password</h1>
      <form onSubmit={submit} className="mt-6 space-y-4">
        <label className="block text-sm font-medium text-slate-700">New password
          <input required minLength={8} type="password" value={password} onChange={(event) => setPassword(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3" />
        </label>
        {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-600">{error}</p>}
        <button disabled={busy} className="w-full rounded-xl bg-indigo-600 py-3 font-semibold text-white disabled:opacity-50">{busy ? "Updating…" : "Update password"}</button>
      </form>
    </section>
  </main>;
}
