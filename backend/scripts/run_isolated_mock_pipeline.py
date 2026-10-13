"""Run backend integration tests in an ephemeral, schema-only MySQL container."""

import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

from sqlalchemy import MetaData, create_engine, inspect, text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.database import DB_NAME, engine as source_engine


TEST_DATABASE = "placement_mock_pipeline_test"
MYSQL_IMAGE = "mysql:8.4.11"
TARGET_CSV = BACKEND_ROOT / "data" / "1681_mcq_reconstructed_complete.csv"
TESTS = ["tests"]


def _assert_safe_source_database():
    if os.getenv("DATABASE_URL"):
        raise RuntimeError(
            "Unset DATABASE_URL before starting the schema-only source inspection."
        )
    if DB_NAME != "placement_platform":
        raise RuntimeError(
            "The configured schema source must be placement_platform."
        )
    with source_engine.connect() as connection:
        actual_name = connection.exec_driver_sql("SELECT DATABASE()").scalar_one()
    if actual_name != "placement_platform":
        raise RuntimeError("Connected source schema is not placement_platform.")


def _production_fingerprint(question_ids):
    with source_engine.connect() as connection:
        totals = {
            "questions": int(connection.execute(
                text("SELECT COUNT(*) FROM questions")
            ).scalar_one()),
            "mcq_questions": int(connection.execute(
                text("SELECT COUNT(*) FROM questions WHERE question_type = 'MCQ'")
            ).scalar_one()),
            "coding_questions": int(connection.execute(
                text("SELECT COUNT(*) FROM questions WHERE question_type = 'CODING'")
            ).scalar_one()),
            "mock_tests": int(connection.execute(
                text("SELECT COUNT(*) FROM mock_tests")
            ).scalar_one()),
            "mock_test_questions": int(connection.execute(
                text("SELECT COUNT(*) FROM mock_test_questions")
            ).scalar_one()),
        }
        placeholders = ", ".join(f":id_{index}" for index in range(len(question_ids)))
        params = {f"id_{index}": value for index, value in enumerate(question_ids)}
        question_rows = connection.execute(
            text(f"""
                SELECT q.question_id, q.question_type, q.status, q.difficulty,
                       q.track_id, q.source_id, q.source_question_number,
                       q.title, q.content_hash, q.source_metadata,
                       mq.question_text, mq.explanation, mq.correct_option_key,
                       mq.is_multiple_correct
                FROM questions q
                LEFT JOIN mcq_questions mq ON mq.question_id = q.question_id
                WHERE q.question_id IN ({placeholders})
                ORDER BY q.question_id
            """),
            params,
        ).mappings().all()
        options = connection.execute(
            text(f"""
                SELECT question_id, option_key, option_text, display_order
                FROM mcq_options
                WHERE question_id IN ({placeholders})
                ORDER BY question_id, display_order, option_id
            """),
            params,
        ).mappings().all()
        reviews = connection.execute(
            text(f"""
                SELECT review_id, question_id, reviewer_id, decision,
                       quality_score, notes, reviewed_at
                FROM question_reviews
                WHERE question_id IN ({placeholders})
                ORDER BY question_id, review_id
            """),
            params,
        ).mappings().all()
        histories = connection.execute(
            text(f"""
                SELECT event_id, question_id, actor_user_id, previous_status,
                       new_status, note, created_at
                FROM question_status_history
                WHERE question_id IN ({placeholders})
                ORDER BY question_id, event_id
            """),
            params,
        ).mappings().all()

    def serialized(rows):
        return [
            {key: (value.isoformat() if hasattr(value, "isoformat") else value)
             for key, value in row.items()}
            for row in rows
        ]

    content = json.dumps({
        "questions": serialized(question_rows),
        "options": serialized(options),
        "reviews": serialized(reviews),
        "history": serialized(histories),
    }, sort_keys=True, default=str, ensure_ascii=False)
    totals["target_id_count"] = len(question_rows)
    totals["target_content_review_history_sha256"] = hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()
    return totals


def _free_loopback_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _wait_for_database(test_url, timeout=90):
    test_engine = create_engine(test_url, pool_pre_ping=True)
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            with test_engine.connect() as connection:
                if connection.exec_driver_sql("SELECT DATABASE()").scalar_one() != TEST_DATABASE:
                    raise RuntimeError("Connected test database has an unexpected name.")
            return test_engine
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    test_engine.dispose()
    raise RuntimeError(f"Isolated MySQL did not become ready: {last_error}")


