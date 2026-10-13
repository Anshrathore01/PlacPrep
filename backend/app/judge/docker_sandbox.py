import json
import logging
import re
import subprocess
from typing import Any

from app.judge.config import (
    COMPILE_TIMEOUT_SECONDS,
    CONTAINER_CPU,
    CONTAINER_MEMORY,
    CONTAINER_PIDS,
    CONTAINER_TMP_SIZE,
    JUDGE_IMAGE,
    MAX_CASE_BYTES,
    MAX_COMPILE_OUTPUT_BYTES,
    MAX_SAFE_ERROR_BYTES,
    MAX_SOURCE_BYTES,
    MAX_STDERR_BYTES,
    MAX_STDOUT_BYTES,
    MAX_TEST_CASES,
    MAX_TOTAL_CASE_BYTES,
    TESTCASE_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


class JudgeUnavailable(RuntimeError):
    """Raised when the Docker daemon or pinned judge image is not ready."""


class JudgeConfigurationError(RuntimeError):
    """Raised when persisted question test data cannot be judged safely."""


def validate_judge_input(source_code: str, test_cases: list[dict]) -> None:
    if not source_code.strip():
        raise JudgeConfigurationError("Source code is empty.")
    if len(source_code.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise JudgeConfigurationError("Source code exceeds the size limit.")
    if not test_cases:
        raise JudgeConfigurationError("No test cases are configured.")
    if len(test_cases) > MAX_TEST_CASES:
        raise JudgeConfigurationError("Question exceeds the supported test-case limit.")

    total_bytes = 0
    for case in test_cases:
        input_data = case.get("input_data")
        expected_output = case.get("expected_output")
        if input_data is None or expected_output is None:
            raise JudgeConfigurationError("A test case is missing input or expected output.")
        case_bytes = len(input_data.encode("utf-8")) + len(expected_output.encode("utf-8"))
        if case_bytes > MAX_CASE_BYTES:
            raise JudgeConfigurationError("A test case exceeds the configured size limit.")
        total_bytes += case_bytes
    if total_bytes > MAX_TOTAL_CASE_BYTES:
        raise JudgeConfigurationError("Question test cases exceed the configured size limit.")


def docker_is_ready() -> bool:
    try:
        daemon = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if daemon.returncode != 0 or not daemon.stdout.strip():
            return False
        image = subprocess.run(
            ["docker", "image", "inspect", JUDGE_IMAGE, "--format", "{{.Id}}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return image.returncode == 0 and bool(image.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return False


def normalize_output(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.rstrip()


def outputs_match(actual: str, expected: str) -> bool:
    return normalize_output(actual) == normalize_output(expected)


def sanitize_diagnostic(value: str, maximum: int) -> str:
    value = re.sub(r"(?:/[A-Za-z0-9_.+-]+)+", "[sandbox]", value)
    value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)
    value = value.replace("\x00", "")
    return value[-maximum:].strip()


def _container_name(submission_id: int) -> str:
    return f"placement-judge-{submission_id}"


def _remove_container(name: str) -> None:
    try:
        result = subprocess.run(
            ["docker", "rm", "--force", name],
            capture_output=True,
            timeout=5,
            check=False,
        )
        if result.returncode and b"No such container" not in result.stderr:
            logger.error(
                "Could not clean up judge container %s: docker rm exited %s",
                name,
                result.returncode,
            )
    except (OSError, subprocess.TimeoutExpired):
        logger.exception("Could not clean up judge container %s", name)


def cleanup_submission_container(submission_id: int) -> None:
    _remove_container(_container_name(submission_id))


def execute_submission(
    submission_id: int,
    source_code: str,
    test_cases: list[dict],
) -> dict[str, Any]:
    validate_judge_input(source_code, test_cases)
    if not docker_is_ready():
        raise JudgeUnavailable("Docker daemon and the configured judge image are required.")

    payload = {
        "source_code": source_code,
        "test_cases": [
            {
                "input_data": case["input_data"],
                "expected_output": case["expected_output"],
            }
            for case in test_cases
        ],
        "limits": {
            "compile_timeout_seconds": COMPILE_TIMEOUT_SECONDS,
            "testcase_timeout_seconds": TESTCASE_TIMEOUT_SECONDS,
            "stdout_bytes": MAX_STDOUT_BYTES,
            "stderr_bytes": MAX_STDERR_BYTES,
            "compile_output_bytes": MAX_COMPILE_OUTPUT_BYTES,
        },
    }
    name = _container_name(submission_id)
    command = [
        "docker", "run", "--rm", "--interactive", "--name", name,
        "--network", "none",
        "--read-only",
        "--memory", CONTAINER_MEMORY,
        "--memory-swap", CONTAINER_MEMORY,
        "--cpus", CONTAINER_CPU,
        "--pids-limit", str(CONTAINER_PIDS),
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--user", "10001:10001",
        "--tmpfs", f"/work:rw,exec,nosuid,nodev,size={CONTAINER_TMP_SIZE},mode=700,uid=10001,gid=10001",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m,mode=700,uid=10001,gid=10001",
        JUDGE_IMAGE,
        "python3", "/opt/judge/runner.py",
    ]
    try:
        _remove_container(name)
        try:
            completed = subprocess.run(
                command,
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=COMPILE_TIMEOUT_SECONDS
                + len(test_cases) * TESTCASE_TIMEOUT_SECONDS
                + 10,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "TIME_LIMIT",
                "tests_passed": 0,
                "tests_total": len(test_cases),
                "score": 0,
                "execution_time_ms": None,
                "safe_error_message": "The judge exceeded its execution time limit.",
            }
        except OSError as error:
            raise JudgeUnavailable("Docker is unavailable to the judge worker.") from error

        if len(completed.stdout.encode("utf-8", errors="replace")) > 128_000:
            logger.error("Judge runner returned oversized output for submission %s", submission_id)
            return {
                "status": "RUNTIME_ERROR",
                "tests_passed": 0,
                "tests_total": len(test_cases),
                "score": 0,
                "execution_time_ms": None,
                "safe_error_message": "The judge could not safely process the execution result.",
            }
        if completed.returncode != 0:
            logger.error(
                "Judge container failed for submission %s with code %s",
                submission_id,
                completed.returncode,
            )
            return {
                "status": "RUNTIME_ERROR",
                "tests_passed": 0,
                "tests_total": len(test_cases),
                "score": 0,
                "execution_time_ms": None,
                "safe_error_message": "The isolated judge could not complete this submission.",
            }
        try:
            result = json.loads(completed.stdout)
        except (json.JSONDecodeError, TypeError):
            logger.exception("Invalid runner response for submission %s", submission_id)
            return {
                "status": "RUNTIME_ERROR",
                "tests_passed": 0,
                "tests_total": len(test_cases),
                "score": 0,
                "execution_time_ms": None,
                "safe_error_message": "The isolated judge returned an invalid result.",
            }
        if result.get("status") == "COMPILE_ERROR":
            result["safe_error_message"] = sanitize_diagnostic(
                result.get("compiler_output", ""), MAX_SAFE_ERROR_BYTES
            ) or "Compilation failed."
            result.pop("compiler_output", None)
        return result
    finally:
        _remove_container(name)
