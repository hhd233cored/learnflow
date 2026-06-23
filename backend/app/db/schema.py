from __future__ import annotations

from sqlalchemy import Engine, inspect, text


def ensure_demo_schema_columns(engine: Engine) -> None:
    """Add demo-era columns that create_all cannot add to existing databases."""

    inspector = inspect(engine)
    statements: list[str] = []

    if inspector.has_table("learning_goals"):
        existing_columns = {
            column["name"] for column in inspector.get_columns("learning_goals")
        }
        if "goal_type" not in existing_columns:
            statements.append(
                "ALTER TABLE learning_goals "
                "ADD COLUMN goal_type VARCHAR(20) DEFAULT 'exam' NOT NULL"
            )
        if "duration_days" not in existing_columns:
            statements.append("ALTER TABLE learning_goals ADD COLUMN duration_days INTEGER")

    if inspector.has_table("document_chunks"):
        existing_columns = {
            column["name"] for column in inspector.get_columns("document_chunks")
        }
        if "content_raw" not in existing_columns:
            statements.append("ALTER TABLE document_chunks ADD COLUMN content_raw TEXT")
        if "retrieval_text" not in existing_columns:
            statements.append("ALTER TABLE document_chunks ADD COLUMN retrieval_text TEXT")
        if "formulas" not in existing_columns:
            statements.append(
                f"ALTER TABLE document_chunks ADD COLUMN formulas {_json_type(engine)}"
            )
        if "key_terms" not in existing_columns:
            statements.append(
                f"ALTER TABLE document_chunks ADD COLUMN key_terms {_json_type(engine)}"
            )

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _json_type(engine: Engine) -> str:
    if engine.dialect.name == "postgresql":
        return "JSONB"
    return "JSON"
