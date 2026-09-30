"""수동 검토 자료를 사용하는 안전한 단계형 재현 빌드 CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import shutil

from .d88 import D88Image
from .errors import BuildError
from .pipeline import build_disk, build_kanji
from .source_gate import lint_all
from .text_sources import lint_text_sources


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _publish_outputs(reports: tuple[dict, ...], output: Path, inputs: set[Path]) -> None:
    destinations: list[tuple[dict, Path, Path, Path | None]] = []
    for report in reports:
        staged = Path(report["output"]["path"])
        destination = output / staged.name
        if destination.resolve() in inputs:
            raise BuildError(f"출력이 원본 입력을 덮어씁니다: {destination}")
        if destination.exists() and not destination.is_file():
            raise BuildError(f"출력 경로가 파일이 아닙니다: {destination}")
        previous = staged.with_name(staged.name + ".previous") if destination.exists() else None
        if previous is not None:
            shutil.copy2(destination, previous)
        destinations.append((report, staged, destination, previous))
    published: list[tuple[Path, Path | None]] = []
    try:
        for report, staged, destination, previous in destinations:
            staged.replace(destination)
            published.append((destination, previous))
            report["output"]["path"] = str(destination)
    except OSError:
        for destination, previous in reversed(published):
            if previous is None:
                destination.unlink()
            else:
                previous.replace(destination)
        raise


def _resolve_hashed_input(path: Path, *, expected_hash: str, expected_size: int,
                          label: str, suffix: str, allow_hash_mismatch: bool = False) -> Path:
    """Accept a file path or locate one matching input in a directory by content hash."""
    path = path.resolve()
    if path.is_file():
        if path.stat().st_size != expected_size or (not allow_hash_mismatch and _sha256(path) != expected_hash):
            raise BuildError(f"{label}가 기준 크기·SHA-256과 다릅니다: {path}")
        return path
    if not path.is_dir():
        raise BuildError(f"{label} 입력 파일이나 폴더를 찾을 수 없습니다: {path}")

    candidates = sorted(
        item for item in path.iterdir()
        if item.is_file()
    )
    matches = []
    for candidate in candidates:
        try:
            if candidate.stat().st_size == expected_size and _sha256(candidate) == expected_hash:
                matches.append(candidate.resolve())
        except OSError as exc:
            raise BuildError(f"{label} 후보를 읽을 수 없습니다: {candidate}") from exc
    if not matches:
        raise BuildError(
            f"{path}에서 기준 {label}을 찾지 못했습니다 "
            f"(크기={expected_size}, sha256={expected_hash})"
        )
    return matches[0]


def _resolve_unique_file(path: Path, *, label: str, suffix: str) -> Path:
    """Accept a file or the only matching extension in a directory."""
    path = path.resolve()
    if path.is_file():
        return path
    if not path.is_dir():
        raise BuildError(f"{label} 파일이나 폴더를 찾을 수 없습니다: {path}")
    candidates = sorted(
        item.resolve() for item in path.iterdir()
        if item.is_file() and item.suffix.lower() == suffix.lower()
    )
    if len(candidates) != 1:
        raise BuildError(f"{path}에서 {label} 파일을 하나로 특정할 수 없습니다: {len(candidates)}개")
    return candidates[0]


def command_source_lint(args: argparse.Namespace) -> dict:
    result = {"command": "source-lint", **lint_all(repo_root())}
    if result["status"] != "OK":
        raise BuildError(json.dumps(result, ensure_ascii=False))
    return result


def command_text_lint(args: argparse.Namespace) -> dict:
    result = {"command": "text-lint", **lint_text_sources(repo_root())}
    if result["status"] != "OK":
        raise BuildError(json.dumps(result, ensure_ascii=False))
    return result


def command_export_original(args: argparse.Namespace) -> dict:
    baseline = json.loads((repo_root() / "source/release-baseline.json").read_text(encoding="utf-8"))
    source = _resolve_hashed_input(
        Path(args.d88), expected_hash=baseline["input"]["d88_sha256"],
        expected_size=baseline["input"]["d88_size"], label="D88", suffix=".d88",
    )
    image = D88Image.read(source)
    output = Path(args.out).resolve()
    image.export(output)
    result = {
        "command": "export-original",
        "source_sha256": image.sha256(),
        "source_size": len(image.data),
        "sector_count": len(image.sectors),
        "flat_payload_size": len(image.flatten_payload()),
        "output": str(output),
        "source_rows_created": 0,
        "status": "OK",
    }
    _write_json(output / "export-report.json", result)
    return result


def command_build_d88(args: argparse.Namespace) -> dict:
    root = repo_root()
    baseline = json.loads((root / "source/release-baseline.json").read_text(encoding="utf-8"))
    source = _resolve_hashed_input(
        Path(args.d88), expected_hash=baseline["input"]["d88_sha256"],
        expected_size=baseline["input"]["d88_size"], label="D88", suffix=".d88",
    )
    return {"command": "build-d88", **build_disk(root, source, Path(args.out).resolve())}


def command_build_rom(args: argparse.Namespace) -> dict:
    root = repo_root()
    baseline = json.loads((root / "source/release-baseline.json").read_text(encoding="utf-8"))
    source = _resolve_hashed_input(
        Path(args.rom), expected_hash=baseline["input"]["kanji1_sha256"],
        expected_size=baseline["input"]["kanji1_size"], label="KANJI1 ROM", suffix=".rom",
        allow_hash_mismatch=args.allow_input_hash_mismatch,
    )
    return {
        "command": "build-rom",
        **build_kanji(
            root,
            source,
            Path(args.out).resolve(),
            allow_input_hash_mismatch=args.allow_input_hash_mismatch,
        ),
    }


def command_build(args: argparse.Namespace) -> dict:
    root = repo_root()
    baseline = json.loads((root / "source/release-baseline.json").read_text(encoding="utf-8"))
    d88_source = _resolve_hashed_input(
        Path(args.d88), expected_hash=baseline["input"]["d88_sha256"],
        expected_size=baseline["input"]["d88_size"], label="D88", suffix=".d88",
    )
    rom_source = _resolve_hashed_input(
        Path(args.rom), expected_hash=baseline["input"]["kanji1_sha256"],
        expected_size=baseline["input"]["kanji1_size"], label="KANJI1 ROM", suffix=".rom",
    )
    output = Path(args.out).resolve()
    # Complete both builds before publishing either output.
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".valis-build-", dir=output.parent) as directory:
        staging = Path(directory)
        disk = build_disk(root, d88_source, staging)
        kanji = build_kanji(root, rom_source, staging)
        output.mkdir(parents=True, exist_ok=True)
        _publish_outputs((disk, kanji), output, {d88_source, rom_source})
    result = {
        "command": "build",
        "d88": disk,
        "kanji1": kanji,
        "output": str(output),
        "status": "OK",
    }
    return result


def command_verify(args: argparse.Namespace) -> dict:
    root = repo_root()
    baseline = json.loads((root / "source/release-baseline.json").read_text(encoding="utf-8"))
    source = _resolve_unique_file(Path(args.d88), label="D88 output", suffix=".d88")
    image = D88Image.read(source)
    result = {"command": "verify", "path": str(source), "sha256": image.sha256(),
              "size": len(image.data), "sector_count": len(image.sectors),
              "flat_payload_size": len(image.flatten_payload()), "status": "OK"}
    original_d88 = _resolve_hashed_input(
        Path(args.original_d88), expected_hash=baseline["input"]["d88_sha256"],
        expected_size=baseline["input"]["d88_size"], label="original D88", suffix=".d88",
    )
    with tempfile.TemporaryDirectory(prefix="valis-verify-") as directory:
        expected = build_disk(root, original_d88, Path(directory))
        if result["sha256"] != expected["output"]["sha256"]:
            raise BuildError("D88 출력이 현재 소스의 빌드 결과와 다릅니다")
    result["matches_current_source"] = True
    if args.rom:
        rom = _resolve_unique_file(Path(args.rom), label="KANJI1 output", suffix=".rom")
        rom_data = rom.read_bytes()
        if len(rom_data) != 0x20000:
            raise BuildError(f"KANJI1은 정확히 0x20000바이트여야 합니다. 현재 크기: {len(rom_data):#x}")
        result["kanji1"] = {
            "path": str(rom),
            "sha256": _sha256(rom),
            "size": len(rom_data),
        }
        original_rom = _resolve_hashed_input(
            Path(args.original_rom), expected_hash=baseline["input"]["kanji1_sha256"],
            expected_size=baseline["input"]["kanji1_size"], label="original KANJI1", suffix=".rom",
        )
        with tempfile.TemporaryDirectory(prefix="valis-verify-") as directory:
            expected = build_kanji(root, original_rom, Path(directory))
            if result["kanji1"]["sha256"] != expected["output"]["sha256"]:
                raise BuildError("KANJI1 출력이 현재 소스의 빌드 결과와 다릅니다")
        result["kanji1"]["matches_current_source"] = True
    if args.report:
        _write_json(Path(args.report).resolve(), result)
    return result


def command_compare(args: argparse.Namespace) -> dict:
    baseline = json.loads((repo_root() / "source/release-baseline.json").read_text(encoding="utf-8"))
    built = _resolve_unique_file(Path(args.built), label="built D88", suffix=".d88")
    reference = _resolve_hashed_input(
        Path(args.reference), expected_hash=baseline["output"]["d88_sha256"],
        expected_size=baseline["output"]["d88_size"], label="reference D88", suffix=".d88",
    )
    built_image = D88Image.read(built)
    reference_image = D88Image.read(reference)
    if len(built_image.data) != len(reference_image.data):
        raise BuildError("빌드 결과와 비교용 D88의 크기가 다릅니다")
    changed = sum(a != b for a, b in zip(built_image.data, reference_image.data))
    result = {"command": "compare", "reference_role": "comparison_only",
              "built_sha256": built_image.sha256(), "reference_sha256": reference_image.sha256(),
              "different_file_bytes": changed, "status": "OK"}
    if args.fail_on_diff and changed:
        raise BuildError(f"비교에 실패했습니다. 다른 바이트 수: {changed}")
    if args.report:
        _write_json(Path(args.report).resolve(), result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="valis-rebuild",
        description="검토된 원천과 로고 PNG를 원본 D88/ROM에 반영하는 한국어 한글패치 재현 빌드 도구",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    lint = sub.add_parser("source-lint", help="확정 소스·근거·릴리스·로고 PNG 설정 검사")
    lint.set_defaults(handler=command_source_lint)
    text_lint = sub.add_parser("text-lint", help="원문·한글 번역·토큰 행 검사")
    text_lint.set_defaults(handler=command_text_lint)
    export = sub.add_parser("export-original", help="원본 D88 구조를 읽기 전용으로 내보내기")
    export.add_argument("--d88", required=True, help="원본 D88 파일 또는 SHA-256으로 찾을 후보 폴더")
    export.add_argument("--out", default="build/export-original", help="구조 보고서 출력 디렉터리")
    export.set_defaults(handler=command_export_original)
    build_d88 = sub.add_parser("build-d88", help="원본 D88에 확정 raw 변경과 GFX 로고 PNG 반영")
    build_d88.add_argument("--d88", required=True, help="원본 D88 파일 또는 SHA-256으로 찾을 후보 폴더")
    build_d88.add_argument("--out", default="output", help="출력 디렉터리")
    build_d88.set_defaults(handler=command_build_d88)
    build_rom = sub.add_parser("build-rom", help="확정된 476개 글리프로 KANJI1 ROM 생성")
    build_rom.add_argument("--rom", required=True, help="원본 KANJI1 ROM 파일 또는 SHA-256으로 찾을 후보 폴더")
    build_rom.add_argument("--out", default="output", help="출력 디렉터리")
    build_rom.add_argument(
        "--allow-input-hash-mismatch",
        action="store_true",
        help="직접 ROM 파일을 지정했을 때 기준 해시가 다른 입력도 허용하고 결과 보고서에 차이를 기록",
    )
    build_rom.set_defaults(handler=command_build_rom)
    build = sub.add_parser("build", help="D88 로고 PNG와 KANJI1을 함께 재현 빌드")
    build.add_argument("--d88", required=True, help="원본 D88 파일 또는 SHA-256으로 찾을 후보 폴더")
    build.add_argument("--rom", required=True, help="원본 KANJI1 ROM 파일 또는 SHA-256으로 찾을 후보 폴더")
    build.add_argument("--out", default="output", help="출력 디렉터리")
    build.set_defaults(handler=command_build)
    verify = sub.add_parser("verify", help="출력 D88/ROM 구조·크기·해시 검증")
    verify.add_argument("--d88", required=True, help="검증할 D88 경로")
    verify.add_argument("--rom", help="검증할 KANJI1 ROM 경로")
    verify.add_argument("--original-d88", default="import", help="검증에 사용할 원본 D88 입력")
    verify.add_argument("--original-rom", default="import", help="검증에 사용할 원본 KANJI1 입력")
    verify.add_argument("--report", help="검증 보고서 JSON 경로")
    verify.set_defaults(handler=command_verify)
    compare = sub.add_parser("compare", help="로컬 비교용 완료본과 바이트 차이 확인")
    compare.add_argument("--built", required=True, help="빌드한 D88 경로")
    compare.add_argument("--reference", required=True, help="로컬에만 존재하는 비교용 D88 경로")
    compare.add_argument("--report", help="비교 보고서 JSON 경로")
    compare.add_argument("--fail-on-diff", action="store_true", help="차이가 있으면 실패 코드 반환")
    compare.set_defaults(handler=command_compare)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.handler(args)
    except (BuildError, OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
