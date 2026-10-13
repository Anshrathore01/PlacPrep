import unittest
from decimal import Decimal
from uuid import uuid4
from unittest.mock import MagicMock, Mock, patch

from fastapi import HTTPException

from app.judge.config import MAX_CASE_BYTES, MAX_SOURCE_BYTES
from app.judge.docker_sandbox import (
    JudgeConfigurationError,
    docker_is_ready,
    execute_submission,
    normalize_output,
    outputs_match,
    validate_judge_input,
)
from app.services.coding_service import calculate_submission_score, get_submission
from app.services import judge_service


class JudgeOutputTests(unittest.TestCase):
    def test_output_normalization_preserves_internal_whitespace(self):
        self.assertEqual(normalize_output("  5  6 \r\n7\t \r"), "  5  6 \n7")

    def test_output_comparison_is_exact_except_line_endings_and_trailing_whitespace(self):
        self.assertTrue(outputs_match("5 6\r\n7\r\n", "5 6\n7"))
        self.assertTrue(outputs_match("answer \t\n\n", "answer"))
        self.assertFalse(outputs_match("5  6\n", "5 6"))
        self.assertFalse(outputs_match("answer\nextra", "answer"))
        self.assertFalse(outputs_match("", "answer"))
        self.assertFalse(outputs_match("answer", ""))
        self.assertTrue(outputs_match("one\ntwo\n", "one\ntwo"))


class JudgeInputTests(unittest.TestCase):
    def test_valid_source_and_case_are_accepted(self):
        validate_judge_input(
            "int main() {}",
            [{"input_data": "1\n", "expected_output": "1\n"}],
        )

    def test_source_byte_limit_is_enforced(self):
        with self.assertRaises(JudgeConfigurationError):
            validate_judge_input(
                "x" * (MAX_SOURCE_BYTES + 1),
                [{"input_data": "", "expected_output": ""}],
            )

    def test_test_case_byte_limit_is_enforced(self):
        with self.assertRaises(JudgeConfigurationError):
            validate_judge_input(
                "int main() {}",
                [{"input_data": "x" * (MAX_CASE_BYTES + 1), "expected_output": ""}],
            )


class CodingScoreTests(unittest.TestCase):
    def test_weighted_partial_and_complete_score(self):
        cases = [{"points": 1}, {"points": 3}]

        self.assertEqual(
            calculate_submission_score(Decimal("2.00"), cases, 1),
            Decimal("0.50"),
        )
        self.assertEqual(
            calculate_submission_score(Decimal("2.00"), cases, 2),
            Decimal("2.00"),
        )

    def test_score_uses_two_decimal_places(self):
        cases = [{"points": 1}, {"points": 2}]

        self.assertEqual(
            calculate_submission_score(Decimal("1.00"), cases, 1),
            Decimal("0.33"),
        )


class SubmissionOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.row = {
            "submission_id": 10,
            "user_id": 2,
            "question_id": 3,
            "language": "C++17",
            "status": "PASSED",
            "tests_passed": 5,
            "tests_total": 5,
            "score": Decimal("10.00"),
            "submitted_at": None,
            "completed_at": None,
            "safe_error_message": None,
        }
        self.connection = Mock()
        self.connection.execute.return_value.mappings.return_value.first.return_value = self.row

    def test_submission_owner_gets_only_safe_result_fields(self):
        result = get_submission(
            self.connection,
            10,
            {"user_id": 2, "role": "STUDENT"},
        )

        self.assertEqual(result["status"], "PASSED")
        self.assertEqual(result["tests_passed"], 5)
        self.assertNotIn("user_id", result)
        self.assertNotIn("source_code", result)
        self.assertNotIn("attempt_id", result)

    def test_other_student_cannot_read_submission(self):
        with self.assertRaises(HTTPException) as raised:
            get_submission(
                self.connection,
                10,
                {"user_id": 4, "role": "STUDENT"},
            )

        self.assertEqual(raised.exception.status_code, 403)

    def test_admin_can_read_submission_without_sensitive_fields(self):
        result = get_submission(
            self.connection,
            10,
            {"user_id": 4, "role": "ADMIN"},
        )

        self.assertEqual(result["submission_id"], 10)
        self.assertNotIn("user_id", result)
        self.assertNotIn("source_code", result)


