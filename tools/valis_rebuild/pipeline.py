"""확정 소스에서 결과까지 수행하는 재현 빌드 파이프라인."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile

from .d88 import D88Image
from .gameover import apply_gameover
from .kanji import build_rom, load_assignments
from .ips import apply_ips, encode_ips
from .outputs import publish_outputs
from .logo import apply_logo_build, prepare_logo_build
from .serializer import apply_hold_patch, apply_raw_tables
from .source_gate import require_buildable


def source_tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    source_root = root / "source"
    for path in sorted(p for p in source_root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        content = path.read_bytes()
        if path.suffix.lower() in {".md", ".json", ".jsonl", ".csv", ".txt", ".asm"}:
            content = content.replace(b"\r\n", b"\n")
        digest.update(content)
    return digest.hexdigest()


def _baseline(root: Path) -> dict:
    return json.loads((root / "source/release-baseline.json").read_text(encoding="utf-8"))


def _write_build_outputs(output: Path, original: bytes, target: bytes, input_path: Path) -> dict:
    ips_bytes = encode_ips(original, target)
    if apply_ips(original, ips_bytes) != target:
        raise ValueError("IPS를 원본에 적용한 결과가 빌드 출력과 다릅니다")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".valis-build-", dir=output.parent) as directory:
        staging = Path(directory)
        image_path = staging / output.name
        ips_path = image_path.with_suffix(".ips")
        image_path.write_bytes(target)
        ips_path.write_bytes(ips_bytes)
        artifacts = {
            "output": {"path": str(image_path), "sha256": hashlib.sha256(target).hexdigest(), "size": len(target)},
            "ips": {"path": str(ips_path), "sha256": hashlib.sha256(ips_bytes).hexdigest(),
                    "size": len(ips_bytes), "reapplied_matches_output": True},
        }
        publish_outputs((artifacts,), output.parent, {input_path.resolve()})
    return artifacts


def _require_input(
    path: Path,
    expected_hash: str,
    expected_size: int,
    label: str,
    *,
    allow_hash_mismatch: bool = False,
    data: bytes | None = None,
) -> bool:
    if data is None:
        data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if len(data) != expected_size or (actual != expected_hash and not allow_hash_mismatch):
        raise ValueError(
            f"{label}가 검토된 원본과 다릅니다: 크기={len(data)}, sha256={actual}"
        )
    return actual == expected_hash


def _disk_tables(root: Path) -> list[tuple[str, Path]]:
    tables = [(f"event_block_{n}", root / f"source/tables/events/block-{n}-raw-changes.csv") for n in range(1, 7)]
    tables += [
        ("ending_1_24", root / "source/tables/ending/raw-changes.csv"),
        ("error07", root / "source/tables/error07/raw-changes.csv"),
    ]
    return tables


def build_disk(root: Path, input_path: Path, output_dir: Path) -> dict:
    require_buildable(root)
    baseline = _baseline(root)
    original = input_path.read_bytes()
    _require_input(input_path, baseline["input"]["d88_sha256"], baseline["input"]["d88_size"], "D88 input", data=original)
    image = D88Image.parse(original)
    logo_plan = prepare_logo_build(root)
    component_reports = []
    component_reports.extend(apply_gameover(image, root / "source"))
    component_reports.extend(apply_raw_tables(
        image,
        _disk_tables(root),
    ))
    logo_report = apply_logo_build(image, logo_plan)
    if logo_report is not None:
        component_reports.append(logo_report)
    component_reports.append(apply_hold_patch(image, root / "source/tables/gameover/hold-34-35.json"))
    output = output_dir / "valis_disk_a(K).d88"
    if output.resolve() == input_path.resolve():
        raise ValueError("D88 output would overwrite the original input")
    exact_release_match = image.sha256() == baseline["output"]["d88_sha256"]
    D88Image.parse(image.data)
    artifacts = _write_build_outputs(output, original, bytes(image.data), input_path)
    log = {
        "schema": "valis-reproduction-log/v1",
        "kind": "d88",
        "input": {"path": str(input_path), "sha256": hashlib.sha256(original).hexdigest()},
        "source_tree_sha256": source_tree_hash(root),
        "component_reports": component_reports,
        **artifacts,
        "structure": {"sectors": len(image.sectors), "flat_payload": len(image.flatten_payload())},
        "expected_output_sha256": baseline["output"]["d88_sha256"],
        "exact_release_match": exact_release_match,
        "status": "OK",
    }
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
    original = input_path.read_bytes()
    input_matches_baseline = _require_input(
        input_path,
        baseline["input"]["kanji1_sha256"],
        baseline["input"]["kanji1_size"],
        "KANJI1 input",
        allow_hash_mismatch=allow_input_hash_mismatch,
        data=original,
    )
    assignments = load_assignments(
        root / "source/tables/kanji/assignments.csv",
        root / "source/kanji",
    )
    output_bytes, glyph_report = build_rom(original, assignments)
    output = output_dir / "KANJI1(K).ROM"
    if output.resolve() == input_path.resolve():
        raise ValueError("KANJI1 output would overwrite the original input")
    exact_release_match = hashlib.sha256(output_bytes).hexdigest() == baseline["output"]["kanji1_sha256"]
    artifacts = _write_build_outputs(output, original, output_bytes, input_path)
    log = {
        "schema": "valis-reproduction-log/v1",
        "kind": "kanji1",
        "input": {"path": str(input_path), "sha256": hashlib.sha256(original).hexdigest()},
        "input_matches_baseline": input_matches_baseline,
        "source_tree_sha256": source_tree_hash(root),
        "assignments": len(assignments),
        "changed_slots": sum(item["changed"] for item in glyph_report),
        **artifacts,
        "expected_output_sha256": baseline["output"]["kanji1_sha256"],
        "exact_release_match": exact_release_match,
        "status": "OK",
    }
    return log
