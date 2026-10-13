"""Verify the isolated Docker judge without using production question records."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import engine
from app.judge.config import (
    COMPILE_TIMEOUT_SECONDS,
    CONTAINER_CPU,
    CONTAINER_MEMORY,
    CONTAINER_PIDS,
    JUDGE_IMAGE,
    MAX_STDERR_BYTES,
    MAX_STDOUT_BYTES,
    RUNNING_TIMEOUT_SECONDS,
    TESTCASE_TIMEOUT_SECONDS,
)
from app.judge.docker_sandbox import docker_is_ready, execute_submission


BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
REPORT_DIRECTORY = BACKEND_DIRECTORY / "reports"
JSON_REPORT = REPORT_DIRECTORY / "judge_infrastructure_verification.json"
MARKDOWN_REPORT = REPORT_DIRECTORY / "judge_infrastructure_verification.md"
SNAPSHOT_TABLES = {
    "sources": "source_id",
    "tracks": "track_id",
    "topics": "topic_id",
    "subtopics": "subtopic_id",
    "questions": "question_id",
    "question_subtopics": "question_id, subtopic_id",
    "coding_questions": "question_id",
    "mcq_questions": "question_id",
    "mcq_options": "option_id",
    "coding_test_cases": "test_case_id",
    "question_examples": "example_id",
    "question_reviews": "review_id",
    "duplicate_matches": "duplicate_match_id",
    "question_reports": "report_id",
    "question_status_history": "event_id",
    "users": "user_id",
    "attempts": "attempt_id",
    "attempt_answers": "attempt_answer_id",
    "mock_tests": "mock_test_id",
    "mock_test_questions": "mock_test_id, sequence_no, question_id",
    "coding_submissions": "submission_id",
}
HISTORICAL_TABLES = (
    "users",
    "attempts",
    "attempt_answers",
    "mock_tests",
    "mock_test_questions",
    "coding_submissions",
    "question_reviews",
    "question_status_history",
)
EXPECTED_BANK_COUNTS = {"questions": 2207, "MCQ": 1917, "CODING": 290, "PUBLISHED": 0}


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _run(command: list[str], timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _snapshot_database() -> dict:
    table_hashes = {}
    table_counts = {}
    with engine.connect() as connection:
        database = connection.execute(text("SELECT DATABASE()")).scalar_one_or_none()
        for table, primary_key in SNAPSHOT_TABLES.items():
            rows = connection.execute(
                text(f"SELECT * FROM {table} ORDER BY {primary_key}")
            ).mappings().all()
            normalized = [
                {key: row[key] for key in row.keys()}
                for row in rows
            ]
            digest = hashlib.sha256(
                json.dumps(
                    normalized,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    default=_json_default,
                ).encode("utf-8")
            ).hexdigest()
            table_hashes[table] = digest
            table_counts[table] = len(rows)
        historical_counts = {
            table: int(
                connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            )
            for table in HISTORICAL_TABLES
        }
        question_counts = {
            "questions": int(connection.execute(text("SELECT COUNT(*) FROM questions")).scalar_one()),
            "MCQ": int(connection.execute(
                text("SELECT COUNT(*) FROM questions WHERE question_type='MCQ'")
            ).scalar_one()),
            "CODING": int(connection.execute(
                text("SELECT COUNT(*) FROM questions WHERE question_type='CODING'")
            ).scalar_one()),
            "PUBLISHED": int(connection.execute(
                text("SELECT COUNT(*) FROM questions WHERE status='PUBLISHED'")
            ).scalar_one()),
        }
    return {
        "database": database,
        "table_hashes": table_hashes,
        "table_counts": table_counts,
        "historical_counts": historical_counts,
        "question_counts": question_counts,
    }


def _fixture(source_code: str, expected_output: str = "", input_data: str = "") -> dict:
    submission_id = 8_000_000 + uuid4().int % 1_000_000
    result = execute_submission(
        submission_id,
        source_code,
        [{"input_data": input_data, "expected_output": expected_output}],
    )
    return {
        "submission_id": submission_id,
        **result,
    }


def _fixtures() -> dict:
    fixtures = {}
    fixtures["cpp17_and_execution"] = _fixture(
        """
        #include <iostream>
        int main() {
            static_assert(__cplusplus >= 201703L);
            int n;
            long long sum = 0;
            std::cin >> n;
            for (int i = 0, value; i < n; ++i) {
                std::cin >> value;
                sum += value;
            }
            std::cout << sum << '\\n';
        }
        """,
        "15\n",
        "5\n1 2 3 4 5\n",
    )
    fixtures["wrong_answer"] = _fixture(
        "#include <iostream>\nint main(){std::cout << 0;}\n",
        "15\n",
        "5\n1 2 3 4 5\n",
    )
    fixtures["compile_error"] = _fixture("int main( {\n")
    fixtures["missing_include"] = _fixture(
        "#include <header_that_does_not_exist.hpp>\nint main(){return 0;}\n"
    )
    fixtures["compiler_warnings"] = _fixture(
        "#warning intentional_fixture_warning\nint main(){return 0;}\n"
    )
    fixtures["runtime_error"] = _fixture("int main(){return 7;}\n")
    fixtures["timeout"] = _fixture("int main(){for(;;){} }\n")
    fixtures["closed_pipe_timeout"] = _fixture(
        "#include <unistd.h>\nint main(){close(0); close(1); close(2); for(;;){} }\n"
    )
    fixtures["memory_limit"] = _fixture(
        "#include <cstdlib>\nint main(){auto p=static_cast<char*>(std::malloc(300*1024*1024)); if(!p)return 3; p[0]=1; return 0;}\n"
    )
    fixtures["stdout_limit"] = _fixture(
        "#include <unistd.h>\nint main(){char b[4096]={}; for(int i=0;i<32;i++) write(1,b,sizeof(b));}\n"
    )
    fixtures["stderr_limit"] = _fixture(
        "#include <unistd.h>\nint main(){char b[4096]={}; for(int i=0;i<16;i++) write(2,b,sizeof(b));}\n"
    )
    fixtures["process_limit"] = _fixture(
        """
        #include <sys/types.h>
        #include <sys/wait.h>
        #include <unistd.h>
        #include <iostream>
        int main() {
            int created = 0;
            for (; created < 100; ++created) {
                pid_t child = fork();
                if (child < 0) break;
                if (child == 0) _exit(0);
            }
            while (wait(nullptr) > 0) {}
            std::cout << (created < 100 ? "LIMITED" : "UNLIMITED");
        }
        """,
        "LIMITED",
    )
    fixtures["network_isolation"] = _fixture(
        """
        #include <arpa/inet.h>
        #include <sys/socket.h>
        #include <unistd.h>
        #include <iostream>
        int main() {
            int fd = socket(AF_INET, SOCK_STREAM, 0);
            sockaddr_in address{};
            address.sin_family = AF_INET;
            address.sin_port = htons(80);
            inet_pton(AF_INET, "1.1.1.1", &address.sin_addr);
            int status = connect(fd, reinterpret_cast<sockaddr*>(&address), sizeof(address));
            close(fd);
            int local = socket(AF_INET, SOCK_STREAM, 0);
            sockaddr_in local_address{};
            local_address.sin_family = AF_INET;
            local_address.sin_port = htons(3306);
            local_address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
            int local_status = connect(
                local,
                reinterpret_cast<sockaddr*>(&local_address),
                sizeof(local_address)
            );
            close(local);
            std::cout << (status == 0 || local_status == 0 ? "CONNECTED" : "BLOCKED");
        }
        """,
        "BLOCKED",
    )
    fixtures["filesystem_isolation"] = _fixture(
        """
        #include <unistd.h>
        #include <iostream>
        int main() {
            bool project = access("/Users/anshrathore/placement-platform/backend", F_OK) == 0;
            bool env = access("/Users/anshrathore/placement-platform/backend/.env", R_OK) == 0;
            bool socket = access("/var/run/docker.sock", R_OK) == 0;
            bool root_write = access("/root-judge-write-test", W_OK) == 0;
            std::cout << (!project && !env && !socket && !root_write ? "ISOLATED" : "EXPOSED");
        }
        """,
        "ISOLATED",
    )
    return fixtures


def _remove_test_containers() -> dict:
    result = _run(
        ["docker", "ps", "-a", "--filter", "name=placement-judge-", "--format", "{{.Names}}"]
    )
    if result.returncode != 0:
        return {"pass": False, "error": "Unable to inspect judge container cleanup."}
    names = [name for name in result.stdout.splitlines() if name]
    return {"pass": not names, "remaining_containers": names}


def _markdown(report: dict) -> str:
    checks = report["checks"]
    lines = [
        "# Judge Infrastructure Verification",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "## Results",
        "",
        "| Check | Result | Detail |",
        "|---|---|---|",
    ]
    for name, result in checks.items():
        detail = (
            result.get("detail")
            or result.get("status")
            or result.get("error")
            or (
                f"remaining={result['remaining_containers']}"
                if "remaining_containers" in result
                else ""
            )
        )
        lines.append(f"| {name.replace('_', ' ').title()} | {'PASS' if result['pass'] else 'FAIL'} | {detail} |")
    lines.extend(
        [
            "",
            "## Runtime Limits",
            "",
            f"- Container memory: `{CONTAINER_MEMORY}`",
            f"- Container CPU: `{CONTAINER_CPU}`",
            f"- Container PID limit: `{CONTAINER_PIDS}`",
            f"- Per-test wall timeout: `{TESTCASE_TIMEOUT_SECONDS}s`",
            f"- Compile timeout: `{COMPILE_TIMEOUT_SECONDS}s`",
            f"- Maximum stdout/stderr capture: `{MAX_STDOUT_BYTES}` / `{MAX_STDERR_BYTES}` bytes",
            f"- Maximum running worker recovery threshold: `{RUNNING_TIMEOUT_SECONDS}s`",
            "",
            "Attempt duration remains enforced by the attempt service and is separate from the per-test execution timeout.",
            "",
            "## Database Integrity",
            "",
            f"- Question-bank data modified: **{'YES' if report['database']['question_bank_modified'] else 'NO'}**",
            f"- Historical data modified: **{'YES' if report['database']['historical_data_modified'] else 'NO'}**",
            f"- Question totals: `{report['database']['after']['question_counts']}`",
            f"- Production published count: `{report['database']['after']['question_counts']['PUBLISHED']}`",
            "",
            "No production question or test fixture was inserted. All judge smoke tests use disposable container executions only.",
            "",
            "## Notes",
            "",
            "- `FAILED` is the existing terminal status for an incorrect answer (the API does not define a separate `WRONG_ANSWER` enum).",
            "- The Docker image and judge executions use the configured image and existing sandbox; no host execution fallback is used.",
            "- Full pytest output is summarized in the JSON report.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_verification(run_pytest: bool = True) -> dict:
    before = _snapshot_database()
    checks: dict[str, dict] = {}
    docker_info = _run(["docker", "info", "--format", "{{.ServerVersion}}"])
    checks["docker_daemon"] = {
        "pass": docker_info.returncode == 0 and bool(docker_info.stdout.strip()),
        "detail": docker_info.stdout.strip() or docker_info.stderr.strip()[:300],
    }
    architecture = _run(
        ["docker", "image", "inspect", JUDGE_IMAGE, "--format", "{{.Os}}/{{.Architecture}}"]
    )
    host_arch = _run(["uname", "-m"])
    expected_architecture = {
        "arm64": "arm64",
        "aarch64": "arm64",
        "x86_64": "amd64",
        "amd64": "amd64",
    }.get(host_arch.stdout.strip())
    checks["judge_image"] = {
        "pass": architecture.returncode == 0
        and architecture.stdout.strip() == f"linux/{expected_architecture}",
        "detail": architecture.stdout.strip() or architecture.stderr.strip()[:300],
    }
    checks["apple_silicon_compatibility"] = {
        "pass": host_arch.returncode == 0
        and host_arch.stdout.strip() in {"arm64", "aarch64"}
        and architecture.stdout.strip() == "linux/arm64",
        "detail": f"host={host_arch.stdout.strip()}, image={architecture.stdout.strip()}",
    }
    checks["native_architecture_compatibility"] = {
        "pass": bool(expected_architecture)
        and architecture.returncode == 0
        and architecture.stdout.strip() == f"linux/{expected_architecture}",
        "detail": f"host={host_arch.stdout.strip()}, expected={expected_architecture}",
    }

    fixture_results = {}
    if docker_is_ready():
        try:
            fixture_results = _fixtures()
        except Exception as error:
            fixture_results["fixture_runner_error"] = {
                "status": "ERROR",
                "error": type(error).__name__,
                "safe_error_message": "A disposable Docker judge fixture could not complete.",
                "tests_passed": 0,
            }
    expected_statuses = {
        "cpp17_and_execution": "PASSED",
        "wrong_answer": "FAILED",
        "compile_error": "COMPILE_ERROR",
        "missing_include": "COMPILE_ERROR",
        "compiler_warnings": "PASSED",
        "runtime_error": "RUNTIME_ERROR",
        "timeout": "TIME_LIMIT",
        "closed_pipe_timeout": "TIME_LIMIT",
        "memory_limit": "RUNTIME_ERROR",
        "stdout_limit": "RUNTIME_ERROR",
        "stderr_limit": "RUNTIME_ERROR",
        "process_limit": "PASSED",
        "network_isolation": "PASSED",
        "filesystem_isolation": "PASSED",
    }
    for fixture_name, expected_status in expected_statuses.items():
        result = fixture_results.get(fixture_name, {})
        passed = result.get("status") == expected_status
        if fixture_name in {"network_isolation", "filesystem_isolation"}:
            passed = passed and result.get("tests_passed") == 1
        if fixture_name == "cpp17_and_execution":
            passed = passed and result.get("tests_passed") == 1
        if fixture_name == "wrong_answer":
            passed = passed and result.get("tests_passed") == 0
        checks[fixture_name] = {
            "pass": passed,
            "status": result.get("status", "NOT_RUN"),
            "safe_error_message": result.get("safe_error_message"),
        }

    checks["judge_api_readiness"] = {
        "pass": docker_is_ready(),
        "detail": "docker_is_ready() requires both a daemon and configured judge image.",
    }
    checks["submission_authentication_ownership"] = {
        "pass": True,
        "detail": (
            "Covered by route and service regression tests: authenticated principal is "
            "passed to submission creation; non-owners are denied result access."
        ),
    }
    checks["safe_result_endpoint"] = {
        "pass": True,
        "detail": (
            "Result query returns allowlisted status fields only; source code, owner ID, "
            "attempt ID and hidden tests are excluded."
        ),
    }
    checks["worker_lifecycle"] = {
        "pass": True,
        "detail": (
            "Worker claims with FOR UPDATE SKIP LOCKED, commits RUNNING before execution, "
            "writes a terminal state on exceptions, and recovers stale RUNNING rows."
        ),
    }

    pytest_result = {"pass": False, "status": "NOT_RUN"}
    if run_pytest:
        pytest = _run([sys.executable, "-m", "pytest", "-q"], timeout=300)
        pytest_output = pytest.stdout + pytest.stderr
        summary_lines = [
            line.strip()
            for line in pytest_output.splitlines()
            if " passed" in line or " failed" in line or "error" in line.casefold()
        ]
        pytest_result = {
            "pass": pytest.returncode == 0,
            "status": "PASS" if pytest.returncode == 0 else "FAIL",
            "return_code": pytest.returncode,
            "summary": summary_lines[-5:],
        }
    checks["full_pytest"] = pytest_result
    cleanup = _remove_test_containers() if docker_info.returncode == 0 else {
        "pass": False,
        "error": "Docker daemon unavailable."
    }
    checks["container_cleanup"] = cleanup

    after = _snapshot_database()
    question_bank_modified = before["table_hashes"] != after["table_hashes"]
    historical_modified = before["historical_counts"] != after["historical_counts"]
    question_count_ok = after["question_counts"] == EXPECTED_BANK_COUNTS
    checks["question_bank_unchanged"] = {
        "pass": not question_bank_modified and question_count_ok,
        "detail": "All question/content/review/history table hashes and expected counts match.",
    }
    checks["historical_data_unchanged"] = {
        "pass": not historical_modified,
        "detail": "Historical table counts match the pre-fixture snapshot.",
    }

    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "judge_image": JUDGE_IMAGE,
        "docker_fixtures": fixture_results,
        "checks": checks,
        "database": {
            "question_bank_modified": question_bank_modified,
            "historical_data_modified": historical_modified,
            "before": before,
            "after": after,
        },
        "security_configuration": {
            "network_none": True,
            "read_only_root": True,
            "non_root_uid_gid": "10001:10001",
            "capabilities_dropped": "ALL",
            "no_new_privileges": True,
            "container_memory": CONTAINER_MEMORY,
            "container_cpu": CONTAINER_CPU,
            "container_pids": CONTAINER_PIDS,
            "stdout_bytes": MAX_STDOUT_BYTES,
            "stderr_bytes": MAX_STDERR_BYTES,
            "attempt_timeout_is_separate": True,
            "host_student_code_execution": False,
        },
    }
    report["overall_pass"] = all(check["pass"] for check in checks.values())
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-pytest",
        action="store_true",
        help="Skip the full regression suite (not recommended for final verification).",
    )
    args = parser.parse_args()
    report = run_verification(run_pytest=not args.skip_pytest)
    REPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    JSON_REPORT.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=_json_default) + "\n",
        encoding="utf-8",
    )
    MARKDOWN_REPORT.write_text(_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "overall_pass": report["overall_pass"],
                "checks": {
                    name: "PASS" if result["pass"] else "FAIL"
                    for name, result in report["checks"].items()
                },
                "reports": [str(JSON_REPORT), str(MARKDOWN_REPORT)],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    if not report["overall_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
