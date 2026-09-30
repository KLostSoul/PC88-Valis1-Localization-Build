"""Sector-safe serializers for reviewed literal source tables.

The event and ending tables contain explicit D88 offsets and old/new raw
bytes. Space-separated values in grouped event rows stay index-aligned. This
module verifies those claims against the original image and writes them. It
never derives an offset from a completed image or an IPS file.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from pathlib import Path

from .d88 import D88Image
from .errors import BuildError


@dataclass(frozen=True)
class RawWrite:
    component: str
    row: int
    disk_offset: int
    raw_old: int
    raw_new: int


def _byte(value: str, field: str, row: int) -> int:
    try:
        result = int(value, 16)
    except ValueError as exc:
        raise BuildError(f"invalid {field} at CSV row {row}: {value!r}") from exc
    if not 0 <= result <= 0xFF:
        raise BuildError(f"{field} is not one byte at CSV row {row}: {value!r}")
    return result


def load_raw_writes(
    path: str | Path,
    component: str,
    *,
    skip_ram_ranges: tuple[tuple[int, int], ...] = (),
) -> list[RawWrite]:
    rows: list[RawWrite] = []
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        if {"disk_offsets", "raw_old_bytes", "raw_new_bytes"}.issubset(fields):
            offset_field, old_field, new_field = "disk_offsets", "raw_old_bytes", "raw_new_bytes"
        elif {"disk_offset", "raw_old", "raw_new"}.issubset(fields):
            offset_field, old_field, new_field = "disk_offset", "raw_old", "raw_new"
        elif {"raw_file_offset", "old_raw", "new_raw"}.issubset(fields):
            offset_field, old_field, new_field = "raw_file_offset", "old_raw", "new_raw"
        else:
            raise BuildError(f"{path} is missing explicit raw write columns")
        for row_number, row in enumerate(reader, 2):
            if skip_ram_ranges:
                try:
                    ram_address = int(row["ram_addr"], 16)
                except (KeyError, TypeError, ValueError) as exc:
                    raise BuildError(f"invalid ram_addr at CSV row {row_number}") from exc
                if any(start <= ram_address < end for start, end in skip_ram_ranges):
                    continue
            offsets = row[offset_field].split()
            old_values = row[old_field].split()
            new_values = row[new_field].split()
            if not offsets or len(offsets) != len(old_values) or len(offsets) != len(new_values):
                raise BuildError(f"mismatched raw write arrays at CSV row {row_number}")
            for offset_value, old_value, new_value in zip(offsets, old_values, new_values):
                try:
                    offset = int(offset_value, 16)
                except ValueError as exc:
                    raise BuildError(f"invalid disk_offset at CSV row {row_number}: {offset_value!r}") from exc
                if offset < 0:
                    raise BuildError(f"negative disk offset at CSV row {row_number}")
                rows.append(RawWrite(
                    component=component,
                    row=row_number,
                    disk_offset=offset,
                    raw_old=_byte(old_value, "raw_old", row_number),
                    raw_new=_byte(new_value, "raw_new", row_number),
                ))
    if not rows and not skip_ram_ranges:
        raise BuildError(f"empty literal raw source table: {path}")
    return rows


def apply_raw_tables(
    image: D88Image,
    tables: list[tuple[str, str | Path]],
    *,
    skip_ram_ranges: dict[str, tuple[tuple[int, int], ...]] | None = None,
) -> list[dict]:
    writes: list[RawWrite] = []
    for component, path in tables:
        ranges = (skip_ram_ranges or {}).get(component, ())
        writes.extend(load_raw_writes(path, component, skip_ram_ranges=ranges))
    offsets: dict[int, RawWrite] = {}
    reports: dict[str, dict] = {}
    for write in writes:
        previous = offsets.get(write.disk_offset)
        if previous is not None:
            raise BuildError(
                f"overlapping raw source rows at 0x{write.disk_offset:X}: "
                f"{previous.component}:{previous.row} and {write.component}:{write.row}"
            )
        sector = image.find_data_sector(write.disk_offset)
        if write.disk_offset >= sector.end:
            raise BuildError(f"raw source points beyond sector payload: 0x{write.disk_offset:X}")
        actual = image.data[write.disk_offset]
        if actual != write.raw_old:
            raise BuildError(
                f"raw_old mismatch for {write.component} at 0x{write.disk_offset:X}: "
                f"table={write.raw_old:02X} input={actual:02X}"
            )
        offsets[write.disk_offset] = write
        image.data[write.disk_offset] = write.raw_new
        report = reports.setdefault(write.component, {"component": write.component, "writes": 0, "changed": 0})
        report["writes"] += 1
        report["changed"] += int(write.raw_old != write.raw_new)
    return [reports[key] for key in sorted(reports)]


def apply_hold_patch(image: D88Image, path: str | Path) -> dict:
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    sector = record["d88_sector"]
    expected_sector = image.find_chrn(*(int(sector[key], 16) for key in ("c", "h", "r", "n")))
    offset = int(record["disk_offset"], 16)
    if not expected_sector.data_offset <= offset < expected_sector.end:
        raise BuildError("hold source offset is outside its declared CHRN sector")
    old = _byte(record["raw_old"], "raw_old", 0)
    new = _byte(record["raw_new"], "raw_new", 0)
    actual = image.data[offset]
    if actual != old:
        raise BuildError(f"hold raw_old mismatch at 0x{offset:X}: table={old:02X} input={actual:02X}")
    image.data[offset] = new
    return {"component": record["component"], "writes": 1, "changed": int(old != new)}

