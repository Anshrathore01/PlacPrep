"""Run database-free Supabase auth checks; this script never mutates MySQL."""

import subprocess
import sys


if __name__ == "__main__":
    subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            "tests.test_supabase_auth",
            "tests.test_auth_runtime_regression",
        ],
        check=True,
    )
