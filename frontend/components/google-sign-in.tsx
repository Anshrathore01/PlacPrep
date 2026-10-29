"use client";

import { GoogleOAuthButton } from "@/components/google-oauth-button";

/** Compatibility export for any PlacPrep screen still importing GoogleSignIn. */
export function GoogleSignIn({ disabled = false, onError = () => {} }: {
  disabled?: boolean;
  onError?: (message: string) => void;
}) {
  return <GoogleOAuthButton disabled={disabled} onError={onError} />;
}
