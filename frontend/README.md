# Prepwise frontend

Next.js App Router frontend for the Placement Preparation Platform.

## Setup

```bash
npm install
cp .env.example .env.local
npm run dev
```

Set `NEXT_PUBLIC_API_BASE_URL` to the local FastAPI server
(`http://127.0.0.1:8000`) and configure the Supabase project URL and publishable
key. Supabase Auth stores its session in cookies through `@supabase/ssr`; the
frontend sends the current Supabase access token to FastAPI as a bearer token.
Google OAuth returns through `/auth/callback`, where the PKCE code is exchanged
for a Supabase session. Allow `http://localhost:3000/**` in the Supabase Auth
redirect allowlist for local development; the callback route is
`/auth/callback`. Gemini is never called
from the browser: AI Mock Generator and Placo use the backend routes
`/ai/mock-tests/generate` and `/ai/placo/chat`.

## Validation

```bash
npm run lint
npm run build
```

The server remains authoritative for question eligibility, assessment timing,
answer validation, and scoring.
