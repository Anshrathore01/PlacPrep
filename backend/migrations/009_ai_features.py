"""Add Placo conversation persistence tables without altering existing data."""

from pathlib import Path
import sys

from sqlalchemy import inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import engine


def migrate() -> None:
    with engine.begin() as connection:
        existing = set(inspect(connection).get_table_names())
        if "placo_conversations" not in existing:
            connection.execute(text("""
                CREATE TABLE placo_conversations (
                    conversation_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    user_id BIGINT UNSIGNED NOT NULL,
                    question_id BIGINT UNSIGNED NULL,
                    attempt_id BIGINT UNSIGNED NULL,
                    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (conversation_id),
                    KEY idx_placo_conversations_user_updated
                        (user_id, updated_at),
                    KEY idx_placo_conversations_question (question_id),
                    KEY idx_placo_conversations_attempt (attempt_id),
                    CONSTRAINT fk_placo_conversations_user
                        FOREIGN KEY (user_id) REFERENCES users (user_id),
                    CONSTRAINT fk_placo_conversations_question
                        FOREIGN KEY (question_id) REFERENCES questions (question_id),
                    CONSTRAINT fk_placo_conversations_attempt
                        FOREIGN KEY (attempt_id) REFERENCES attempts (attempt_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    COLLATE=utf8mb4_unicode_ci
            """))
        if "placo_messages" not in existing:
            connection.execute(text("""
                CREATE TABLE placo_messages (
                    message_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                    conversation_id BIGINT UNSIGNED NOT NULL,
                    role ENUM('USER', 'ASSISTANT') NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (message_id),
                    KEY idx_placo_messages_conversation
                        (conversation_id, message_id),
                    CONSTRAINT fk_placo_messages_conversation
                        FOREIGN KEY (conversation_id)
                        REFERENCES placo_conversations (conversation_id)
                        ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    COLLATE=utf8mb4_unicode_ci
            """))


if __name__ == "__main__":
    migrate()
