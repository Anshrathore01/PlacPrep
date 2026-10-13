-- Phase 6 result metadata. Existing submission history and statuses are kept.

ALTER TABLE coding_submissions
    ADD COLUMN started_at TIMESTAMP NULL DEFAULT NULL,
    ADD COLUMN completed_at TIMESTAMP NULL DEFAULT NULL,
    ADD COLUMN execution_time_ms INT UNSIGNED DEFAULT NULL,
    ADD COLUMN memory_kb INT UNSIGNED DEFAULT NULL,
    ADD COLUMN safe_error_message VARCHAR(2000) DEFAULT NULL,
    ADD KEY idx_coding_submission_status (status, submission_id),
    ADD KEY idx_coding_submission_attempt_question (attempt_id, question_id, score);
