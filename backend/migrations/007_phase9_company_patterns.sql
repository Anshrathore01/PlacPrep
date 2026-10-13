-- Phase 9 adds metadata and composition controls to the existing blueprint
-- model. All changes are additive; existing blueprints and rules are retained.

ALTER TABLE test_blueprints
    ADD COLUMN program_name VARCHAR(180) NULL,
    ADD COLUMN pattern_version VARCHAR(80) NULL,
    ADD COLUMN effective_from DATE NULL,
    ADD COLUMN source_name VARCHAR(180) NULL,
    ADD COLUMN source_url VARCHAR(1000) NULL,
    ADD COLUMN verification_status ENUM(
        'OFFICIAL',
        'REPORTED',
        'UNVERIFIED'
    ) NOT NULL DEFAULT 'UNVERIFIED',
    ADD COLUMN verification_notes TEXT NULL;

ALTER TABLE test_blueprint_rules
    ADD COLUMN section_name VARCHAR(120) NULL,
    ADD COLUMN section_order INT NOT NULL DEFAULT 1,
    ADD COLUMN is_required BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN time_allocation_seconds INT NULL,
    ADD COLUMN minimum_difficulty ENUM('EASY', 'MEDIUM', 'HARD') NULL,
    ADD COLUMN maximum_difficulty ENUM('EASY', 'MEDIUM', 'HARD') NULL;
