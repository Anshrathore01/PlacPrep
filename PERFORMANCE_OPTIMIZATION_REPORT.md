# PlacPrep performance audit and optimization report

**Date:** 2026-10-29  
**Scope:** Repository inspection, local tests with fake database connections, and the production measurements supplied in the request. No production endpoint was load-tested, no production database was queried, and nothing was deployed.

## Findings ranked by impact

| Priority | Finding | Confidence and evidence | Impact / status |
|---|---|---|---|
| **P1** | Mock detail performed per-question SQL for every question and option list. | **Confirmed in code.** `api.mocks(id)` calls `GET /mock-tests/{mock_test_id}`. That endpoint called `get_question_detail_student()` once per assigned question; an MCQ performs separate base-question, MCQ-content, and option queries. | For a 10-MCQ mock, the request path made 32 SQL statements (2 mock reads + 30 question reads). The endpoint now batches question content. In the local equivalence fixture it makes 5 queries and returns byte-for-byte identical JSON. Real database latency after deployment is not yet measured. |
| **P1** | Placo 429 source is ambiguous; provider throttles could trigger redundant same-provider retries. | **Retry behavior confirmed; incident source unverified.** Application limiter returns 429 at 30 Placo calls per user per 60 seconds. Separately, provider HTTP 429 is classified as `rate_limit`, but was marked retryable; `FallbackAIProvider` could call the same provider again and clamp its `Retry-After` delay to 1.5 seconds. | Same-provider retry is removed for provider 429/quota errors; another provider family may still serve as fallback. Both provider and application 429 paths now emit distinct safe logs and a `Retry-After` header. The frontend avoids duplicate in-flight submissions and waits before retrying. This should reduce unnecessary retries; the reported ~19.97 s incident was not reproduced, so no latency improvement is claimed. |
| **P2** | Company and taxonomy lists were fetched again after client route remounts. | **Confirmed in code.** The Companies, subject-wise, and difficulty-wise pages fetch these public datasets in mount effects; the API wrapper used `no-store` and had no browser cache. Supplied production observations were 1.10–1.75 s for companies and 1.54–2.16 s for the already-optimized taxonomy endpoint. | Browser memory cache now deduplicates concurrent calls and reuses only these public responses for five minutes. Errors evict their entries. No account-specific catalog, progress, attempt, or analytics data is cached. Test verifies repeated company calls issue one fetch; production revisit time was not measured. |
| **P2** | Product/catalog API requests take about 1.94–2.12 s. | **Endpoint structure confirmed; time attribution unverified.** `GET /coding-practice/product` and `/catalog` read static JSON loaded at process startup and make a user-progress query (plus optional user resolution for catalog). Response sizes and auth/DB timings were not supplied. | No personalized response caching or schema change was made. New request logs will show total and SQL time for slow calls. Further changes need response-size and timing evidence. |
| **P2** | RSC navigations were reported at 78–650 ms; exact cause is unknown. | **User-measured, code cause unverified.** The App Router uses `Link` navigation and root auth providers. The root auth provider bootstraps the session and `/auth/me`; it is not shown to refetch `/auth/me` on every internal navigation. Next links retain default prefetch behavior. | No broad prefetch or auth changes were made. Most route content is client-rendered and has local loading states, so route-shell latency and subsequent API wait should be measured separately. |
| **P2** | Dashboard analytics could grow with a user's attempt history. | **Code-based hypothesis.** Summary gathers submitted-question rows, scores, coding submissions, and topic mappings, then aggregates them in Python. No authenticated timing, query plan, or live index inventory was available. | No analytics semantics or indexes were changed. Use the new slow-request SQL metrics and a safe staging `EXPLAIN` before optimizing. |
| **P3** | Render Free, Aiven Free, and provider network latency may contribute to remaining response time. | **Unverified.** The supplied measurements and code alone do not isolate hosting wake-up, connection setup, DB time, serialization, or provider time. | New backend logs report slow route duration, SQL query count, and SQL execute time without logging SQL parameters or user data. No keep-alive service was added. |

### Taxonomy status

The taxonomy batching change is already present at deployed commit `d4e4fbe` and was not repeated here. The reported production range after that deployment is 1.54–2.16 seconds. The existing taxonomy tests still pass.

## Changes made

- [question_service.py](./backend/app/services/question_service.py): added a batched student-facing detail loader. It selects base question rows, MCQ content/options, and coding content/examples in bounded set queries, then preserves request order and existing response fields.
- [main.py](./backend/app/main.py): mock detail now calls the batch loader instead of looping over per-question reads. Added safe slow-request logs for route template, status, elapsed milliseconds, SQL statement count, and SQL execute time. Exposed only `Retry-After` through CORS.
- [provider.py](./backend/app/ai/provider.py): provider 429s no longer retry the same provider; sibling models from that provider family are skipped, while a different configured provider can still be tried. Parses numeric and HTTP-date `Retry-After` values and respects explicit delay for other retryable errors.
- [rate_limit.py](./backend/app/ai/rate_limit.py) and [service.py](./backend/app/ai/placo/service.py): application and provider throttling return retry timing; application limiter logs are distinct from provider failure logs.
- [api.ts](./frontend/lib/api.ts): added five-minute browser-memory caching and in-flight deduplication for public company and taxonomy data only; API errors expose `Retry-After` to the UI.
- [placo.tsx](./frontend/components/placo.tsx): blocks same-tick duplicate sends and disables chat retries/submission until the received retry delay expires (five-second local fallback only when a 429 has no header).
- Regression coverage in [test_mock_detail_batch.py](./backend/tests/test_mock_detail_batch.py), [test_ai_features.py](./backend/tests/test_ai_features.py), and [google-auth.test.ts](./frontend/lib/google-auth.test.ts).

