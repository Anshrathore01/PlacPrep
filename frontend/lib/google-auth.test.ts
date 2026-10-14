import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

describe("Google authentication API", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sends the GIS credential and nonce to the existing auth endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ access_token: "app-jwt" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(api.googleLogin({ credential: "google-id-token", nonce: "nonce-value" })).resolves.toEqual({ access_token: "app-jwt" });
    expect(fetchMock.mock.calls[0][0]).toContain("/auth/google");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ credential: "google-id-token", nonce: "nonce-value" });
  });

  it("surfaces backend errors for account-link conflicts", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Sign in with password" }), { status: 409 })));
    await expect(api.googleLogin({ credential: "google-id-token", nonce: "nonce-value" })).rejects.toMatchObject({ status: 409, message: "Sign in with password" });
  });
});
