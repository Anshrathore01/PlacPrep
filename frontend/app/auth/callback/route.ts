
import { NextResponse, type NextRequest } from "next/server";
import { createSupabaseServerClient } from "@/lib/supabase/server";

function safeNextPath(value: string | null) {
  return value?.startsWith("/") && !value.startsWith("//")
    ? value
    : "/dashboard";
}

export async function GET(request: NextRequest) {
  const code = request.nextUrl.searchParams.get("code");
  const nextPath = safeNextPath(request.nextUrl.searchParams.get("next"));

  try {
    if (!code) {
      console.error("[auth/callback] Authorization code is missing.");
      return NextResponse.redirect(
        new URL("/login?error=auth_callback_failed", request.url)
      );
    }

    const supabase = await createSupabaseServerClient();
    const { error } = await supabase.auth.exchangeCodeForSession(code);

    if (error) {
      console.error("[auth/callback] Code exchange failed:", {
        message: error.message,
        status: error.status,
        code: error.code,
      });

      return NextResponse.redirect(
        new URL("/login?error=auth_callback_failed", request.url)
      );
    }

    return NextResponse.redirect(new URL(nextPath, request.url));
  } catch (error) {
    console.error(
      "[auth/callback] Unexpected error:",
      error instanceof Error ? error.message : "Unknown error"
    );

    return NextResponse.redirect(
      new URL("/login?error=auth_callback_failed", request.url)
    );
  }
}
