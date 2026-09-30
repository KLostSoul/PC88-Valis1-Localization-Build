"""Validation for explicitly transcribed original/translation source tables.

This module reads JSONL that is already present in ``source``.  It
does not open DOCX files, extract rows, derive tokens, or infer missing text.
Its only job is to enforce the source-table contract before a build.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

from .errors import BuildError


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"cannot read text source index: {path}") from exc
    if not isinstance(value, dict):
        raise BuildError(f"text source index must be an object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise BuildError(f"cannot read text source: {path}") from exc
    for line_no, line in enumerate(lines, 1):
        if not line.strip():
            raise BuildError(f"blank line in text source: {path}:{line_no}")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BuildError(f"invalid JSONL at {path}:{line_no}") from exc
        if not isinstance(value, dict):
            raise BuildError(f"text record is not an object: {path}:{line_no}")
        records.append(value)
    return records


def lint_text_sources(repo_root: str | Path) -> dict:
    root = Path(repo_root)
    text_root = root / "source" / "text"
    index = _read_json(text_root / "source-index.json")
    errors: list[str] = []
    if index.get("schema") != "valis-literal-text-source-index/v1":
        errors.append("unexpected text source index schema")
    if index.get("automatic_mapping") is not False:
        errors.append("text source index must disable automatic mapping")
    if index.get("automatic_binary_extraction") is not False:
        errors.append("text source index must disable automatic binary extraction")

    records = index.get("records")
    if not isinstance(records, dict) or not records:
        errors.append("text source index has no records")
        return {"path": str((text_root / "source-index.json").relative_to(root)), "errors": errors, "status": "INVALID"}
    required_names = {f"event_block_{n}" for n in range(1, 7)} | {f"event_block_{n}_korean" for n in range(2, 7)} | {"ending_1_24", "gameover_fixed_1_15", "gameover_scroll_1_35"}
    if set(records) != required_names:
        errors.append("text source index must declare all event, ending, and gameover record sets")

    report_records: dict[str, dict] = {}
    for name, spec in records.items():
        if not isinstance(spec, dict) or not isinstance(spec.get("path"), str):
            errors.append(f"{name}: invalid index entry")
            continue
        path = text_root / spec["path"].removeprefix("text/")
        if not path.resolve().is_relative_to(text_root.resolve()):
            errors.append(f"{name}: source path escapes source/text")
            continue
        if not path.is_file():
            errors.append(f"{name}: missing source {spec['path']}")
            continue
        rows = _read_jsonl(path)
        expected = spec.get("rows")
        if len(rows) != expected:
            errors.append(f"{name}: expected {expected} rows, got {len(rows)}")
        if name == "event_block_1":
            groups: dict[int, list[int]] = {}
            for row in rows:
                provenance = row.get("provenance")
                table = provenance.get("table") if isinstance(provenance, dict) else None
                groups.setdefault(table, []).append(row.get("ordinal"))
            if any(numbers != list(range(1, len(numbers) + 1)) for numbers in groups.values()):
                errors.append(f"{name}: table row numbering is not contiguous")
        elif name.startswith("event_block_") and [row.get("ordinal") for row in rows] != list(range(1, len(rows) + 1)):
            errors.append(f"{name}: row numbering is not contiguous")
        for row_no, record in enumerate(rows, 1):
            if not isinstance(record.get("provenance"), dict):
                errors.append(f"{name}:{row_no}: missing provenance")
            for provenance in ("provenance", "token_provenance", "final_patch_provenance"):
                value = record.get(provenance)
                reference = value.get("document") if isinstance(value, dict) else None
                if reference and not (root / reference).is_file():
                    errors.append(f"{name}:{row_no}: missing document {reference}")
            if name in {"event_block_1", "event_block_2", "event_block_3", "event_block_4", "event_block_5", "event_block_6", "ending_1_24", "gameover_fixed_1_15", "gameover_scroll_1_35"}:
                for field in ("original", "translation"):
                    if field not in record:
                        errors.append(f"{name}:{row_no}: missing {field}")
            if name.endswith("_korean"):
                if "translation" not in record or "token_bytes" not in record:
                    errors.append(f"{name}:{row_no}: missing Korean translation/token bytes")
                tokens = record.get("token_bytes")
                if not isinstance(tokens, list) or len(tokens) != record.get("length") or any(
                    not isinstance(token, str) or re.fullmatch(r"[0-9A-Fa-f]{2}", token) is None for token in tokens
                ):
                    errors.append(f"{name}:{row_no}: invalid token bytes/length")
                try:
                    bounds = record["runtime_range"].split("~")
                    start, end = int(bounds[0], 16), int(bounds[-1], 16)
                    if not 0 <= start <= end <= 0xFFFF or end - start + 1 != record["length"]:
                        errors.append(f"{name}:{row_no}: runtime range/length mismatch")
                except (KeyError, TypeError, ValueError):
                    errors.append(f"{name}:{row_no}: invalid runtime range")
            if "token_pairs" in record:
                tokens = record["token_pairs"]
                if not isinstance(tokens, list) or not tokens or any(
                    not isinstance(token, str) or re.fullmatch(r"[0-9A-Fa-f]{4}", token) is None for token in tokens
                ):
                    errors.append(f"{name}:{row_no}: invalid token pairs")
        report_records[name] = {"path": spec["path"], "rows": len(rows)}

    fixed = _read_jsonl(text_root / "gameover-fixed.jsonl") if (text_root / "gameover-fixed.jsonl").is_file() else []
    scroll = _read_jsonl(text_root / "gameover-scroll.jsonl") if (text_root / "gameover-scroll.jsonl").is_file() else []
    if [r.get("number") for r in fixed] != list(range(1, 16)):
        errors.append("gameover-fixed numbering is not exactly 1..15")
    if [r.get("number") for r in scroll] != list(range(1, 36)):
        errors.append("gameover-scroll numbering is not exactly 1..35")
    ending = _read_jsonl(text_root / "ending-24.jsonl") if (text_root / "ending-24.jsonl").is_file() else []
    if [r.get("segment") for r in ending] != list(range(1, 25)):
        errors.append("ending numbering is not exactly 1..24")

    return {
        "path": str((text_root / "source-index.json").relative_to(root)),
        "records": report_records,
        "automatic_mapping": False,
        "automatic_binary_extraction": False,
        "errors": errors,
        "status": "OK" if not errors else "INVALID",
    }
