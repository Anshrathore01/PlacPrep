"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useAuth } from "@/components/providers";

export default function ResetPasswordPage() {
  const { resetPassword } = useAuth();
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    setError("");
    try {
      await resetPassword(email);
      setMessage("If this email has a Supabase account, a password reset link is on its way.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to send a password reset email.");
    } finally {
      setBusy(false);
    }
  };

  return <main className="grid min-h-screen place-items-center bg-slate-50 px-5 py-10">
    <section className="card w-full max-w-md p-7 md:p-9">
      <h1 className="text-2xl font-bold text-slate-900">Reset your password</h1>
      <p className="mt-2 text-sm text-slate-500">This resets a password for an account already enrolled in Supabase. If this is your first Supabase sign-in, create an account with the same verified email to reconnect your existing PlacPrep profile.</p>
      <form onSubmit={submit} className="mt-6 space-y-4">
        <label className="block text-sm font-medium text-slate-700">Email
          <input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-200 px-4 py-3" />
        </label>
        {message && <p role="status" className="rounded-xl bg-green-50 p-3 text-sm text-green-700">{message}</p>}
        {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-600">{error}</p>}
        <button disabled={busy} className="w-full rounded-xl bg-indigo-600 py-3 font-semibold text-white disabled:opacity-50">{busy ? "Sending…" : "Send reset link"}</button>
      </form>
      <Link href="/login" className="mt-6 inline-block text-sm font-semibold text-indigo-600">Back to sign in</Link>
    </section>
  </main>;
}
