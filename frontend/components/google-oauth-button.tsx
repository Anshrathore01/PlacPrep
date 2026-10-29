"use client";

import { useState } from "react";
import { useAuth } from "@/components/providers";

export function GoogleOAuthButton({ onError, disabled = false }: { onError: (message: string) => void; disabled?: boolean }) {
  const { signInWithGoogle } = useAuth();
  const [busy, setBusy] = useState(false);

  const start = async () => {
    setBusy(true);
    onError("");
    try {
      await signInWithGoogle();
    } catch (error) {
      setBusy(false);
      onError(error instanceof Error ? error.message : "Unable to start Google sign-in. Please try again.");
    }
  };

  return (
    <button
      type="button"
      onClick={start}
      disabled={busy || disabled}
      className="flex w-full items-center justify-center gap-3 rounded-xl border border-slate-200 bg-white py-3 font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
    >
      <span aria-hidden="true" className="text-lg font-bold text-[#4285F4]">G</span>
      {busy ? "Redirecting to Google…" : "Continue with Google"}
    </button>
  );
}
