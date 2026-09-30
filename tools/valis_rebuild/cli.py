"""수동 검토 자료를 사용하는 안전한 단계형 재현 빌드 CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .d88 import D88Image
from .errors import BuildError
from .pipeline import build_disk, build_kanji
from .source_gate import lint_all, require_buildable
from .text_sources import lint_text_sources


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reject_reference(path: Path) -> None:
    lowered = str(path).lower()
    if path.suffix.lower() in {".zip", ".ips", ".patch"}:
        raise BuildError(f"비교용 압축파일/패치는 빌드 입력이 아닙니다: {path}")
    forbidden = ("reference_work", "nested_extract", "completed", "final", "quarantine")
    if any(part in lowered for part in forbidden):
        raise BuildError(f"비교용 또는 격리 자료는 빌드 입력이 아닙니다: {path}")


def command_source_lint(args: argparse.Namespace) -> dict:
    return {"command": "source-lint", **lint_all(repo_root())}


def command_text_lint(args: argparse.Namespace) -> dict:
    return {"command": "text-lint", **lint_text_sources(repo_root())}


def command_export_original(args: argparse.Namespace) -> dict:
    source = Path(args.d88).resolve()
    _reject_reference(source)
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
    source = Path(args.d88).resolve()
    _reject_reference(source)
    return {"command": "build-d88", **build_disk(root, source, Path(args.out).resolve())}


def command_build_rom(args: argparse.Namespace) -> dict:
    root = repo_root()
    source = Path(args.rom).resolve()
    _reject_reference(source)
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
    d88_source = Path(args.d88).resolve()
    rom_source = Path(args.rom).resolve()
    _reject_reference(d88_source)
    _reject_reference(rom_source)
    output = Path(args.out).resolve()
    # Separate component directories keep the two component logs independent.
    disk = build_disk(root, d88_source, output / "d88")
    kanji = build_kanji(root, rom_source, output / "kanji")
    if disk["status"] != "OK" or kanji["status"] != "OK":
        raise BuildError("출력 해시가 검토된 릴리스 기준과 일치하지 않습니다")
    result = {
        "command": "build",
        "d88": disk,
        "kanji1": kanji,
        "output": str(output),
        "status": "OK",
    }
    _write_json(output / "build-log.json", result)
    return result


def command_verify(args: argparse.Namespace) -> dict:
    source = Path(args.d88).resolve()
    image = D88Image.read(source)
    result = {"command": "verify", "path": str(source), "sha256": image.sha256(),
              "size": len(image.data), "sector_count": len(image.sectors),
              "flat_payload_size": len(image.flatten_payload()), "status": "OK"}
    if args.rom:
        rom = Path(args.rom).resolve()
        _reject_reference(rom)
        rom_data = rom.read_bytes()
        if len(rom_data) != 0x20000:
            raise BuildError(f"KANJI1은 정확히 0x20000바이트여야 합니다. 현재 크기: {len(rom_data):#x}")
        result["kanji1"] = {
            "path": str(rom),
            "sha256": _sha256(rom),
            "size": len(rom_data),
        }
    if args.report:
        _write_json(Path(args.report).resolve(), result)
    return result


def command_compare(args: argparse.Namespace) -> dict:
    built = Path(args.built).resolve()
    reference = Path(args.reference).resolve()
    if reference.suffix.lower() != ".d88":
        raise BuildError("비교 기준은 로컬 D88 파일이어야 합니다")
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
        description="원본 D88/ROM에 확정 리터럴 바이트를 직접 적용하는 한국어 한글패치 재현 빌드 도구",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    lint = sub.add_parser("source-lint", help="확정 소스·근거·릴리스 계약 검사")
    lint.set_defaults(handler=command_source_lint)
    text_lint = sub.add_parser("text-lint", help="원문·한글 번역·토큰 행 검사")
    text_lint.set_defaults(handler=command_text_lint)
    export = sub.add_parser("export-original", help="원본 D88 구조를 읽기 전용으로 내보내기")
    export.add_argument("--d88", required=True, help="사용자가 제공한 원본 D88 경로")
    export.add_argument("--out", default="build/export-original", help="구조 보고서 출력 디렉터리")
    export.set_defaults(handler=command_export_original)
    build_d88 = sub.add_parser("build-d88", help="원본 D88에 확정 raw 변경을 직접 적용")
    build_d88.add_argument("--d88", required=True, help="사용자가 제공한 원본 D88 경로")
    build_d88.add_argument("--out", default="build/reproduction/d88", help="D88 출력 디렉터리")
    build_d88.set_defaults(handler=command_build_d88)
    build_rom = sub.add_parser("build-rom", help="확정된 476개 글리프로 KANJI1 ROM 생성")
    build_rom.add_argument("--rom", required=True, help="사용자가 제공한 원본 KANJI1 ROM 경로")
    build_rom.add_argument("--out", default="build/reproduction/kanji", help="KANJI1 출력 디렉터리")
    build_rom.add_argument(
        "--allow-input-hash-mismatch",
        action="store_true",
        help="ROM 크기 검증 후 기준 해시가 다른 원본도 허용하고 결과 보고서에 차이를 기록",
    )
    build_rom.set_defaults(handler=command_build_rom)
    build = sub.add_parser("build", help="D88와 KANJI1을 함께 재현 빌드")
    build.add_argument("--d88", required=True, help="사용자가 제공한 원본 D88 경로")
    build.add_argument("--rom", required=True, help="사용자가 제공한 원본 KANJI1 ROM 경로")
    build.add_argument("--out", default="build/reproduction", help="통합 출력 디렉터리")
    build.set_defaults(handler=command_build)
    verify = sub.add_parser("verify", help="출력 D88/ROM 구조·크기·해시 검증")
    verify.add_argument("--d88", required=True, help="검증할 D88 경로")
    verify.add_argument("--rom", help="검증할 KANJI1 ROM 경로")
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
    except (BuildError, OSError, ValueError) as exc:
        parser.error(str(exc))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
