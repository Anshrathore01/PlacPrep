# Judge Infrastructure Verification

Generated: 2026-09-30T06:39:55.669977+05:30

## Results

| Check | Result | Detail |
|---|---|---|
| Docker Daemon | PASS | 28.5.2 |
| Judge Image | PASS | linux/arm64 |
| Apple Silicon Compatibility | PASS | host=arm64, image=linux/arm64 |
| Native Architecture Compatibility | PASS | host=arm64, expected=arm64 |
| Cpp17 And Execution | PASS | PASSED |
| Wrong Answer | PASS | FAILED |
| Compile Error | PASS | COMPILE_ERROR |
| Missing Include | PASS | COMPILE_ERROR |
| Compiler Warnings | PASS | PASSED |
| Runtime Error | PASS | RUNTIME_ERROR |
| Timeout | PASS | TIME_LIMIT |
| Closed Pipe Timeout | PASS | TIME_LIMIT |
| Memory Limit | PASS | RUNTIME_ERROR |
| Stdout Limit | PASS | RUNTIME_ERROR |
| Stderr Limit | PASS | RUNTIME_ERROR |
| Process Limit | PASS | PASSED |
| Network Isolation | PASS | PASSED |
| Filesystem Isolation | PASS | PASSED |
| Judge Api Readiness | PASS | docker_is_ready() requires both a daemon and configured judge image. |
| Submission Authentication Ownership | PASS | Covered by route and service regression tests: authenticated principal is passed to submission creation; non-owners are denied result access. |
| Safe Result Endpoint | PASS | Result query returns allowlisted status fields only; source code, owner ID, attempt ID and hidden tests are excluded. |
| Worker Lifecycle | PASS | Worker claims with FOR UPDATE SKIP LOCKED, commits RUNNING before execution, writes a terminal state on exceptions, and recovers stale RUNNING rows. |
| Full Pytest | PASS | PASS |
| Container Cleanup | PASS | remaining=[] |
| Question Bank Unchanged | PASS | All question/content/review/history table hashes and expected counts match. |
| Historical Data Unchanged | PASS | Historical table counts match the pre-fixture snapshot. |

## Runtime Limits

- Container memory: `256m`
- Container CPU: `1`
- Container PID limit: `32`
- Per-test wall timeout: `2s`
- Compile timeout: `15s`
- Maximum stdout/stderr capture: `64000` / `16000` bytes
- Maximum running worker recovery threshold: `245s`

Attempt duration remains enforced by the attempt service and is separate from the per-test execution timeout.

## Database Integrity

- Question-bank data modified: **NO**
- Historical data modified: **NO**
- Question totals: `{'questions': 2207, 'MCQ': 1917, 'CODING': 290, 'PUBLISHED': 0}`
- Production published count: `0`

No production question or test fixture was inserted. All judge smoke tests use disposable container executions only.

## Notes

- `FAILED` is the existing terminal status for an incorrect answer (the API does not define a separate `WRONG_ANSWER` enum).
- The Docker image and judge executions use the configured image and existing sandbox; no host execution fallback is used.
- Full pytest output is summarized in the JSON report.