No new dependency, migration, index, hosting plan, environment variable, or auth/identity change was introduced. Personalized product progress, mock attempts, and analytics remain uncached.

## Measurements

### Mock detail, local isolated fixture

The test calls the original per-question detail helper to create the baseline, then the optimized `GET /mock-tests/1735` route over equivalent fake rows. It checks full JSON equality and exact response bytes.

| Fixture | Original SQL statements | Optimized SQL statements | Response |
|---|---:|---:|---|
| 10 MCQs | 32 | 5 | Byte-for-byte equal |
| 9 MCQs + 1 coding question | 32 | 7 | Byte-for-byte equal |

The 10-MCQ case removes 27 of 32 SQL executions (84.4%) in the isolated query-count test. This is a query-count result, **not** an endpoint time measurement: the test uses a fake connection and does not measure MySQL round trips, Aiven network time, response serialization under production data, or Render latency.

### Reported production timings

These are user-supplied observations, not measurements collected during this code change:

- `/health`: about 0.45–1.13 s
- `/companies`: about 1.10–1.75 s
- `/taxonomy` after commit `d4e4fbe`: about 1.54–2.16 s
- RSC navigation: mostly 78–312 ms, with some 550–650 ms
- Product and catalog APIs: about 1.94 s and 2.12 s
- mock detail ID `1735`: about 7.69 s in DevTools
- Placo chat: HTTP 429 after about 19.97 s

No after-deploy timing exists yet. The 429 response origin remains unverified; after deployment, `slow_request` plus either `AI application rate limit` or provider `category=rate_limit status=429` logs will distinguish the app limiter from the provider path.

## Tests and checks

Passed locally:

- Backend mock detail batch tests: 2 passed (MCQ and mixed MCQ/coding).
- Backend taxonomy tests: 4 passed.
- Backend authentication runtime tests: 3 passed.
- Backend coding submission route tests: 9 passed.
- Backend AI retry/rate-limit selection: 5 passed, 20 deselected.
- Frontend Vitest suite: 16 tests passed.
- `npm run lint`, `npm run typecheck`, and `npm run build` passed.
- Python `py_compile` and `git diff --check` passed.

The backend test runner's database integration suite was not run: its isolated pipeline runner inspects a configured `placement_platform` source database before building a local test database. I avoided connecting to that external database. TestClient emitted an existing Starlette warning that `httpx` is deprecated for its test client; tests passed.

## Deployment and production verification

There are backend and frontend changes. The backend service in [render.yaml](./render.yaml) uses `backend/` as its root and starts `uvicorn app.main:app`; backend files need a Render deployment. Frontend API cache/retry UI changes need a Vercel deployment. No migration or production setting change is needed.

After review, stage only the task files (leave the prior untracked `PERFORMANCE_AUDIT.md` untouched):

```sh
git add PERFORMANCE_OPTIMIZATION_REPORT.md \
  backend/app/main.py backend/app/services/question_service.py \
  backend/app/ai/provider.py backend/app/ai/rate_limit.py \
  backend/app/ai/placo/service.py backend/tests/test_mock_detail_batch.py \
  backend/tests/test_ai_features.py \
  frontend/lib/api.ts frontend/lib/google-auth.test.ts frontend/components/placo.tsx
git diff --cached --check
git diff --cached
git commit -m "Optimize mock detail queries and AI retries"
git push origin main
```

Then let the connected Render/Vercel deployments complete through their normal deployment flow. Verify Render health and repeat the same DevTools mock detail request for ID `1735` at least 10 times during warm use, recording median and range for total time and response bytes. Confirm its JSON and ten question ordering are unchanged. Render logs should show `route=/mock-tests/{mock_test_id}` with `db_queries=5` for a 10-MCQ mock and a lower `db_time_ms` if MySQL round trips were the dominant cost.

For the API probe, use sequential requests, one at a time (not a load test):

```sh
for i in $(seq 1 10); do
  curl -sS -o /tmp/mock-1735.json \
    -w "run=$i status=%{http_code} ttfb=%{time_starttransfer}s total=%{time_total}s bytes=%{size_download}\n" \
    https://placprep.onrender.com/mock-tests/1735
done
```

For Placo, make one normal request, then inspect logs for either the application-limit marker or a provider failure marker. If the request is still slow but has no SQL time, provider/Render/serialization remains to isolate. Do not repeatedly submit chat requests to force throttling. Confirm the browser waits for a returned `Retry-After` before enabling retry.

## Next work if latency remains

1. If mock detail remains slow while `db_time_ms` drops, compare response bytes and browser JSON parse/render time. If SQL time remains high, inspect query plans/indexes on a representative staging database; do not run `EXPLAIN ANALYZE` or migrations in production for this audit.
2. If product/catalog API time remains high, separate JWT verification, user lookup, progress query, response bytes, and Render time before changing the user-specific response contract.
3. If RSC timing remains high, capture a browser Network/Performance trace and count sidebar prefetch requests before changing Next Link behavior or adding loading boundaries.
4. If dashboard time remains high, measure each personalized analytics query and row count; any index or aggregation change should be justified with staging query plans and metric-equivalence tests.

