"""확정 소스에서 결과까지 수행하는 재현 빌드 파이프라인."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .d88 import D88Image
from .gameover import apply_gameover
from .kanji import build_rom, load_assignments
from .logo import apply_logo_build, prepare_logo_build
from .serializer import apply_hold_patch, apply_raw_tables
from .source_gate import require_buildable


def source_tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    source_root = root / "source"
    for path in sorted(p for p in source_root.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _baseline(root: Path) -> dict:
    return json.loads((root / "source/release-baseline.json").read_text(encoding="utf-8"))


def _require_input(
    path: Path,
    expected_hash: str,
    expected_size: int,
    label: str,
    *,
    allow_hash_mismatch: bool = False,
) -> bool:
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if path.stat().st_size != expected_size or (actual != expected_hash and not allow_hash_mismatch):
        raise ValueError(
            f"{label}가 검토된 원본과 다릅니다: 크기={path.stat().st_size}, sha256={actual}"
        )
    return actual == expected_hash


def _disk_tables(root: Path) -> list[tuple[str, Path]]:
    tables = [(f"event_block_{n}", root / f"source/tables/events/block-{n}-raw-changes.csv") for n in range(1, 7)]
    tables += [
        ("ending_1_24", root / "source/tables/ending/raw-changes.csv"),
        ("error07", root / "source/tables/error07/raw-changes.csv"),
        ("logo", root / "source/tables/logo/raw-changes.csv"),
    ]
    return tables


def build_disk(root: Path, input_path: Path, output_dir: Path) -> dict:
    require_buildable(root)
    baseline = _baseline(root)
    _require_input(input_path, baseline["input"]["d88_sha256"], baseline["input"]["d88_size"], "D88 input")
    image = D88Image.read(input_path)
    logo_plan = prepare_logo_build(root)
    component_reports = []
    component_reports.extend(apply_gameover(image, root / "source"))
    component_reports.extend(apply_raw_tables(
        image,
        _disk_tables(root),
        skip_ram_ranges={"logo": logo_plan.skipped_ram_ranges},
    ))
    logo_report = apply_logo_build(image, logo_plan)
    if logo_report is not None:
        component_reports.append(logo_report)
    component_reports.append(apply_hold_patch(image, root / "source/tables/gameover/hold-34-35.json"))
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "valis_disk_a(K).d88"
    image.save(output)
    log = {
        "schema": "valis-reproduction-log/v1",
        "kind": "d88",
        "input": {"path": str(input_path), "sha256": hashlib.sha256(input_path.read_bytes()).hexdigest()},
        "source_tree_sha256": source_tree_hash(root),
        "component_reports": component_reports,
        "output": {"path": str(output), "sha256": image.sha256(), "size": len(image.data)},
        "structure": {"sectors": len(image.sectors), "flat_payload": len(image.flatten_payload())},
        "expected_output_sha256": baseline["output"]["d88_sha256"],
        "exact_release_match": image.sha256() == baseline["output"]["d88_sha256"],
        "status": "OK" if image.sha256() == baseline["output"]["d88_sha256"] else "MISMATCH",
    }
    _write_json(output_dir / "repro-log.json", log)
    return log


def build_kanji(
    root: Path,
    input_path: Path,
    output_dir: Path,
    *,
    allow_input_hash_mismatch: bool = False,
) -> dict:
    require_buildable(root)
    baseline = _baseline(root)
    input_matches_baseline = _require_input(
        input_path,
        baseline["input"]["kanji1_sha256"],
        baseline["input"]["kanji1_size"],
        "KANJI1 input",
        allow_hash_mismatch=allow_input_hash_mismatch,
    )
    original = input_path.read_bytes()
    assignments = load_assignments(
        root / "source/tables/kanji/assignments.csv",
        root / "source/kanji",
    )
    output_bytes, glyph_report = build_rom(original, assignments)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "KANJI1(K).ROM"
    output.write_bytes(output_bytes)
    log = {
        "schema": "valis-reproduction-log/v1",
        "kind": "kanji1",
        "input": {"path": str(input_path), "sha256": hashlib.sha256(original).hexdigest()},
        "input_matches_baseline": input_matches_baseline,
        "source_tree_sha256": source_tree_hash(root),
        "assignments": len(assignments),
        "changed_slots": sum(item["changed"] for item in glyph_report),
        "output": {"path": str(output), "sha256": hashlib.sha256(output_bytes).hexdigest(), "size": len(output_bytes)},
        "expected_output_sha256": baseline["output"]["kanji1_sha256"],
        "exact_release_match": hashlib.sha256(output_bytes).hexdigest() == baseline["output"]["kanji1_sha256"],
        "status": "OK" if hashlib.sha256(output_bytes).hexdigest() == baseline["output"]["kanji1_sha256"] else "MISMATCH",
    }
    _write_json(output_dir / "repro-log.json", log)
    _write_json(output_dir / "glyph-report.json", {"schema": "valis-kanji-build-report/v1", "glyphs": glyph_report})
    return log
