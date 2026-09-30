"""Gameover fixed/scroll source serializer.

The source JSONL is a literal transcription of the completion archive's
original/translation/token-pair tables.  The four SUB-to-D88 block bases and
the 0x3A correction are explicit facts from the analysis document; there is
no global address search or token inference here.
"""

from __future__ import annotations

import json
from pathlib import Path

from .codec import encode_byte, decode_byte
from .d88 import D88Image
from .errors import BuildError


SUB_TO_D88_BASE = {
    0x4400: 0x7A10,
    0x4800: 0x7E20,
    0x4C00: 0x8230,
    0x5000: 0x8640,
}
CORRECTION = 0x3A


def _range(text: str) -> tuple[int, int]:
    try:
        left, right = text.split("~", 1)
        start, end = int(left, 16), int(right, 16)
        if not 0 <= start <= end:
            raise ValueError("invalid range bounds")
        return start, end
    except ValueError as exc:
        raise BuildError(f"invalid gameover range: {text!r}") from exc


def _ranges(text: str) -> list[tuple[int, int]]:
    return [_range(part.strip()) for part in text.split(",")]


def _records(path: Path) -> list[dict]:
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            if not isinstance(record, dict):
                raise BuildError(f"gameover record must be an object: {path}:{line_number}")
            records.append(record)
        except json.JSONDecodeError as exc:
            raise BuildError(f"invalid gameover JSONL at {path}:{line_number}") from exc
    if not records:
        raise BuildError(f"empty gameover source: {path}")
    return records


def _expected_raw_offsets(sub_start: int, length: int) -> list[int]:
    offsets = []
    for i in range(length):
        address = sub_start + i
        block = address & ~0x3FF
        if block not in SUB_TO_D88_BASE:
            raise BuildError(f"no explicit gameover D88 base for SUB 0x{block:04X}")
        offsets.append(SUB_TO_D88_BASE[block] + 0x3FF - (address - block))
    return offsets


def _declared_raw_offsets(text: str) -> set[int]:
    result: set[int] = set()
    for start, end in _ranges(text):
        if end < start:
            raise BuildError(f"descending gameover D88 range is not accepted: {text}")
        result.update(range(start, end + 1))
    return result


def _record_plan(record: dict, component: str) -> tuple[bytes, int, list[int], int | None]:
    pairs = record["token_pairs"]
    if not isinstance(pairs, list) or not pairs or any(
        not isinstance(pair, str) or len(pair) != 4 or
        any(char not in "0123456789abcdefABCDEF" for char in pair) for pair in pairs
    ):
        raise BuildError(f"invalid gameover token pairs: {component} {record.get('number')}")
    decoded = bytes.fromhex("".join(pairs))
    sub_range_start, sub_range_end = _range(record["sub_range"])
    main_start, main_end = _range(record["main_range"])
    if (main_start + 0x3F00, main_end + 0x3F00) != (sub_range_start, sub_range_end):
        raise BuildError(f"{component} MAIN/SUB range mismatch")
    if "body_range" in record:
        main_body_start, main_body_end = _range(record["body_range"])
        sub_start, sub_end = main_body_start + 0x3F00, main_body_end + 0x3F00
        if record.get("marker") not in {"", "0F"}:
            raise BuildError(f"{component} has an unsupported marker")
        if sub_end != sub_range_end or sub_start != sub_range_start + int(record.get("marker") == "0F"):
            raise BuildError(f"{component} body/marker range mismatch")
    else:
        sub_start, sub_end = sub_range_start, sub_range_end
        if int(record["terminator"], 16) + 0x3F00 != sub_end + 1:
            raise BuildError(f"{component} terminator is not after its body")
    if len(decoded) != sub_end - sub_start + 1:
        raise BuildError(f"{component} {record.get('number')} token length/sub range mismatch")
    expected_offsets = _expected_raw_offsets(sub_start, len(decoded))
    marker_offset = _expected_raw_offsets(sub_range_start, 1)[0] if record.get("marker") == "0F" else None
    all_expected_offsets = set(expected_offsets)
    if marker_offset is not None:
        all_expected_offsets.add(marker_offset)
    if all_expected_offsets != _declared_raw_offsets(record["d88_range"]):
        raise BuildError(f"{component} {record.get('number')} D88 span does not match explicit SUB map")
    return decoded, sub_start, expected_offsets, marker_offset


def lint_gameover_sources(source_root: str | Path) -> dict[str, list[int]]:
    root = Path(source_root)
    result = {}
    for name, count in (("fixed", 15), ("scroll", 35)):
        records = _records(root / f"text/gameover-{name}.jsonl")
        if [r["number"] for r in records] != list(range(1, count + 1)):
            raise BuildError(f"gameover {name} numbering is invalid")
        offsets = []
        for record in records:
            _, _, declared, marker = _record_plan(record, f"gameover_{name}")
            offsets.extend(declared)
            if marker is not None:
                offsets.append(marker)
        result[name] = offsets
    return result


def _apply_records(image: D88Image, records: list[dict], component: str) -> dict:
    writes = 0
    changed = 0
    marker_relocations = 0
    for record in records:
        decoded, sub_start, expected_offsets, marker_offset = _record_plan(record, component)
        for index, value in enumerate(decoded):
            offset = expected_offsets[index]
            image.find_data_sector(offset)
            address = sub_start + index
            local = address - (address & ~0x3FF)
            raw_new = encode_byte(value, local, CORRECTION)
            actual = image.data[offset]
            image.write_data(offset, bytes([raw_new]))
            writes += 1
            changed += int(actual != raw_new)
        if marker_offset is not None:
            marker_address = sub_start - 1
            marker_raw = encode_byte(0x0F, marker_address & 0x3FF, CORRECTION)
            marker_old = image.data[marker_offset]
            image.write_data(marker_offset, bytes([marker_raw]))
            writes += 1
            changed += int(marker_old != marker_raw)
            marker_relocations += int(marker_old != marker_raw)
        if "terminator" in record:
            address = int(record["terminator"], 16) + 0x3F00
            offset = _expected_raw_offsets(address, 1)[0]
            if decode_byte(image.data[offset], address & 0x3FF, CORRECTION) != 0x0F:
                raise BuildError(f"{component} fixed terminator is not 0F")
    return {"component": component, "records": len(records), "writes": writes,
            "changed": changed, "marker_relocations": marker_relocations}


def apply_gameover(image: D88Image, source_root: str | Path) -> list[dict]:
    root = Path(source_root)
    fixed = _records(root / "text" / "gameover-fixed.jsonl")
    scroll = _records(root / "text" / "gameover-scroll.jsonl")
    if [r["number"] for r in fixed] != list(range(1, 16)):
        raise BuildError("gameover fixed source must contain segments 1..15")
    if [r["number"] for r in scroll] != list(range(1, 36)):
        raise BuildError("gameover scroll source must contain blocks 1..35")
    return [
        _apply_records(image, fixed, "gameover_fixed_1_15"),
        _apply_records(image, scroll, "gameover_scroll_1_35"),
    ]
