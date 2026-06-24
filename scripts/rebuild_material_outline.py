from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(BACKEND_DIR)

from app import crud, models  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.document_parser import extract_text  # noqa: E402
from app.services.material_outline import extract_material_outline  # noqa: E402
from app.services.paddle_ocr import cached_ocr_pages  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild material outline_json/outline_status/outline_source without "
            "touching chunks, Chroma, or dense embeddings."
        )
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--material-id", type=int)
    scope.add_argument("--goal-id", type=int)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the extracted outline without writing the database.",
    )
    parser.add_argument(
        "--refine-with-llm",
        action="store_true",
        help="Optionally ask DeepSeek to clean the extracted outline.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        materials = _load_materials(db, material_id=args.material_id, goal_id=args.goal_id)
        if not materials:
            raise SystemExit("No matching materials found.")

        for material in materials:
            result = asyncio.run(
                _extract_one(material, refine_with_llm=args.refine_with_llm)
            )
            print(
                f"Material {material.id} {material.filename}: "
                f"{result.status}/{result.source}, {len(result.items)} outline items"
            )
            for item in result.items[:8]:
                page = item.get("page_start") or "?"
                level = item.get("level") or 1
                print(f"  L{level} p{page}: {item.get('title')}")

            if args.dry_run:
                continue

            crud.update_material_outline(
                db,
                material,
                result.items,
                result.status,
                result.source,
            )
        if not args.dry_run:
            print("Outline rebuild complete. Chroma embeddings were not changed.")
    finally:
        db.close()


def _load_materials(
    db,
    *,
    material_id: int | None,
    goal_id: int | None,
) -> list[models.CourseMaterial]:
    if material_id is not None:
        material = db.get(models.CourseMaterial, material_id)
        return [material] if material is not None else []
    return (
        db.query(models.CourseMaterial)
        .filter(models.CourseMaterial.goal_id == goal_id)
        .order_by(models.CourseMaterial.created_at.asc())
        .all()
    )


async def _extract_one(material: models.CourseMaterial, *, refine_with_llm: bool):
    document_text = ""
    try:
        document_text = extract_text(material.storage_path)
    except Exception as exc:
        print(f"  Warning: built-in text extraction failed: {exc}")

    ocr_pages = []
    if material.file_type.lower() == "pdf":
        try:
            ocr_pages = cached_ocr_pages(material)
        except Exception as exc:
            print(f"  Warning: cached OCR read failed: {exc}")

    return await extract_material_outline(
        material,
        document_text=document_text,
        ocr_pages=ocr_pages,
        refine_with_llm=refine_with_llm,
    )


if __name__ == "__main__":
    main()
