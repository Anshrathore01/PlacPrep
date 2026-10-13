import json
import os
import resource
import selectors
import signal
import subprocess
import sys
import time


WORKSPACE = "/work"


def _outputs_match(actual, expected):
    normalized_actual = actual.replace("\r\n", "\n").replace("\r", "\n").rstrip()
    normalized_expected = expected.replace("\r\n", "\n").replace("\r", "\n").rstrip()
    return normalized_actual == normalized_expected


def _capped_output(process, input_data, timeout_seconds, stdout_limit, stderr_limit):
    input_bytes = input_data.encode("utf-8")
    input_offset = 0
    stdin = process.stdin
    if input_bytes:
        os.set_blocking(stdin.fileno(), False)
    os.set_blocking(process.stdout.fileno(), False)
    os.set_blocking(process.stderr.fileno(), False)
    selector = selectors.DefaultSelector()
    if input_bytes:
        selector.register(stdin, selectors.EVENT_WRITE, "stdin")
    else:
        stdin.close()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    output = {"stdout": bytearray(), "stderr": bytearray()}
    limits = {"stdout": stdout_limit, "stderr": stderr_limit}
    started = time.monotonic()

    try:
        while selector.get_map() or process.poll() is None:
            remaining = timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                return None, None, "TIME_LIMIT"
            if not selector.get_map():
                time.sleep(min(remaining, 0.01))
                continue
            for key, _ in selector.select(min(remaining, 0.1)):
                if key.data == "stdin":
                    try:
                        written = os.write(
                            key.fileobj.fileno(),
                            input_bytes[input_offset:input_offset + 8192],
                        )
                    except BlockingIOError:
                        continue
                    except BrokenPipeError:
                        selector.unregister(key.fileobj)
                        stdin.close()
                        continue
                    input_offset += written
                    if input_offset == len(input_bytes):
                        selector.unregister(key.fileobj)
                        stdin.close()
                    continue

                block = os.read(key.fileobj.fileno(), 8192)
                if not block:
                    selector.unregister(key.fileobj)
                    continue
                output[key.data].extend(block)
                if len(output[key.data]) > limits[key.data]:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                    return None, None, "OUTPUT_LIMIT"

        return (
            bytes(output["stdout"]).decode("utf-8", errors="replace"),
            bytes(output["stderr"]).decode("utf-8", errors="replace"),
            process.wait(),
        )
    finally:
        selector.close()
        for stream in (stdin, process.stdout, process.stderr):
            if not stream.closed:
                stream.close()


def _set_compiler_limits():
    resource.setrlimit(resource.RLIMIT_CPU, (3, 4))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _set_program_limits():
    resource.setrlimit(resource.RLIMIT_CPU, (3, 4))
    resource.setrlimit(resource.RLIMIT_AS, (192 * 1024 * 1024, 192 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def main():
    payload = json.load(sys.stdin)
    limits = payload["limits"]
    source_path = os.path.join(WORKSPACE, "main.cpp")
    binary_path = os.path.join(WORKSPACE, "program")
    with open(source_path, "w", encoding="utf-8") as source_file:
        source_file.write(payload["source_code"])

    compile_start = time.monotonic()
    try:
        compiler = subprocess.Popen(
            ["g++", "-std=c++17", "-O2", "-pipe", "-o", binary_path, source_path],
            cwd=WORKSPACE,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            preexec_fn=_set_compiler_limits,
        )
        compiler_stdout, compiler_stderr, compile_status = _capped_output(
            compiler,
            "",
            limits["compile_timeout_seconds"],
            limits["compile_output_bytes"],
            limits["compile_output_bytes"],
        )
    except OSError:
        print(json.dumps({
            "status": "RUNTIME_ERROR",
            "tests_passed": 0,
            "tests_total": len(payload["test_cases"]),
            "score": 0,
            "execution_time_ms": int((time.monotonic() - compile_start) * 1000),
            "safe_error_message": "The compiler could not be started.",
        }))
        return

    if compile_status == "TIME_LIMIT":
        print(json.dumps({
            "status": "TIME_LIMIT",
            "tests_passed": 0,
            "tests_total": len(payload["test_cases"]),
            "score": 0,
            "execution_time_ms": int((time.monotonic() - compile_start) * 1000),
            "safe_error_message": "Compilation exceeded the configured time limit.",
        }))
        return

    if compile_status != 0:
        diagnostic = compiler_stderr or compiler_stdout or (
            "Compiler diagnostics exceeded the configured output limit."
            if compile_status == "OUTPUT_LIMIT"
            else "Compilation failed."
        )
        print(json.dumps({
            "status": "COMPILE_ERROR",
            "tests_passed": 0,
            "tests_total": len(payload["test_cases"]),
            "score": 0,
            "execution_time_ms": int((time.monotonic() - compile_start) * 1000),
            "compiler_output": diagnostic,
        }))
        return

    passed = 0
    total_started = time.monotonic()
    outcome = "PASSED"
    safe_error_message = None
    for case in payload["test_cases"]:
        try:
            process = subprocess.Popen(
                [binary_path],
                cwd=WORKSPACE,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                preexec_fn=_set_program_limits,
            )
            stdout, stderr, exit_code = _capped_output(
                process,
                case["input_data"],
                limits["testcase_timeout_seconds"],
                limits["stdout_bytes"],
                limits["stderr_bytes"],
            )
        except (OSError, ValueError):
            outcome = "RUNTIME_ERROR"
            safe_error_message = "The program could not be executed safely."
            break
        if exit_code == "TIME_LIMIT":
            outcome = "TIME_LIMIT"
            safe_error_message = "A test case exceeded the configured time limit."
            break
        if exit_code == "OUTPUT_LIMIT":
            outcome = "RUNTIME_ERROR"
            safe_error_message = "The program exceeded the configured output limit."
            break
        if exit_code != 0:
            outcome = "RUNTIME_ERROR"
            safe_error_message = "The program terminated with a runtime error or resource violation."
            break

        if not _outputs_match(stdout, case["expected_output"]):
            outcome = "FAILED"
            break
        passed += 1

    print(json.dumps({
        "status": outcome,
        "tests_passed": passed,
        "tests_total": len(payload["test_cases"]),
        "score": 0,
        "execution_time_ms": int((time.monotonic() - total_started) * 1000),
        "safe_error_message": safe_error_message,
    }))


if __name__ == "__main__":
    main()
