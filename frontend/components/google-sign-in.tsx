"use client";

import Script from "next/script";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

declare global {
  interface Window {
    google?: { accounts: { id: {
      initialize: (options: { client_id: string; callback: (response: { credential: string }) => void; nonce: string }) => void;
      renderButton: (element: HTMLElement, options: Record<string, string>) => void;
    } } };
  }
}

type Props = { disabled?: boolean; onCredential: (credential: string, nonce: string) => Promise<void> };

export function GoogleSignIn({ disabled = false, onCredential }: Props) {
  const buttonRef = useRef<HTMLDivElement>(null);
  const nonceRef = useRef("");
  const [ready, setReady] = useState(false);
  const [nonceReady, setNonceReady] = useState(false);
  const [nonceGeneration, setNonceGeneration] = useState(0);
  const [setupError, setSetupError] = useState(false);
  const [working, setWorking] = useState(false);
  const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
  const callback = useCallback(async (response: { credential: string }) => {
    setWorking(true);
    try { await onCredential(response.credential, nonceRef.current); }
    finally {
      setWorking(false);
      nonceRef.current = "";
      setNonceReady(false);
      setNonceGeneration((generation) => generation + 1);
    }
  }, [onCredential]);

  useEffect(() => {
    if (!ready || !clientId) return;
    let active = true;
    api.googleNonce().then(({ nonce }) => {
      if (!active) return;
      nonceRef.current = nonce;
      setNonceReady(true);
    }).catch(() => { if (active) setSetupError(true); });
    return () => { active = false; };
  }, [clientId, nonceGeneration, ready]);

  useEffect(() => {
    if (!nonceReady || !clientId || !buttonRef.current || !window.google) return;
    window.google.accounts.id.initialize({ client_id: clientId, callback, nonce: nonceRef.current });
    const container = buttonRef.current;
    const render = () => {
      container.replaceChildren();
      window.google?.accounts.id.renderButton(container, {
        type: "standard", theme: "outline", size: "large", text: "continue_with",
        shape: "rectangular", width: String(Math.floor(container.clientWidth || 320)), logo_alignment: "left",
      });
    };
    render();
    const observer = new ResizeObserver(render);
    observer.observe(container);
    return () => observer.disconnect();
  }, [callback, clientId, nonceReady]);

  if (!clientId) return <p className="text-sm text-slate-500">Google sign-in is not configured.</p>;
  return <>
    <Script src="https://accounts.google.com/gsi/client" strategy="afterInteractive" onLoad={() => setReady(true)} />
    <div className={`relative min-h-10 ${disabled || working ? "pointer-events-none opacity-50" : ""}`}>
      <div ref={buttonRef} className="flex justify-center" />
      {working && <span className="mt-2 block text-center text-sm text-slate-500">Signing in with Google…</span>}
      {setupError && <span role="alert" className="mt-2 block text-center text-sm text-red-600">Unable to initialize Google sign-in. Please refresh and try again.</span>}
    </div>
  </>;
}
