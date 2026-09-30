"""Strict gates between manual analysis and the build graph.

This module deliberately does not parse project documents or infer source
rows. It validates only hand-authored ledger and acceptance metadata.
"""

from __future__ import annotations

import json
from pathlib import Path

from .errors import BuildError
from .text_sources import lint_text_sources


REQUIRED_FACT_FIELDS = {
    "id", "component", "assertion", "source_documents", "source_location",
    "literal_observation", "address_layer", "status", "review",
}
ALLOWED_FACT_STATUS = {"observed", "derived", "confirmed", "conflict", "blocked"}
REQUIRED_COMPONENT_STATUS = "accepted"


def _load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"cannot read evidence/source manifest: {path}") from exc
    if not isinstance(value, dict):
        raise BuildError(f"manifest must be a JSON object: {path}")
    return value


def lint_ledger(repo_root: str | Path) -> dict:
    root = Path(repo_root)
    path = root / "analysis" / "evidence-ledger.json"
    doc = _load(path)
    if doc.get("schema") != "valis-manual-evidence-ledger/v2":
        raise BuildError("unexpected evidence ledger schema")
    facts = doc.get("facts")
    if not isinstance(facts, list):
        raise BuildError("evidence ledger facts must be a list")
    errors: list[str] = []
    ids: set[str] = set()
    for index, fact in enumerate(facts):
        if not isinstance(fact, dict):
            errors.append(f"fact {index} is not an object")
            continue
        missing = sorted(REQUIRED_FACT_FIELDS - set(fact))
        if missing:
            errors.append(f"fact {index} missing fields: {', '.join(missing)}")
        fact_id = fact.get("id")
        if fact_id in ids:
            errors.append(f"duplicate fact id: {fact_id}")
        if isinstance(fact_id, str):
            ids.add(fact_id)
        if fact.get("status") not in ALLOWED_FACT_STATUS:
            errors.append(f"fact {fact_id} has invalid status")
        review = fact.get("review")
        if not isinstance(review, dict) or review.get("status") not in {"pending", "confirmed", "blocked"}:
            errors.append(f"fact {fact_id} has invalid review status")
        if fact.get("status") == "confirmed" and (not isinstance(review, dict) or review.get("status") != "confirmed"):
            errors.append(f"fact {fact_id} claims confirmed without confirmed review")
    return {
        "path": str(path.relative_to(root)),
        "fact_count": len(facts),
        "fact_ids": sorted(ids),
        "errors": errors,
        "status": "OK" if not errors else "INVALID",
    }


def lint_source_manifest(repo_root: str | Path) -> dict:
    root = Path(repo_root)
    path = root / "source" / "source-manifest.json"
    doc = _load(path)
    if doc.get("schema") != "valis-accepted-source-manifest/v2":
        raise BuildError("unexpected accepted source manifest schema")
    components = doc.get("components")
    if not isinstance(components, list) or not components:
        raise BuildError("accepted source manifest has no components")
    ids: set[str] = set()
    errors: list[str] = []
    for component in components:
        if not isinstance(component, dict) or not component.get("id"):
            errors.append("component without id")
            continue
        component_id = component["id"]
        if component_id in ids:
            errors.append(f"duplicate component id: {component_id}")
        ids.add(component_id)
        if component.get("required") and component.get("status") != REQUIRED_COMPONENT_STATUS:
            errors.append(f"required component is not accepted: {component_id}")
    accepted_files = doc.get("accepted_files")
    if not isinstance(accepted_files, list):
        errors.append("accepted_files must be a list")
    for item in accepted_files or []:
        if not isinstance(item, dict) or not item.get("path") or not item.get("review_ids"):
            errors.append("accepted file lacks path or review_ids")
            continue
        if item.get("generated") is True:
            errors.append(f"generated file cannot be accepted: {item.get('path')}")
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            errors.append(f"accepted file path escapes repository: {item['path']}")
            continue
        if not (root / relative).is_file():
            errors.append(f"accepted file is missing: {item['path']}")
        review_ids = item.get("review_ids")
        if not isinstance(review_ids, list) or not all(isinstance(value, str) and value for value in review_ids):
            errors.append(f"accepted file has invalid review_ids: {item['path']}")
    buildable = doc.get("status") == "accepted" and doc.get("buildable") is True and not errors
    return {
        "path": str(path.relative_to(root)),
        "component_count": len(components),
        "accepted_file_count": len(accepted_files or []),
        "errors": errors,
        "declared_status": doc.get("status"),
        "buildable": buildable,
        "status": "OK" if buildable else "BLOCKED",
    }


def lint_release_baseline(repo_root: str | Path) -> dict:
    root = Path(repo_root)
    path = root / "source" / "release-baseline.json"
    doc = _load(path)
    errors: list[str] = []
    if doc.get("schema") != "valis-release-baseline/v1":
        errors.append("unexpected release baseline schema")
    for section in ("input", "output"):
        value = doc.get(section)
        if not isinstance(value, dict):
            errors.append(f"missing {section} release values")
            continue
        for key in ("d88_sha256", "d88_size", "kanji1_sha256", "kanji1_size"):
            if key not in value:
                errors.append(f"missing {section}.{key}")
    contract = doc.get("component_contract")
    if not isinstance(contract, dict):
        errors.append("missing final component contract")
    required_contract = {"rule", "logo_final_raw_rows", "gameover_scroll_records", "event_final_raw_updates", "error07_final_raw_updates"}
    if isinstance(contract, dict) and not required_contract.issubset(contract):
        errors.append("final component contract is incomplete")
    return {
        "path": str(path.relative_to(root)),
        "logo_final_raw_rows": contract.get("logo_final_raw_rows") if isinstance(contract, dict) else None,
        "errors": errors,
        "status": "OK" if not errors else "INVALID",
    }


def lint_all(repo_root: str | Path) -> dict:
    ledger = lint_ledger(repo_root)
    manifest = lint_source_manifest(repo_root)
    release = lint_release_baseline(repo_root)
    text_sources = lint_text_sources(repo_root)
    return {
        "ledger": ledger,
        "source_manifest": manifest,
        "release_baseline": release,
        "text_sources": text_sources,
        "status": "OK" if ledger["status"] == "OK" and manifest["buildable"] and release["status"] == "OK" and text_sources["status"] == "OK" else "BLOCKED",
    }


def require_buildable(repo_root: str | Path) -> dict:
    report = lint_all(repo_root)
    if report["status"] != "OK":
        raise BuildError(
            "build is blocked: manual evidence review is incomplete; "
            "run source-lint and populate source only from reviewed literal data"
        )
    return report
