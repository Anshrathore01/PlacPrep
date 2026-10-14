-- Safe, forward-only extension for Google sign-in. Existing users and credentials
-- remain untouched; columns are nullable so password accounts continue to work.
ALTER TABLE users
    ADD COLUMN google_id VARCHAR(255) NULL,
    ADD COLUMN profile_picture VARCHAR(2048) NULL,
    ADD UNIQUE KEY uq_users_google_id (google_id);

CREATE TABLE google_auth_nonces (
    nonce_hash CHAR(64) NOT NULL PRIMARY KEY,
    expires_at DATETIME(6) NOT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    KEY ix_google_auth_nonces_expires_at (expires_at)
) ENGINE=InnoDB;