class JudgeWorkerFailureTests(unittest.TestCase):
    def test_unexpected_worker_error_is_persisted_as_safe_terminal_failure(self):
        transaction = MagicMock()
        connection = MagicMock()
        transaction.__enter__.return_value = connection

        with (
            patch(
                "app.services.judge_service._load_judge_data",
                side_effect=RuntimeError("private /Users/example/.env path"),
            ),
            patch(
                "app.services.judge_service.engine.begin",
                return_value=transaction,
            ),
        ):
            judge_service.process_submission(
                {"submission_id": 12345, "source_code": "int main() {}"}
            )

        statement, parameters = connection.execute.call_args.args
        self.assertIn("UPDATE coding_submissions", str(statement))
        self.assertEqual(parameters["status"], "RUNTIME_ERROR")
        self.assertNotIn("/Users", parameters["message"])
        self.assertIn("could not complete", parameters["message"])


@unittest.skipUnless(docker_is_ready(), "Docker and configured judge image are required")
class DockerJudgeIntegrationTests(unittest.TestCase):
    def _execute(self, source_code, expected_output="", input_data=""):
        return execute_submission(
            9_000_000 + uuid4().int % 900_000,
            source_code,
            [{"input_data": input_data, "expected_output": expected_output}],
        )

    def test_cpp17_compile_and_execute_sum_fixture(self):
        result = self._execute(
            """
            #include <iostream>
            int main() {
                int count;
                long long sum = 0;
                std::cin >> count;
                for (int i = 0, value; i < count; ++i) {
                    std::cin >> value;
                    sum += value;
                }
                std::cout << sum << '\\n';
            }
            """,
            "15\n",
            "5\n1 2 3 4 5\n",
        )

        self.assertEqual(result["status"], "PASSED")
        self.assertEqual(result["tests_passed"], 1)
        self.assertEqual(result["tests_total"], 1)

    def test_wrong_answer_is_failed_deterministically(self):
        result = self._execute(
            "#include <iostream>\nint main(){std::cout << 0;}\n",
            "15\n",
            "5\n1 2 3 4 5\n",
        )

        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["tests_passed"], 0)

    def test_syntax_error_maps_to_compile_error_and_is_sanitized(self):
        result = self._execute("int main( {\n")

        self.assertEqual(result["status"], "COMPILE_ERROR")
        self.assertNotIn("/work", result.get("safe_error_message", ""))

    def test_missing_include_maps_to_compile_error(self):
        result = self._execute(
            "#include <header_that_does_not_exist.hpp>\nint main(){return 0;}\n"
        )

        self.assertEqual(result["status"], "COMPILE_ERROR")

    def test_compiler_warnings_do_not_prevent_execution(self):
        result = self._execute(
            "#warning intentional_fixture_warning\nint main(){return 0;}\n"
        )

        self.assertEqual(result["status"], "PASSED")

    def test_nonzero_exit_maps_to_runtime_error(self):
        result = self._execute("int main(){return 7;}\n")

        self.assertEqual(result["status"], "RUNTIME_ERROR")

    def test_infinite_loop_is_timed_out(self):
        result = self._execute("int main(){for(;;){} }\n")

        self.assertEqual(result["status"], "TIME_LIMIT")

    def test_timeout_remains_enforced_after_program_closes_all_pipes(self):
        result = self._execute(
            "#include <unistd.h>\nint main(){close(0); close(1); close(2); for(;;){} }\n"
        )

        self.assertEqual(result["status"], "TIME_LIMIT")

    def test_memory_limit_terminates_program(self):
        result = self._execute(
            "#include <cstdlib>\nint main(){auto p=static_cast<char*>(std::malloc(300*1024*1024)); if(!p)return 3; p[0]=1; return 0;}\n"
        )

        self.assertEqual(result["status"], "RUNTIME_ERROR")

    def test_stdout_limit_terminates_program(self):
        result = self._execute(
            "#include <unistd.h>\nint main(){char b[4096]={}; for(int i=0;i<32;i++) write(1,b,sizeof(b));}\n"
        )

        self.assertEqual(result["status"], "RUNTIME_ERROR")

    def test_process_limit_is_enforced(self):
        result = self._execute(
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

        self.assertEqual(result["status"], "PASSED")

    def test_network_and_host_project_paths_are_not_accessible(self):
        network = self._execute(
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
        filesystem = self._execute(
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

        self.assertEqual(network["status"], "PASSED")
        self.assertEqual(filesystem["status"], "PASSED")


if __name__ == "__main__":
    unittest.main()
