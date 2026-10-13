"""Add per-attempt duration_seconds column to attempts table."""

from pathlib import Path
import sys

from sqlalchemy import inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import engine


def migrate() -> None:
    with engine.begin() as connection:
        inspector = inspect(connection)
        columns = [col["name"] for col in inspector.get_columns("attempts")]
        if "duration_seconds" not in columns:
            connection.execute(text("""
                ALTER TABLE attempts
                ADD COLUMN duration_seconds INT NULL AFTER time_spent_seconds
            """))
            print("Successfully added duration_seconds column to attempts table.")
        else:
            print("Column duration_seconds already exists in attempts table.")
        # Freeze legacy active attempts with a null per-attempt duration against
        # the mock's current timer. This is safe to rerun and preserves all rows.
        connection.execute(text("""
            UPDATE attempts a
            JOIN mock_tests mt ON mt.mock_test_id = a.mock_test_id
               SET a.duration_seconds = mt.duration_seconds
             WHERE a.status = 'IN_PROGRESS'
               AND a.duration_seconds IS NULL
        """))


if __name__ == "__main__":
    migrate()
