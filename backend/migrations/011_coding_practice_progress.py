"""Store per-user completion for the shared service coding collection."""

from pathlib import Path
import sys

from sqlalchemy import inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database import engine


def migrate() -> None:
    with engine.begin() as connection:
        if not inspect(connection).has_table("coding_practice_progress"):
            connection.execute(text("""
                CREATE TABLE coding_practice_progress (
                    user_id BIGINT UNSIGNED NOT NULL,
                    problem_id VARCHAR(180) NOT NULL,
                    is_solved BOOLEAN NOT NULL DEFAULT TRUE,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, problem_id),
                    CONSTRAINT fk_coding_practice_progress_user
                        FOREIGN KEY (user_id) REFERENCES users (user_id)
                        ON DELETE CASCADE
                ) ENGINE=InnoDB
            """))


if __name__ == "__main__":
    migrate()
