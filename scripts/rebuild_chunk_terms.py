from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import chromadb


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

from app import models  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.document_enrichment import (  # noqa: E402
    _extract_terms,
    clean_text_for_retrieval,
    detect_language,
    extract_formulas,
)
from app.services.knowledge_base import collection_name_for_goal  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Recompute lightweight RAG fields for one material without rebuilding "
            "dense Chroma embeddings."
        )
    )
    parser.add_argument("--material-id", type=int, required=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned updates without writing DB or Chroma metadata.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        material = db.get(models.CourseMaterial, args.material_id)
        if material is None:
            raise SystemExit(f"Material {args.material_id} not found.")

        chunks = (
            db.query(models.DocumentChunk)
            .filter(models.DocumentChunk.material_id == material.id)
            .order_by(models.DocumentChunk.chunk_index.asc())
            .all()
        )
        if not chunks:
            raise SystemExit(f"Material {material.id} has no persisted chunks.")

        updates: list[tuple[models.DocumentChunk, dict[str, Any]]] = []
        for chunk in chunks:
            raw = chunk.content_raw or chunk.content_preview or ""
            retrieval_text = clean_text_for_retrieval(raw)
            formulas = extract_formulas(raw)
            key_terms = _extract_terms(retrieval_text)
            updates.append(
                (
                    chunk,
                    {
                        "content_raw": raw,
                        "retrieval_text": retrieval_text,
                        "formulas": formulas,
                        "key_terms": key_terms,
                        "source_lang": detect_language(retrieval_text),
                    },
                )
            )

        print(
            "Terms-only rebuild updates retrieval_text/formulas/key_terms and "
            "Chroma metadata only. Dense embeddings stay unchanged."
        )
        print(f"Material: {material.id} {material.filename}")
        print(f"Chunks:   {len(updates)}")

        if args.dry_run:
            for chunk, data in updates[:5]:
                print(
                    f"chunk-{chunk.chunk_index}: "
                    f"{len(data['key_terms'])} terms, {len(data['formulas'])} formulas"
                )
            return

        for chunk, data in updates:
            chunk.content_raw = data["content_raw"]
            chunk.retrieval_text = data["retrieval_text"]
            chunk.formulas = data["formulas"]
            chunk.key_terms = data["key_terms"]
        db.commit()

        updated_metadata = update_chroma_metadata(material, updates)
        print(f"DB chunks updated:      {len(updates)}")
        print(f"Chroma metadata updated: {updated_metadata}")
    finally:
        db.close()


def update_chroma_metadata(
    material: models.CourseMaterial,
    updates: list[tuple[models.DocumentChunk, dict[str, Any]]],
) -> int:
    settings = get_settings()
    client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    try:
        collection = client.get_collection(collection_name_for_goal(material.goal_id))
    except Exception as exc:
        print(f"Warning: Chroma collection not found or unavailable: {exc}")
        return 0

    updated = 0
    for chunk, data in updates:
        document_id = chunk.chroma_document_id
        if not document_id:
            continue
        try:
            existing = collection.get(ids=[document_id], include=["metadatas"])
            metadatas = existing.get("metadatas") or []
            metadata = dict(metadatas[0] or {}) if metadatas else {}
            metadata.update(
                {
                    "source_lang": data["source_lang"],
                    "key_terms_json": json.dumps(
                        data["key_terms"], ensure_ascii=False, default=str
                    ),
                    "formulas_json": json.dumps(
                        data["formulas"], ensure_ascii=False, default=str
                    ),
                }
            )
            collection.update(ids=[document_id], metadatas=[metadata])
            updated += 1
        except Exception as exc:
            print(f"Warning: failed to update {document_id}: {exc}")
    return updated


if __name__ == "__main__":
    main()
