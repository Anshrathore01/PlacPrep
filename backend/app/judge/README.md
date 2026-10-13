# Isolated C++17 Judge

## Prerequisites and local setup

Install and start Docker Desktop (or a compatible Docker Engine). Confirm the
active context points at the running daemon:

```sh
docker --version
docker context ls
docker info
```

On Apple Silicon, use the Docker Desktop `desktop-linux` context and build the
native ARM64 image:

```sh
cd backend/app/judge
docker build --platform linux/arm64 -t placement-cpp-judge:1.0.0 -f Dockerfile .
docker image inspect placement-cpp-judge:1.0.0 --format '{{.Os}}/{{.Architecture}}'
```

The expected local image platform is `linux/arm64`. For an AMD64 deployment,
build and verify a separate native image:

```sh
docker build --platform linux/amd64 -t placement-cpp-judge:1.0.0 -f Dockerfile .
docker image inspect placement-cpp-judge:1.0.0 --format '{{.Os}}/{{.Architecture}}'
```

Do not use a mismatched platform without deliberately enabling and measuring
emulation. The base is pinned to
`gcc:14.2.0-bookworm@sha256:b99b86a28812b1e6453a231a947dc43d76fe192788a12f344a9b568bf9f5d24c`.
The compiler is GCC 14.2.0; compilation uses `g++ -std=c++17 -O2 -pipe`.

The API and worker require both a live Docker daemon and the configured image
(`JUDGE_DOCKER_IMAGE`, default `placement-cpp-judge:1.0.0`). The application
fails closed when either is unavailable. Student source is never run on the
API/worker host. Start a worker separately:

```sh
cd backend
source venv/bin/activate
python -m app.judge.worker
```

## Health check and disposable verification

Run the infrastructure verifier from `backend`:

```sh
python scripts/verify_judge_infrastructure.py
```

It runs disposable C++ fixtures through the real judge and then the full pytest
suite. It does not create production questions or test cases. Its JSON and
Markdown results are written to:

- `reports/judge_infrastructure_verification.json`
- `reports/judge_infrastructure_verification.md`

Use `--skip-pytest` only when a separate full test run is being performed.
`docker info` alone is not a judge health check: the verifier also confirms the
configured image, compiler/execution, failure states, limits, network and
filesystem isolation, and cleanup.

## Execution and worker lifecycle

The worker claims database rows with `FOR UPDATE SKIP LOCKED`, commits the
`RUNNING` state before execution, and records terminal outcomes separately. It
recovers abandoned `RUNNING` rows after 245 seconds, longer than the maximum
submission execution deadline, and removes stale named containers. Container
cleanup is also attempted in a `finally` block. Each test case runs separately
inside the isolated container; hidden inputs and expected outputs are never
returned by the student-facing submission-result endpoint.

Attempt expiry and the judge's per-test timeout are separate checks. The
attempt service enforces the assessment duration; the judge enforces a
15-second compile timeout and a 2-second wall-clock timeout for each program
execution.

## Security limits

Every run uses:

- `--network none`
- read-only container root filesystem
- UID/GID `10001:10001` (non-root)
- all Linux capabilities dropped and `no-new-privileges`
- 256 MiB container memory, one CPU, and 32 PIDs
- an 80 MiB writable `/work` tmpfs and 16 MiB non-executable `/tmp`
- 3-second CPU, 192 MiB address-space, and 1 MiB file-size limits per
  compiler/program process
- 64 KiB stdout and 16 KiB stderr capture limits (8 KiB compiler diagnostics)
- automatic container removal and explicit cleanup

Source and test input are sent over stdin. No project directory, `.env`,
database credentials, Docker socket, host path, or other submission is mounted
into the container. The only writable locations are the per-container tmpfs
mounts; the working directory is private to that container. Docker daemon
access remains a privileged host capability and must only be granted to trusted
application operators.

## Results and output comparison

The lifecycle is `QUEUED -> RUNNING -> PASSED | FAILED | COMPILE_ERROR |
RUNTIME_ERROR | TIME_LIMIT`. `FAILED` is the existing terminal state for a
wrong answer; there is no separate `WRONG_ANSWER` database enum. A Docker or
worker failure is recorded as a safe terminal runtime failure rather than
leaving a submission indefinitely in `RUNNING`. The worker's row locking
prevents two workers from claiming the same queued submission.

Output comparison normalizes CRLF/CR to LF and ignores trailing whitespace at
the end of the complete output, including the final newline. It preserves
internal whitespace and line structure: `5  6` does not match `5 6`, and extra
non-whitespace output fails.

## Troubleshooting

- **Cannot connect to Docker daemon:** start Docker Desktop, then check
  `docker context ls` and `docker info`. Do not point the application at a
  different or remote daemon without reviewing its trust boundary.
- **Judge image unavailable:** build the pinned Dockerfile with the host's
  intended platform and configured tag; verify using `docker image inspect`.
- **Architecture mismatch:** compare `uname -m` and image `Os/Architecture`.
  Rebuild for the target platform instead of relying on unmeasured emulation.
- **Compilation/runtime failures:** student-visible diagnostics are sanitized
  and bounded. Detailed infrastructure diagnostics belong in trusted server
  logs, not API responses.
- **Containers remain after interruption:** inspect `docker ps -a` for
  `placement-judge-*`; the worker recovers stale submissions and the verifier
  reports containers that remain after its fixtures.
