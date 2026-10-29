# AI mock curation and Placo

This backend adds two provider-agnostic AI features:

- `POST /ai/mock-tests/generate` asks Gemini to curate IDs from a bounded,
  database-filtered candidate set. The backend revalidates every selected ID
  and persists the resulting test through `mock_tests` and
  `mock_test_questions`; standard attempts and scoring remain unchanged.
- `POST /ai/placo/chat` offers question-aware tutoring and persists owned
  conversations in `placo_conversations` and `placo_messages`.

## Eligibility and provenance

Mock eligibility is determined by question content and structure, taxonomy,
difficulty, and supported scorer/judge relationships. Review state, publication
state, governance reports, duplicate records, source authorization, source
metadata, and provenance do not gate ordinary mock selection. Existing
governance and provenance records are retained for administration and audit.
The selector prevents a question ID from occurring twice in a mock but does
not remove or merge duplicate content.

The canonical predicate is
`app.services.mock_eligibility_service.MOCK_ELIGIBLE_QUESTION_SQL`; generic
selection, blueprint selection, adaptive selection, and AI candidate filtering
reuse that predicate.

## AI mock behavior

Candidates are filtered before any call to the model. The provider receives
only question IDs, stems, topic/subtopic names, and stored difficulty. It never
receives options, answer keys, explanations, or other question-bank rows.
Candidate sampling is randomized and capped at 80 per requested difficulty
(or at the requested count when greater). Recent questions are excluded when
the remaining eligible pool is large enough; otherwise novelty alone is
relaxed. Type, content eligibility, difficulty, and taxonomy constraints are
never relaxed.

Difficulty `TOUGH` maps to the database value `HARD`. For a blueprint request,
the existing blueprint allocator enforces section counts and unique assignment;
AI selection is restricted to its allocated blueprint candidates. The request
must provide the same total count as the blueprint and a difficulty composition
matching that allocation.

## Placo safety

Attempt ownership and question membership are checked server-side. During an
active `MOCK` assessment, Placo's context excludes question wording, options,
selected answer, answer key, grading, and stored explanation; direct answer
requests receive a fixed refusal. No coding reference solution or hidden test
case is ever sent to the provider. Outside an active mock, MCQ explanations
and answer context may be used. Conversation reads and writes are scoped to
the authenticated user.

Messages are limited to 2,000 characters and each AI feature has an
application-process per-user request limit. The simple rate limiter is
per-process and should be replaced by a shared limiter for multi-worker
deployments.

## Configuration and local run

Copy `.env.example` to `.env`, provide a Gemini key privately, and optionally
change `AI_MODEL`. The default model is `gemini-3.1-flash-lite`. Never commit `.env`.
Install the pinned provider package in an already configured backend
environment:

```sh
cd backend
. venv/bin/activate
python -m pip install -r requirements-ai.txt
cp .env.example .env
```

Set the key in `.env`, then apply the additive conversation-table migration
once:

```sh
python migrations/009_ai_features.py
uvicorn app.main:app --reload
```

Use the current Supabase Auth access token as the bearer token for both routes.
Example mock request:

```json
{
  "title": "DBMS mixed mock",
  "question_type": "MCQ",
  "track_id": 1,
  "topic_id": 12,
  "subtopic_id": 34,
  "difficulty_mode": "MIXED",
  "total_questions": 20,
  "duration_seconds": 1800,
  "difficulty_distribution": {
    "EASY": 6,
    "MEDIUM": 10,
    "TOUGH": 4
  },
  "exclude_recent_questions": true
}
```

Example Placo request:

```json
{
  "question_id": 1234,
  "attempt_id": 55,
  "message": "Can you explain this concept?"
}
```

The mock response includes `mock_test_id` for the normal
`POST /attempts` flow. Placo returns `conversation_id`, `message`, `mode`, and
`referenced_question_id`.
