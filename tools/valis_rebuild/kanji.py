"""Build KANJI1 from the explicit 476-row visual TXT source table."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .errors import BuildError

ROM_SIZE = 0x20000
GLYPH_SIZE = 0x20


@dataclass(frozen=True)
class GlyphAssignment:
    index: int
    unicode: str
    slot: int
    token: str
    rom_offset: int
    source: Path
    review: str


def load_assignments(path: str | Path, source_root: str | Path) -> list[GlyphAssignment]:
    source_root = Path(source_root).resolve()
    rows: list[GlyphAssignment] = []
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            try:
                assignment = GlyphAssignment(
                    index=int(raw["index"]),
                    unicode=raw["unicode"],
                    slot=int(raw["slot"]),
                    token=raw["token"].upper(),
                    rom_offset=int(raw["rom_offset"], 16),
                    source=source_root / raw["source"],
                    review=raw["review"],
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise BuildError(f"invalid KANJI assignment row: {raw}") from exc
            if assignment.review != "confirmed":
                raise BuildError(f"KANJI assignment is not confirmed: {assignment.index}")
            if assignment.rom_offset != assignment.slot * GLYPH_SIZE:
                raise BuildError(f"KANJI slot/offset mismatch: {assignment.index}")
            if not 0 <= assignment.slot < ROM_SIZE // GLYPH_SIZE:
                raise BuildError(f"KANJI slot is outside the ROM: {assignment.index}")
            try:
                assignment.source.resolve().relative_to(source_root)
            except ValueError as exc:
                raise BuildError(f"KANJI source path escapes source/kanji: {assignment.index}") from exc
            if len(assignment.token) != 4 or any(c not in "0123456789ABCDEF" for c in assignment.token):
                raise BuildError(f"invalid KANJI token: {assignment.index}")
            token_address = int.from_bytes(bytes.fromhex(assignment.token), "little")
            if token_address & 0x0F or token_address >> 4 != assignment.slot:
                raise BuildError(f"KANJI token/slot mismatch: {assignment.index}")
            rows.append(assignment)
    if len(rows) != 476:
        raise BuildError(f"expected 476 explicit KANJI assignments, got {len(rows)}")
    if [row.index for row in rows] != list(range(1, 477)):
        raise BuildError("KANJI assignment indices must be exactly 1..476")
    if len({row.slot for row in rows}) != len(rows):
        raise BuildError("duplicate KANJI slot")
    if len({row.unicode for row in rows}) != len(rows):
        raise BuildError("duplicate KANJI Unicode assignment")
    return rows


def read_visual_txt(path: Path) -> bytes:
    if not path.is_file():
        raise BuildError(f"missing KANJI visual TXT source: {path}")
    lines = [line.rstrip("\r\n") for line in path.read_text(encoding="utf-8").splitlines()
             if not line.startswith(";") and line.strip()]
    if len(lines) != 16 or any(len(line) != 16 for line in lines):
        raise BuildError(f"KANJI source must contain exactly 16x16 cells: {path}")
    if any(char not in "■□" for line in lines for char in line):
        raise BuildError(f"KANJI source contains a non-bitmap cell: {path}")
    output = bytearray()
    for line in lines:
        bits = int("".join("1" if char == "■" else "0" for char in line), 2)
        output.extend(((bits >> 8) & 0xFF, bits & 0xFF))
    return bytes(output)


def build_rom(original: bytes, assignments: list[GlyphAssignment]) -> tuple[bytes, list[dict]]:
    if len(original) != ROM_SIZE:
        raise BuildError(f"KANJI1 must be exactly 0x20000 bytes, got {len(original):#x}")
    output = bytearray(original)
    report = []
    for assignment in assignments:
        if not 0 <= assignment.rom_offset <= ROM_SIZE - GLYPH_SIZE:
            raise BuildError(f"KANJI write is outside the ROM: {assignment.index}")
        glyph = read_visual_txt(assignment.source)
        before = bytes(output[assignment.rom_offset:assignment.rom_offset + GLYPH_SIZE])
        output[assignment.rom_offset:assignment.rom_offset + GLYPH_SIZE] = glyph
        report.append({
            "index": assignment.index,
            "unicode": assignment.unicode,
            "slot": assignment.slot,
            "token": assignment.token,
            "rom_offset": f"0x{assignment.rom_offset:05X}",
            "changed": before != glyph,
            "source": str(assignment.source),
        })
    return bytes(output), report
