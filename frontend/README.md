# Prepwise frontend

Next.js App Router frontend for the Placement Preparation Platform.

## Setup

```bash
npm install
cp .env.example .env.local
npm run dev
```

Set `NEXT_PUBLIC_API_BASE_URL` to the FastAPI server, for example
`http://127.0.0.1:8000`. The browser stores only the JWT returned by
`/auth/login` and sends it as a bearer token. Gemini is never called from the
browser: AI Mock Generator and Placo use the backend routes
`/ai/mock-tests/generate` and `/ai/placo/chat`.

## Validation

```bash
npm run lint
npm run build
```

The server remains authoritative for question eligibility, assessment timing,
answer validation, and scoring.