def _create_schema_only_test_database(test_engine):
    metadata = MetaData()
    metadata.reflect(bind=source_engine)
    table_names = set(inspect(source_engine).get_table_names())
    if not table_names or len(metadata.tables) != len(table_names):
        raise RuntimeError("Could not reflect the complete source schema.")
    metadata.create_all(bind=test_engine, checkfirst=True)
    with test_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO tracks (track_id, track_name) VALUES (1, 'Aptitude')")
        )
        connection.execute(
            text("""
                INSERT INTO topics (topic_id, track_id, topic_name, display_order)
                VALUES (1, 1, 'Quantitative Aptitude', 1)
            """)
        )
        connection.execute(
            text("""
                INSERT INTO subtopics (
                    subtopic_id, topic_id, subtopic_name, display_order
                )
                VALUES (1, 1, 'Synthetic Percentages', 1)
            """)
        )
        connection.execute(
            text("""
                INSERT INTO sources (
                    source_id, source_name, source_type, source_notes
                )
                VALUES (1, 'Synthetic Custom Test Source', 'CUSTOM', 'Test-only source.')
            """)
        )
        connection.execute(
            text("""
                INSERT INTO sources (
                    source_id, source_name, source_type, source_url, source_notes
                )
                VALUES (
                    2, 'Synthetic Scraped Test Source', 'SCRAPED',
                    'https://example.test/source', ''
                )
            """)
        )
        connection.execute(
            text("""
                INSERT INTO sources (source_id, source_name, source_type, source_notes)
                VALUES (
                    3, 'Custom MCQ Bank — 310 Questions Detected',
                    'CUSTOM', 'Synthetic test-suite reference source.'
                )
            """)
        )
        connection.execute(
            text("""
                INSERT INTO tracks (track_id, track_name)
                VALUES (2, 'Technical'), (3, 'Synthetic Other Track')
            """)
        )
        taxonomy = (
            (2, 1, "Verbal Ability", "Synthetic Reading"),
            (3, 1, "Logical Reasoning", "Synthetic Patterns"),
            (4, 2, "Programming Concepts", "Synthetic Fundamentals"),
            (5, 3, "Synthetic Other Topic", "Synthetic Other Subtopic"),
        )
        for topic_id, track_id, topic_name, subtopic_name in taxonomy:
            connection.execute(
                text("""
                    INSERT INTO topics (
                        topic_id, track_id, topic_name, display_order
                    )
                    VALUES (:topic_id, :track_id, :topic_name, 1)
                """),
                {
                    "topic_id": topic_id,
                    "track_id": track_id,
                    "topic_name": topic_name,
                },
            )
            connection.execute(
                text("""
                    INSERT INTO subtopics (
                        subtopic_id, topic_id, subtopic_name, display_order
                    )
                    VALUES (:subtopic_id, :topic_id, :subtopic_name, 1)
                """),
                {
                    "subtopic_id": topic_id,
                    "topic_id": topic_id,
                    "subtopic_name": subtopic_name,
                },
            )
            connection.execute(
                text("""
                    INSERT INTO subtopics (
                        subtopic_id, topic_id, subtopic_name, display_order
                    )
                    VALUES (
                        :subtopic_id, :topic_id, :subtopic_name, 2
                    )
                """),
                {
                    "subtopic_id": topic_id + 10,
                    "topic_id": topic_id,
                    "subtopic_name": f"{subtopic_name} Continued",
                },
            )
        connection.execute(
            text("""
                INSERT INTO subtopics (
                    subtopic_id, topic_id, subtopic_name, display_order
                )
                VALUES (11, 1, 'Synthetic Percentages Continued', 2)
            """)
        )
        connection.execute(
            text("""
                INSERT INTO companies (
                    company_id, company_name, slug, description,
                    official_pattern_verified
                )
                VALUES (1, 'Synthetic TCS Fixture', 'tcs', 'Test metadata only.', FALSE)
            """)
        )
    return len(table_names)


def _run_tests(test_url):
    env = os.environ.copy()
    env["DATABASE_URL"] = test_url
    env["PLACEMENT_RUN_ISOLATED_PIPELINE"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-s", *TESTS],
        cwd=BACKEND_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    print(result.stdout, end="")
    return result.returncode


def main():
    if os.getenv("DATABASE_URL"):
        raise RuntimeError(
            "The runner must start without DATABASE_URL; it sets the isolated URL "
            "only in the child test process."
        )
    _assert_safe_source_database()
    import csv

    with TARGET_CSV.open(encoding="utf-8-sig", newline="") as handle:
        question_ids = [int(row["question_id"]) for row in csv.DictReader(handle)]
    if len(question_ids) != 1681 or len(set(question_ids)) != 1681:
        raise RuntimeError("Production MCQ source file is not 1,681 unique target IDs.")

    before = _production_fingerprint(question_ids)
    container_name = f"placement-mcq-pipeline-test-{os.getpid()}"
    password = secrets.token_urlsafe(32)
    port = _free_loopback_port()
    container_id = None
    test_engine = None
    test_url = (
        f"mysql+pymysql://root:{password}@127.0.0.1:{port}/{TEST_DATABASE}"
    )
    try:
        launched = subprocess.run(
            [
                "docker", "run", "--detach", "--rm",
                "--name", container_name,
                "--publish", f"127.0.0.1:{port}:3306",
                "--env", f"MYSQL_ROOT_PASSWORD={password}",
                "--env", f"MYSQL_DATABASE={TEST_DATABASE}",
                MYSQL_IMAGE,
            ],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        container_id = launched.stdout.strip()
        test_engine = _wait_for_database(test_url)
        schema_table_count = _create_schema_only_test_database(test_engine)
        test_database_name = test_engine.url.database
        test_engine.dispose()
        test_engine = None

        test_return_code = _run_tests(test_url)
        after = _production_fingerprint(question_ids)
        print(json.dumps({
            "isolated_test_database": test_database_name,
            "schema_only_tables_copied": schema_table_count,
            "production_before": before,
            "production_after": after,
            "production_unchanged": before == after,
            "database_writes_to_production": "NONE",
            "pytest_return_code": test_return_code,
        }, sort_keys=True, indent=2))
        if before != after:
            raise RuntimeError("Production fingerprint changed during isolated tests.")
        if test_return_code:
            raise SystemExit(test_return_code)
    finally:
        if test_engine is not None:
            test_engine.dispose()
        if container_id:
            subprocess.run(
                ["docker", "rm", "--force", container_id],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


if __name__ == "__main__":
    main()
