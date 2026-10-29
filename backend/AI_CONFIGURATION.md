# AI provider configuration

Configure these variables in Render for the backend service (and in `backend/.env` for local development):

- `GEMINI_API_KEY` — existing Google Gemini API key.
- `AI_MODEL` — primary Gemini model; defaults to `gemini-3.1-flash-lite`.
- `GEMINI_FALLBACK_MODEL` — optional second Gemini model; `gemini-3.5-flash-lite` is a current documented structured-output model. The previously suggested Gemini 2.5 Flash is documented but access is restricted for some projects.
- `OPENAI_API_KEY` — optional OpenAI API key. If absent, OpenAI fallback is skipped and Gemini continues to work.
- `OPENAI_FALLBACK_MODEL` — OpenAI model; defaults to `gpt-4o-mini`.

The application attempts bounded transient retries with jitter, then advances through configured models. Provider credentials, prompts, and response bodies are not logged. Sanitized upstream error messages are included for diagnosing permanent provider errors. Public model documentation confirms the names above and structured-output support, but model access, quotas, and API availability must be confirmed for the specific provider projects at runtime.

Mock curation uses the Google GenAI SDK `models.generate_content` method with `response_mime_type="application/json"` and the `QuestionSelection` Pydantic class as `response_schema`. With the Gemini Developer API client, the SDK uses API version `v1beta` by default. The request schema is validated locally again before any mock persistence.
