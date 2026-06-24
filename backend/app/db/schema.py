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
        if "content_preview" in existing_columns:
            statements.append(
                "UPDATE document_chunks "
                "SET content_raw = content_preview "
                "WHERE content_raw IS NULL"
            )
            statements.append(
                "UPDATE document_chunks "
                "SET retrieval_text = content_preview "
                "WHERE retrieval_text IS NULL"
            )

    if inspector.has_table("course_materials"):
        existing_columns = {
            column["name"] for column in inspector.get_columns("course_materials")
        }
        if "outline_json" not in existing_columns:
            statements.append(
                f"ALTER TABLE course_materials ADD COLUMN outline_json {_json_type(engine)}"
            )
        if "outline_status" not in existing_columns:
            statements.append(
                "ALTER TABLE course_materials "
                "ADD COLUMN outline_status VARCHAR(30) DEFAULT 'pending'"
            )
        if "outline_source" not in existing_columns:
            statements.append(
                "ALTER TABLE course_materials ADD COLUMN outline_source VARCHAR(40)"
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
