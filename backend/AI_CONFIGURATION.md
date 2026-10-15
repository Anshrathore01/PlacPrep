# AI provider configuration

Configure these variables in Render for the backend service (and in `backend/.env` for local development):

- `GEMINI_API_KEY` — existing Google Gemini API key.
- `AI_MODEL` — primary Gemini model; defaults to `gemini-3.1-flash-lite`.
- `GEMINI_FALLBACK_MODEL` — optional second Gemini model; currently documented as `gemini-2.5-flash`.
- `OPENAI_API_KEY` — optional OpenAI API key. If absent, OpenAI fallback is skipped and Gemini continues to work.
- `OPENAI_FALLBACK_MODEL` — OpenAI model; defaults to `gpt-4o-mini`.

The application attempts a transient retry with bounded jitter, then advances through configured models. Provider credentials, prompts, and response bodies are not logged. Public model documentation confirms the names above, but access, quotas, and API availability must be confirmed for the specific provider projects at runtime.
