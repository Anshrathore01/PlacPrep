from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import engine


BLUEPRINT_COLUMNS = {
    "effective_to": "DATE NULL",
    "source_type": "VARCHAR(40) NULL",
    "source_published_at": "DATE NULL",
    "source_accessed_at": "DATETIME NULL",
    "source_notes": "TEXT NULL",
    "pattern_details": "JSON NULL",
    "activated_at": "DATETIME NULL",
}

RULE_COLUMNS = {
    "track_id": "INTEGER NULL",
    "selection_strategy": (
        "VARCHAR(32) NOT NULL DEFAULT 'QUESTION_ID_ASC'"
    ),
}


def _add_missing_columns(connection, table: str, columns: dict[str, str]) -> None:
    existing = {
        column["name"]
        for column in inspect(connection).get_columns(table)
    }
    for name, definition in columns.items():
        if name not in existing:
            connection.execute(
                text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
            )
            existing.add(name)


def _ensure_unique_index(
    connection,
    table: str,
    index_name: str,
    columns: tuple[str, ...],
) -> None:
    inspector = inspect(connection)
    indexes = inspector.get_indexes(table)
    unique_constraints = inspector.get_unique_constraints(table)
    if any(
        index.get("unique")
        and tuple(index.get("column_names") or ()) == columns
        for index in indexes
    ) or any(
        tuple(constraint.get("column_names") or ()) == columns
        for constraint in unique_constraints
    ):
        return
    not_null_filter = (
        "WHERE company_id IS NOT NULL "
        "AND program_name IS NOT NULL "
        "AND pattern_version IS NOT NULL"
        if table == "test_blueprints"
        else ""
    )
    duplicates = connection.execute(
        text(f"""
            SELECT {", ".join(columns)}, COUNT(*) AS duplicate_count
            FROM {table}
            {not_null_filter}
            GROUP BY {", ".join(columns)}
            HAVING COUNT(*) > 1
            LIMIT 1
        """)
    ).mappings().first()
    if duplicates is not None:
        raise RuntimeError(
            f"Cannot create {index_name}: duplicate {table} values exist "
            f"for {columns}: {dict(duplicates)}"
        )
    connection.execute(
        text(
            f"CREATE UNIQUE INDEX {index_name} ON {table} "
            f"({', '.join(columns)})"
        )
    )


def migrate() -> None:
    with engine.begin() as connection:
        _add_missing_columns(connection, "test_blueprints", BLUEPRINT_COLUMNS)
        _add_missing_columns(connection, "test_blueprint_rules", RULE_COLUMNS)
        rule_foreign_keys = inspect(connection).get_foreign_keys(
            "test_blueprint_rules"
        )
        if not any(
            foreign_key.get("constrained_columns") == ["track_id"]
            and foreign_key.get("referred_table") == "tracks"
            for foreign_key in rule_foreign_keys
        ):
            connection.execute(text("""
                ALTER TABLE test_blueprint_rules
                ADD CONSTRAINT fk_test_blueprint_rules_track
                FOREIGN KEY (track_id) REFERENCES tracks (track_id)
            """))
        connection.execute(text("""
            UPDATE test_blueprints
            SET activated_at = COALESCE(activated_at, updated_at, CURRENT_TIMESTAMP)
            WHERE status = 'ACTIVE'
        """))
        _ensure_unique_index(
            connection,
            "test_blueprints",
            "uq_blueprint_company_program_version",
            ("company_id", "program_name", "pattern_version"),
        )
        _ensure_unique_index(
            connection,
            "test_blueprint_rules",
            "uq_blueprint_section_order",
            ("blueprint_id", "section_order"),
        )


if __name__ == "__main__":
    migrate()
