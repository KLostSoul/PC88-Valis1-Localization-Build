"""Read the editable logo PNGs and encode their PC-88 source streams."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct
import zlib

from .d88 import D88Image
from .errors import BuildError


@dataclass(frozen=True)
class LogoInput:
    target: str
    plane: str
    path: Path
    edit_png: str
    baseline_pixels_sha256: str


@dataclass(frozen=True)
class LogoGroup:
    name: str
    base: int
    length: int
    encoder: str
    width_pixels: int
    height: int
    images: tuple[LogoInput, ...]

    @property
    def width_bytes(self) -> int:
        return self.width_pixels // 8


@dataclass(frozen=True)
class EncodedLogo:
    name: str
    base: int
    data: bytes
    encoder: str
    inputs: tuple[str, ...]
    source_handling: str


@dataclass(frozen=True)
class LogoBuildPlan:
    skipped_ram_ranges: tuple[tuple[int, int], ...]
    encoded: tuple[EncodedLogo, ...]
    ram_map: dict[int, dict[str, str]]


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError as exc:
        raise BuildError(f"cannot read logo source table: {path}") from exc


def load_binary_png_rows(path: Path, expected_w: int, expected_h: int, width_bytes: int) -> list[list[int]]:
    """Decode a binary black/white PNG without third-party packages."""
    if expected_w <= 0 or expected_h <= 0 or width_bytes * 8 != expected_w:
        raise BuildError("invalid packed PNG dimensions")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise BuildError(f"cannot read logo PNG: {path}") from exc
    signature = b"\x89PNG\r\n\x1a\n"
    if not data.startswith(signature):
        raise BuildError(f"{path}: not a PNG file")

    pos = len(signature)
    ihdr = None
    palette = None
    transparency = None
    idat = bytearray()
    saw_iend = False
    while pos < len(data):
        if pos + 12 > len(data):
            raise BuildError(f"{path}: truncated PNG chunk")
        length = struct.unpack_from(">I", data, pos)[0]
        chunk_type = data[pos + 4:pos + 8]
        end = pos + 8 + length
        if end + 4 > len(data):
            raise BuildError(f"{path}: truncated PNG {chunk_type!r} chunk")
        chunk = data[pos + 8:end]
        expected_crc = struct.unpack_from(">I", data, end)[0]
        if zlib.crc32(chunk_type + chunk) & 0xFFFFFFFF != expected_crc:
            raise BuildError(f"{path}: invalid PNG CRC in {chunk_type!r} chunk")
        pos = end + 4
        if ihdr is None and chunk_type != b"IHDR":
            raise BuildError(f"{path}: IHDR must be the first PNG chunk")
        if chunk_type == b"IHDR":
            if ihdr is not None or length != 13:
                raise BuildError(f"{path}: invalid IHDR")
            ihdr = chunk
        elif chunk_type == b"PLTE":
            if palette is not None or length == 0 or length % 3 or length > 768:
                raise BuildError(f"{path}: invalid PNG palette")
            palette = [tuple(chunk[i:i + 3]) for i in range(0, length, 3)]
        elif chunk_type == b"tRNS":
            transparency = chunk
        elif chunk_type == b"IDAT":
            idat.extend(chunk)
        elif chunk_type == b"IEND":
            if length != 0 or pos != len(data):
                raise BuildError(f"{path}: invalid IEND or trailing PNG data")
            saw_iend = True
            break
        elif chunk_type[0] & 0x20 == 0:
            raise BuildError(f"{path}: unsupported critical PNG chunk {chunk_type!r}")

    if ihdr is None or not idat or not saw_iend:
        raise BuildError(f"{path}: missing IHDR, image data, or IEND")
    w, h, bit_depth, color_type, comp, filt, interlace = struct.unpack(">IIBBBBB", ihdr)
    if (w, h) != (expected_w, expected_h):
        raise BuildError(f"{path}: expected {expected_w}x{expected_h}, got {w}x{h}")
    if comp != 0 or filt != 0 or interlace != 0:
        raise BuildError(f"{path}: PNG must use standard, non-interlaced encoding")
    samples = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if samples is None:
        raise BuildError(f"{path}: unsupported PNG color type {color_type}")
    if color_type in (2, 4, 6) and bit_depth != 8:
        raise BuildError(f"{path}: truecolor/alpha PNG must be 8-bit per channel")
    if color_type in (0, 3) and bit_depth not in (1, 2, 4, 8):
        raise BuildError(f"{path}: grayscale/indexed PNG bit depth must be 1, 2, 4, or 8")
    if color_type == 3 and palette is None:
        raise BuildError(f"{path}: indexed PNG is missing PLTE")
    if color_type in (0, 2) and transparency is not None:
        raise BuildError(f"{path}: transparent grayscale/truecolor pixels are not allowed")
    if color_type == 3 and transparency is not None and len(transparency) > len(palette or []):
        raise BuildError(f"{path}: palette transparency table is invalid")

    bits_per_pixel = bit_depth * samples
    row_bytes = (w * bits_per_pixel + 7) // 8
    filter_bpp = max(1, (bits_per_pixel + 7) // 8)
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise BuildError(f"{path}: invalid compressed PNG image data") from exc
    if len(raw) != (row_bytes + 1) * h:
        raise BuildError(f"{path}: PNG image data length is inconsistent with IHDR")

    def paeth(a: int, b: int, c: int) -> int:
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        if pa <= pb and pa <= pc:
            return a
        if pb <= pc:
            return b
        return c

    decoded: list[bytearray] = []
    previous = bytearray(row_bytes)
    cursor = 0
    for y in range(h):
        filter_type = raw[cursor]
        cursor += 1
        row = bytearray(raw[cursor:cursor + row_bytes])
        cursor += row_bytes
        if filter_type == 1:
            for i in range(row_bytes):
                left = row[i - filter_bpp] if i >= filter_bpp else 0
                row[i] = (row[i] + left) & 0xFF
        elif filter_type == 2:
            for i in range(row_bytes):
                row[i] = (row[i] + previous[i]) & 0xFF
        elif filter_type == 3:
            for i in range(row_bytes):
                left = row[i - filter_bpp] if i >= filter_bpp else 0
                row[i] = (row[i] + ((left + previous[i]) // 2)) & 0xFF
        elif filter_type == 4:
            for i in range(row_bytes):
                left = row[i - filter_bpp] if i >= filter_bpp else 0
                upper_left = previous[i - filter_bpp] if i >= filter_bpp else 0
                row[i] = (row[i] + paeth(left, previous[i], upper_left)) & 0xFF
        elif filter_type != 0:
            raise BuildError(f"{path}: unsupported PNG filter type {filter_type}")
        decoded.append(row)
        previous = row

    def sample(row: bytearray, x: int) -> int:
        if bit_depth == 8:
            return row[x]
        per_byte = 8 // bit_depth
        shift = (per_byte - 1 - x % per_byte) * bit_depth
        return (row[x // per_byte] >> shift) & ((1 << bit_depth) - 1)

    def classify(r: int, g: int, b: int, alpha: int = 255) -> int:
        if alpha != 255:
            raise BuildError(f"{path}: transparent/alpha pixels are not allowed")
        if (r, g, b) == (0, 0, 0):
            return 0
        if (r, g, b) == (255, 255, 255):
            return 1
        raise BuildError(f"{path}: non-binary/antialiased pixel RGB=({r},{g},{b})")

    packed_rows: list[list[int]] = []
    max_sample = (1 << bit_depth) - 1
    for y, row in enumerate(decoded):
        packed: list[int] = []
        for byte_x in range(width_bytes):
            packed_byte = 0
            for bit in range(8):
                x = byte_x * 8 + bit
                if color_type == 0:
                    value = sample(row, x)
                    if value == 0:
                        on = 0
                    elif value == max_sample:
                        on = 1
                    else:
                        raise BuildError(f"{path}: grayscale pixel is not black/white at {x},{y}")
                elif color_type == 3:
                    index = sample(row, x)
                    if index >= len(palette):
                        raise BuildError(f"{path}: palette index {index} is out of range")
                    red, green, blue = palette[index]
                    alpha = transparency[index] if transparency is not None and index < len(transparency) else 255
                    on = classify(red, green, blue, alpha)
                elif color_type == 2:
                    offset = x * 3
                    on = classify(row[offset], row[offset + 1], row[offset + 2])
                elif color_type == 4:
                    offset = x * 2
                    value, alpha = row[offset], row[offset + 1]
                    on = classify(value, value, value, alpha)
                else:
                    offset = x * 4
                    on = classify(row[offset], row[offset + 1], row[offset + 2], row[offset + 3])
                if on:
                    packed_byte |= 0x80 >> bit
            packed.append(packed_byte)
        packed_rows.append(packed)
    return packed_rows


def decode_061f_row(data: bytes, offset: int, width: int, previous_two: list[int] | None = None) -> tuple[list[int], int]:
    row: list[int] = []
    while len(row) < width:
        if offset >= len(data):
            raise BuildError("061F source ended before the row was complete")
        token = data[offset]
        offset += 1
        if token >= 0x0D or token < 0x02:
            row.append(token)
        elif token == 0x02:
            raise BuildError("direct token 02 is invalid in a 061F stream")
        elif token == 0x03:
            if offset >= len(data):
                raise BuildError("truncated 061F run token")
            count_token = data[offset]
            offset += 1
            count = count_token & 0x7F
            if count == 0:
                raise BuildError("zero-length 061F run")
            if count_token & 0x80:
                if previous_two is None:
                    raise BuildError("061F previous-row reference has no source row")
                value = previous_two[len(row)]
            else:
                if offset >= len(data):
                    raise BuildError("truncated 061F run value")
                value = data[offset]
                offset += 1
            row.extend([value] * count)
        elif token == 0x04:
            if offset >= len(data):
                raise BuildError("truncated 061F escaped literal")
            row.append(data[offset])
            offset += 1
        elif 0x05 <= token <= 0x08:
            if offset >= len(data):
                raise BuildError("truncated 061F short run")
            row.extend([data[offset]] * (token - 3))
            offset += 1
        elif 0x09 <= token <= 0x0C:
            if previous_two is None:
                raise BuildError("061F previous-row reference has no source row")
            row.extend([previous_two[len(row)]] * (token - 7))
        if len(row) > width:
            raise BuildError(f"061F row overflow: {len(row)} > {width}")
    return row, offset


def decode_061f_planes(source: bytes, width: int, height: int, plane_names: tuple[str, ...]) -> dict[str, list[list[int]]]:
    decoded = {plane: [] for plane in plane_names}
    offset = 0
    for y in range(height):
        for plane in plane_names:
            previous_two = decoded[plane][y - 2] if y >= 2 else None
            row, offset = decode_061f_row(source, offset, width, previous_two)
            decoded[plane].append(row)
    if offset != len(source):
        raise BuildError(f"061F stream consumed {offset} of {len(source)} source bytes")
    return decoded


def decode_05ce_columns(source: bytes, calls: int, height: int) -> list[list[int]]:
    rows_by_y = [[0 for _ in range(calls)] for _ in range(height)]
    offset = 0
    for call in range(calls):
        column: list[int] = []
        while len(column) < height:
            if offset >= len(source):
                raise BuildError("05CE source ended before a column was complete")
            token = source[offset]
            offset += 1
            if token == 0x04:
                if offset >= len(source):
                    raise BuildError("truncated 05CE escaped literal")
                column.append(source[offset])
                offset += 1
            elif token == 0x05:
                if offset + 3 > len(source):
                    raise BuildError("truncated 05CE alternating run")
                count, first, second = source[offset:offset + 3]
                offset += 3
                if count == 0:
                    raise BuildError("zero-length 05CE alternating run")
                if len(column) + count * 2 > height:
                    raise BuildError("05CE alternating run overflows the column")
                for _ in range(count):
                    if len(column) < height:
                        column.append(first)
                    if len(column) < height:
                        column.append(second)
            else:
                column.append(token)
        for y, value in enumerate(column):
            rows_by_y[y][call] = value
    if offset != len(source):
        raise BuildError(f"05CE stream consumed {offset} of {len(source)} source bytes")
    return rows_by_y


def _possible_061f_row_encodings(row: list[int], previous_two: list[int] | None, max_length: int = 180) -> dict[int, bytes]:
    n = len(row)
    paths: list[dict[int, bytes]] = [{} for _ in range(n + 1)]
    paths[0][0] = b""
    for pos in range(n):
        for length, sequence in list(paths[pos].items()):
            value = row[pos]
            if value < 2 or value >= 0x0D:
                new_length = length + 1
                if new_length <= max_length:
                    paths[pos + 1].setdefault(new_length, sequence + bytes([value]))
            new_length = length + 2
            if new_length <= max_length:
                paths[pos + 1].setdefault(new_length, sequence + bytes([0x04, value]))
            run = 1
            while pos + run < n and row[pos + run] == value and run < 127:
                run += 1
            for count in range(2, min(5, run) + 1):
                new_length = length + 2
                if new_length <= max_length:
                    paths[pos + count].setdefault(new_length, sequence + bytes([count + 3, value]))
            for count in range(1, run + 1):
                new_length = length + 3
                if new_length <= max_length:
                    paths[pos + count].setdefault(new_length, sequence + bytes([0x03, count, value]))
            if previous_two is not None:
                previous_value = previous_two[pos]
                previous_run = 0
                while pos + previous_run < n and row[pos + previous_run] == previous_value and previous_run < 127:
                    previous_run += 1
                for count in range(2, min(5, previous_run) + 1):
                    new_length = length + 1
                    if new_length <= max_length:
                        paths[pos + count].setdefault(new_length, sequence + bytes([count + 7]))
                for count in range(1, previous_run + 1):
                    new_length = length + 2
                    if new_length <= max_length:
                        paths[pos + count].setdefault(new_length, sequence + bytes([0x03, 0x80 | count]))
    return paths[n]


def _exact_total_encodings(calls: list[dict[int, bytes]], exact_length: int, label: str) -> list[bytes]:
    parent: list[dict[int, tuple[int, int] | None]] = [{} for _ in range(len(calls) + 1)]
    parent[0][0] = None
    for index, possibilities in enumerate(calls):
        for total in list(parent[index]):
            for length in sorted(possibilities):
                new_total = total + length
                if new_total > exact_length:
                    break
                parent[index + 1].setdefault(new_total, (total, length))
    if exact_length not in parent[-1]:
        minimum = sum(min(possibilities) for possibilities in calls)
        maximum = sum(max(possibilities) for possibilities in calls)
        raise BuildError(f"{label}: cannot fit fixed source length {exact_length}; possible range {minimum}..{maximum}")
    lengths: list[int] = []
    total = exact_length
    for index in range(len(calls), 0, -1):
        previous = parent[index][total]
        assert previous is not None
        total, length = previous
        lengths.append(length)
    lengths.reverse()
    return [possibilities[length] for possibilities, length in zip(calls, lengths)]


def encode_061f_planes(planes: dict[str, list[list[int]]], width: int, height: int,
                       plane_names: tuple[str, ...], exact_length: int) -> bytes:
    if width <= 0 or height <= 0 or set(planes) != set(plane_names) or not plane_names:
        raise BuildError("invalid 061F plane configuration")
    if any(len(planes[plane]) != height or any(len(row) != width for row in planes[plane]) for plane in plane_names):
        raise BuildError("061F plane dimensions do not match the declared size")
    calls: list[dict[int, bytes]] = []
    for y in range(height):
        for plane in plane_names:
            previous_two = planes[plane][y - 2] if y >= 2 else None
            possibilities = _possible_061f_row_encodings(planes[plane][y], previous_two)
            if not possibilities:
                raise BuildError(f"061F cannot encode row {y}, plane {plane}")
            calls.append(possibilities)
    chosen = _exact_total_encodings(calls, exact_length, "061F logo")
    source = b"".join(chosen)
    decoded = decode_061f_planes(source, width, height, plane_names)
    if decoded != planes:
        raise BuildError("061F PNG-to-source roundtrip did not preserve pixels")
    return source


def _possible_05ce_encodings(rows: list[int], max_length: int = 64) -> dict[int, bytes]:
    n = len(rows)
    paths: list[dict[int, bytes]] = [{} for _ in range(n + 1)]
    paths[0][0] = b""
    for pos in range(n):
        for length, sequence in list(paths[pos].items()):
            value = rows[pos]
            if value not in (0x04, 0x05):
                new_length = length + 1
                if new_length <= max_length:
                    paths[pos + 1].setdefault(new_length, sequence + bytes([value]))
            new_length = length + 2
            if new_length <= max_length:
                paths[pos + 1].setdefault(new_length, sequence + bytes([0x04, value]))
            if pos + 1 < n:
                first, second = rows[pos], rows[pos + 1]
                max_pairs = (n - pos) // 2
                for count in range(1, max_pairs + 1):
                    if any(rows[pos + 2 * k:pos + 2 * k + 2] != [first, second] for k in range(count)):
                        break
                    new_length = length + 4
                    if new_length <= max_length:
                        paths[pos + 2 * count].setdefault(
                            new_length, sequence + bytes([0x05, count, first, second])
                        )
    return paths[n]


def encode_05ce_columns(rows_by_y: list[list[int]], exact_length: int, width_bytes: int, height: int) -> bytes:
    if len(rows_by_y) != height or any(len(row) != width_bytes for row in rows_by_y):
        raise BuildError(f"05CE image must be {width_bytes * 8}x{height} pixels")
    columns = [[rows_by_y[y][column] for y in range(height)] for column in range(width_bytes)]
    possibilities_by_column = [_possible_05ce_encodings(column) for column in columns]
    if any(not possibilities for possibilities in possibilities_by_column):
        raise BuildError("05CE cannot encode one or more logo columns")
    source = b"".join(_exact_total_encodings(possibilities_by_column, exact_length, "05CE logo"))
    if decode_05ce_columns(source, width_bytes, height) != rows_by_y:
        raise BuildError("05CE PNG-to-source roundtrip did not preserve pixels")
    return source


def _map_int(value: str, field: str, path: Path) -> int:
    try:
        return int(value, 0)
    except ValueError as exc:
        raise BuildError(f"invalid {field} in {path}: {value!r}") from exc


def _read_source_map(root: Path) -> tuple[LogoGroup, ...]:
    path = root / "source/tables/logo/source-map.csv"
    rows = _read_csv(path)
    required = {
        "target", "group", "plane", "ram_base", "source_length", "width", "height",
        "edit_png", "encoder", "baseline_pixels_sha256", "notes",
    }
    if not rows or not required.issubset(rows[0]):
        raise BuildError(f"{path} must define {', '.join(sorted(required))}")
    targets: set[str] = set()
    grouped_rows: dict[str, list[tuple[LogoInput, tuple[int, int, str, int, int]]]] = {}
    source_root = (root / "source").resolve()
    for row_number, row in enumerate(rows, 2):
        missing = sorted(field for field in required if row.get(field) is None)
        if missing:
            raise BuildError(f"{path} row {row_number} is missing values: {', '.join(missing)}")
        target = row["target"].strip()
        name = row["group"].strip()
        plane = row["plane"].strip()
        if not target or target in targets or not name or not plane:
            raise BuildError(f"{path} has a missing or duplicate target")
        targets.add(target)
        encoder = row["encoder"].strip()
        if encoder not in {"061F", "05CE"}:
            raise BuildError(f"unsupported logo encoder for {target}: {row['encoder']}")
        base = _map_int(row["ram_base"], "ram_base", path)
        length = _map_int(row["source_length"], "source_length", path)
        width = _map_int(row["width"], "width", path)
        height = _map_int(row["height"], "height", path)
        if not 0 <= base <= 0xFFFF or length <= 0 or base + length > 0x10000:
            raise BuildError(f"invalid logo source range for {target}")
        if width <= 0 or width % 8 or height <= 0:
            raise BuildError(f"invalid logo dimensions for {target}: {width}x{height}")
        edit_png = row["edit_png"].strip()
        if not edit_png:
            raise BuildError(f"missing logo PNG path for {target}")
        image_path = (path.parent / edit_png).resolve()
        try:
            image_path.relative_to(source_root)
        except ValueError as exc:
            raise BuildError(f"logo PNG path escapes source/: {edit_png}") from exc
        expected_hash = row["baseline_pixels_sha256"].strip().lower()
        if len(expected_hash) != 64 or any(char not in "0123456789abcdef" for char in expected_hash):
            raise BuildError(f"invalid baseline pixel hash for {target}")
        image = LogoInput(target, plane, image_path, edit_png, expected_hash)
        signature = (base, length, encoder, width, height)
        grouped_rows.setdefault(name, []).append((image, signature))

    groups: list[LogoGroup] = []
    for name, entries in grouped_rows.items():
        signatures = {entry[1] for entry in entries}
        if len(signatures) != 1:
            raise BuildError(f"logo group {name} has inconsistent source metadata")
        base, length, encoder, width, height = next(iter(signatures))
        images = tuple(entry[0] for entry in entries)
        planes = [item.plane for item in images]
        if len(set(planes)) != len(planes):
            raise BuildError(f"logo group {name} has duplicate planes")
        if encoder == "05CE" and len(images) != 1:
            raise BuildError(f"05CE logo group {name} must have exactly one PNG")
        groups.append(LogoGroup(name, base, length, encoder, width, height, images))

    ranges = sorted((group.base, group.base + group.length, group.name) for group in groups)
    for previous, current in zip(ranges, ranges[1:]):
        if current[0] < previous[1]:
            raise BuildError(f"overlapping logo RAM ranges: {previous[2]} and {current[2]}")
    return tuple(groups)


def _read_ram_map(root: Path) -> dict[int, dict[str, str]]:
    path = root / "source/tables/logo/ram-to-raw-map.csv"
    rows = _read_csv(path)
    result: dict[int, dict[str, str]] = {}
    raw_offsets: set[int] = set()
    for row in rows:
        try:
            address = int(row["ram_addr"], 16)
        except (KeyError, ValueError) as exc:
            raise BuildError(f"invalid ram_addr in {path}") from exc
        if address in result:
            raise BuildError(f"duplicate RAM address in {path}: 0x{address:04X}")
        try:
            raw_offset = int(row["raw_file_offset"], 16)
            raw_index = int(row["raw_index"], 16)
            raw_base = int(row["sector_raw_base"], 16)
            cylinder = int(row["d88_c"], 16)
            stored = int(row["stored_byte"], 16)
            raw = int(row["current_raw_byte"], 16)
        except (KeyError, TypeError, ValueError) as exc:
            raise BuildError(f"invalid logo mapping at RAM 0x{address:04X}") from exc
        if not 0 <= address <= 0xFFFF or not 0 <= raw_index < 0x400:
            raise BuildError(f"logo map address/index is out of range: 0x{address:04X}")
        if raw_offset != raw_base + raw_index or raw_offset in raw_offsets:
            raise BuildError(f"invalid or duplicate logo raw offset: 0x{raw_offset:X}")
        if not 0 <= stored <= 255 or not 0 <= raw <= 255:
            raise BuildError(f"logo mapping byte is out of range at 0x{address:04X}")
        de = 0x400 - raw_index
        recovered = (raw - (de >> 8) - (de & 255) + 0x40 - cylinder) & 255
        if recovered != stored:
            raise BuildError(f"logo map roundtrip mismatch at 0x{address:04X}")
        raw_offsets.add(raw_offset)
        result[address] = row
    return result


def _original_source(ram_map: dict[int, dict[str, str]], base: int, length: int) -> bytes:
    result = bytearray()
    for address in range(base, base + length):
        row = ram_map.get(address)
        if row is None:
            raise BuildError(f"logo RAM map is missing 0x{address:04X}")
        try:
            result.append(int(row["stored_byte"], 16))
        except (KeyError, ValueError) as exc:
            raise BuildError(f"invalid original stored byte at 0x{address:04X}") from exc
    return bytes(result)


def _load_logo_images(root: Path) -> tuple[
    tuple[LogoGroup, ...], dict[str, list[list[int]]], dict[str, str], tuple[LogoGroup, ...]
]:
    """Read every declared PNG and identify groups whose pixels changed."""
    groups = _read_source_map(root)
    loaded: dict[str, list[list[int]]] = {}
    pixel_hashes: dict[str, str] = {}
    for group in groups:
        for image in group.images:
            loaded[image.target] = load_binary_png_rows(
                image.path, group.width_pixels, group.height, group.width_bytes
            )
            packed = bytes(value for image_row in loaded[image.target] for value in image_row)
            pixel_hashes[image.target] = hashlib.sha256(packed).hexdigest()
    changed_groups = tuple(
        group for group in groups
        if any(pixel_hashes[image.target] != image.baseline_pixels_sha256 for image in group.images)
    )
    return groups, loaded, pixel_hashes, changed_groups


def lint_logo_inputs(root: str | Path) -> dict:
    """Validate declared PNGs and report edited groups without requiring a ROM image."""
    root = Path(root)
    groups, _loaded, _pixel_hashes, changed_groups = _load_logo_images(root)
    ram_map = _read_ram_map(root)
    for group in groups:
        _original_source(ram_map, group.base, group.length)
    changed_targets = {
        image.target
        for group in changed_groups
        for image in group.images
        if _pixel_hashes[image.target] != image.baseline_pixels_sha256
    }
    return {
        "groups": len(groups),
        "png_inputs": sum(len(group.images) for group in groups),
        "edited_groups": [group.name for group in changed_groups],
        "edited_pngs": sorted(changed_targets),
        "status": "OK",
    }


def prepare_logo_build(root: str | Path) -> LogoBuildPlan:
    """Load GFX PNGs and re-encode only groups whose pixels were edited."""
    root = Path(root)
    groups, loaded, _pixel_hashes, changed_groups = _load_logo_images(root)

    if not changed_groups:
        return LogoBuildPlan((), (), {})

    ram_map = _read_ram_map(root)
    encoded: list[EncodedLogo] = []
    skipped_ranges: list[tuple[int, int]] = []
    for group in changed_groups:
        original = _original_source(ram_map, group.base, group.length)
        inputs = tuple(image.edit_png for image in group.images)
        if group.encoder == "061F":
            plane_names = tuple(image.plane for image in group.images)
            planes = {image.plane: loaded[image.target] for image in group.images}
            original_planes = decode_061f_planes(original, group.width_bytes, group.height, plane_names)
            if original_planes == planes:
                source = original
                handling = "original_reused"
            else:
                source = encode_061f_planes(planes, group.width_bytes, group.height,
                                            plane_names, group.length)
                handling = "png_encoded"
        else:
            movement = loaded[group.images[0].target]
            original_movement = decode_05ce_columns(original, group.width_bytes, group.height)
            if original_movement == movement:
                source = original
                handling = "original_reused"
            else:
                source = encode_05ce_columns(movement, group.length, group.width_bytes, group.height)
                handling = "png_encoded"
        if len(source) != group.length:
            raise BuildError(f"{group.name} source length changed: {len(source)} != {group.length}")
        encoded.append(EncodedLogo(group.name, group.base, source, group.encoder, inputs, handling))
        skipped_ranges.append((group.base, group.base + group.length))
    return LogoBuildPlan(tuple(skipped_ranges), tuple(encoded), ram_map)


def apply_logo_build(image: D88Image, plan: LogoBuildPlan) -> dict | None:
    if not plan.encoded:
        return None
    total_writes = 0
    total_changed = 0
    target_reports = []
    for logo in plan.encoded:
        changed = 0
        for index, stored in enumerate(logo.data):
            address = logo.base + index
            mapping = plan.ram_map.get(address)
            if mapping is None:
                raise BuildError(f"logo RAM map is missing 0x{address:04X}")
            try:
                raw_offset = int(mapping["raw_file_offset"], 16)
                raw_index = int(mapping["raw_index"], 16)
                d88_c = int(mapping["d88_c"], 16)
                expected_raw = int(mapping["current_raw_byte"], 16)
            except (KeyError, ValueError) as exc:
                raise BuildError(f"invalid D88 reverse-map row at 0x{address:04X}") from exc
            image.find_data_sector(raw_offset)
            actual_raw = image.data[raw_offset]
            if actual_raw != expected_raw:
                raise BuildError(
                    f"logo source old byte mismatch at 0x{raw_offset:X}: "
                    f"map={expected_raw:02X} input={actual_raw:02X}"
                )
            de = 0x400 - raw_index
            d, e = (de >> 8) & 0xFF, de & 0xFF
            correction = 0x40 - d88_c
            new_raw = (stored + d + e - correction) & 0xFF
            recovered = (new_raw - d - e + correction) & 0xFF
            if recovered != stored:
                raise BuildError(f"logo raw reverse check failed at RAM 0x{address:04X}")
            image.write_data(raw_offset, bytes([new_raw]), expected_old=bytes([expected_raw]))
            changed += int(actual_raw != new_raw)
        total_writes += len(logo.data)
        total_changed += changed
        target_reports.append({
            "name": logo.name,
            "encoder": logo.encoder,
            "source_length": len(logo.data),
            "source_handling": logo.source_handling,
            "png_inputs": list(logo.inputs),
            "changed_raw_bytes": changed,
        })
    return {
        "component": "logo_png",
        "writes": total_writes,
        "changed": total_changed,
        "targets": target_reports,
    }
