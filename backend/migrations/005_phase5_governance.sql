-- Phase 5 additions. Apply once to the existing database after reviewing it.
-- These changes preserve all question, blueprint, mock-test, and attempt rows.

ALTER TABLE questions
    MODIFY COLUMN status ENUM(
        'DRAFT',
        'REVIEW',
        'PUBLISHED',
        'REJECTED',
        'ARCHIVED'
    ) DEFAULT 'DRAFT';

ALTER TABLE test_blueprints
    ADD COLUMN status ENUM(
        'DRAFT',
        'ACTIVE',
        'INACTIVE',
        'ARCHIVED'
    ) NOT NULL DEFAULT 'DRAFT',
    ADD COLUMN created_by BIGINT UNSIGNED DEFAULT NULL,
    ADD COLUMN updated_by BIGINT UNSIGNED DEFAULT NULL,
    ADD COLUMN updated_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP;

ALTER TABLE test_blueprint_rules
    ADD COLUMN points DECIMAL(8, 2) NOT NULL DEFAULT 1.00;

CREATE TABLE question_status_history (
    event_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    question_id BIGINT UNSIGNED NOT NULL,
    actor_user_id BIGINT UNSIGNED NOT NULL,
    previous_status ENUM(
        'DRAFT',
        'REVIEW',
        'PUBLISHED',
        'REJECTED',
        'ARCHIVED'
    ) NOT NULL,
    new_status ENUM(
        'DRAFT',
        'REVIEW',
        'PUBLISHED',
        'REJECTED',
        'ARCHIVED'
    ) NOT NULL,
    note TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (event_id),
    KEY idx_question_status_history_question (question_id, created_at),
    CONSTRAINT question_status_history_ibfk_1
        FOREIGN KEY (question_id) REFERENCES questions (question_id),
    CONSTRAINT question_status_history_ibfk_2
        FOREIGN KEY (actor_user_id) REFERENCES users (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
