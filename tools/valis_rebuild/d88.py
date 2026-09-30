"""D88 parser and fixed-layout serializer.

The image is never flattened for writing.  Event maps in this project refer
to D88 *sector data offsets*, so sector headers and inter-sector gaps remain
untouched while a write is explicitly routed into sector payload bytes.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
from pathlib import Path
import struct

from .errors import BuildError

D88_HEADER_SIZE = 0x2B0
TRACK_POINTER_OFFSET = 0x20
TRACK_POINTER_COUNT = 164
SECTOR_HEADER_SIZE = 16


@dataclass(frozen=True)
class Sector:
    track_index: int
    file_header_offset: int
    data_offset: int
    length: int
    c: int
    h: int
    r: int
    n: int
    sectors_per_track: int
    density: int
    deleted: int
    status: int

    @property
    def end(self) -> int:
        return self.data_offset + self.length

    @property
    def chrn(self) -> str:
        return f"{self.c:02X}/{self.h:02X}/{self.r:02X}/{self.n:02X}"


class D88Image:
    def __init__(self, data: bytes | bytearray, sectors: list[Sector], pointers: list[int]):
        self.data = bytearray(data)
        self.sectors = sectors
        self.pointers = pointers
        self.written_offsets: set[int] = set()

    @classmethod
    def read(cls, path: str | Path) -> "D88Image":
        data = Path(path).read_bytes()
        return cls.parse(data)

    @classmethod
    def parse(cls, data: bytes | bytearray) -> "D88Image":
        if len(data) < D88_HEADER_SIZE:
            raise BuildError(f"D88 is shorter than 0x2B0-byte header: {len(data)}")
        if struct.unpack_from("<I", data, 0x1C)[0] != len(data):
            raise BuildError("D88 declared disk size does not match the file size")
        pointers = [struct.unpack_from("<I", data, TRACK_POINTER_OFFSET + 4 * i)[0]
                    for i in range(TRACK_POINTER_COUNT)]
        nonzero = [(i, p) for i, p in enumerate(pointers) if p]
        if not nonzero:
            raise BuildError("D88 contains no track pointers")
        if any(p < D88_HEADER_SIZE or p >= len(data) for _, p in nonzero):
            raise BuildError("D88 track pointer is outside the file")
        if any(left[1] >= right[1] for left, right in zip(nonzero, nonzero[1:])):
            raise BuildError("D88 track pointers must be strictly increasing")

        sectors: list[Sector] = []
        for pos_idx, (track_index, start) in enumerate(nonzero):
            end = nonzero[pos_idx + 1][1] if pos_idx + 1 < len(nonzero) else len(data)
            pos = start
            track_sectors: list[Sector] = []
            while pos < end:
                if pos + SECTOR_HEADER_SIZE > end:
                    raise BuildError(f"truncated sector header at 0x{pos:X}")
                header = data[pos:pos + SECTOR_HEADER_SIZE]
                length = int.from_bytes(header[14:16], "little")
                data_offset = pos + SECTOR_HEADER_SIZE
                if data_offset + length > end:
                    raise BuildError(
                        f"sector payload crosses track boundary at 0x{pos:X}: "
                        f"0x{data_offset + length:X} > 0x{end:X}"
                    )
                if length not in (128, 256, 512, 1024):
                    raise BuildError(f"unsupported D88 sector length {length} at 0x{pos:X}")
                sectors.append(Sector(
                    track_index=track_index,
                    file_header_offset=pos,
                    data_offset=data_offset,
                    length=length,
                    c=header[0], h=header[1], r=header[2], n=header[3],
                    sectors_per_track=int.from_bytes(header[4:6], "little"),
                    density=header[6], deleted=header[7], status=header[8],
                ))
                track_sectors.append(sectors[-1])
                pos = data_offset + length
            if pos != end:
                raise BuildError(f"track {track_index} does not terminate at its next pointer")
            if any(s.sectors_per_track != len(track_sectors) for s in track_sectors):
                raise BuildError(f"track {track_index} has inconsistent sector counts")

        image = cls(data, sectors, pointers)
        image.validate_structure()
        return image

    def validate_structure(self) -> None:
        if len(self.data) != 414_992:
            raise BuildError(f"unexpected Disk A D88 size: {len(self.data)}")
        if len(self.sectors) != 422:
            raise BuildError(f"unexpected sector count: {len(self.sectors)}")
        payload = sum(s.length for s in self.sectors)
        if payload != 407_552:
            raise BuildError(f"unexpected flat payload length: {payload}")
        for s in self.sectors:
            if self.data[s.file_header_offset + 14:s.file_header_offset + 16] != s.length.to_bytes(2, "little"):
                raise BuildError(f"sector header changed internally at 0x{s.file_header_offset:X}")

    def sector_manifest(self) -> list[dict]:
        return [asdict(s) | {"end": s.end, "chrn": s.chrn} for s in self.sectors]

    def find_data_sector(self, offset: int) -> Sector:
        for sector in self.sectors:
            if sector.data_offset <= offset < sector.end:
                return sector
        raise BuildError(f"file offset 0x{offset:X} is not inside a D88 sector payload")

    def find_chrn(self, c: int, h: int, r: int, n: int) -> Sector:
        matches = [s for s in self.sectors if (s.c, s.h, s.r, s.n) == (c, h, r, n)]
        if len(matches) != 1:
            raise BuildError(f"CHRN {c:02X}/{h:02X}/{r:02X}/{n:02X} matched {len(matches)} sectors")
        return matches[0]

    def read_data(self, offset: int, length: int) -> bytes:
        if length < 0:
            raise BuildError("read length cannot be negative")
        sector = self.find_data_sector(offset)
        if offset + length > sector.end:
            raise BuildError("read crosses a sector boundary; use read_data_ranges")
        return bytes(self.data[offset:offset + length])

    def read_data_ranges(self, ranges: list[tuple[int, int]]) -> bytes:
        out = bytearray()
        for offset, length in ranges:
            out.extend(self.read_data(offset, length))
        return bytes(out)

    def write_data(self, offset: int, payload: bytes, *, expected_old: bytes | None = None) -> None:
        sector = self.find_data_sector(offset)
        if offset + len(payload) > sector.end:
            raise BuildError(
                f"write 0x{offset:X}+{len(payload):X} crosses sector boundary; "
                "declare separate data segments"
            )
        if expected_old is not None:
            if len(expected_old) != len(payload):
                raise BuildError("expected_old length differs from write length")
            actual = bytes(self.data[offset:offset + len(payload)])
            if actual != expected_old:
                raise BuildError(f"old_value mismatch at 0x{offset:X}")
        offsets = set(range(offset, offset + len(payload)))
        overlap = offsets & self.written_offsets
        if overlap:
            raise BuildError(f"overlapping component writes at 0x{min(overlap):X}")
        self.data[offset:offset + len(payload)] = payload
        self.written_offsets.update(offsets)

    def write_data_ranges(self, ranges: list[tuple[int, int]], payload: bytes) -> None:
        if any(length < 0 for _, length in ranges):
            raise BuildError("range lengths cannot be negative")
        if sum(length for _, length in ranges) != len(payload):
            raise BuildError("range lengths do not equal payload length")
        cursor = 0
        for offset, length in ranges:
            self.write_data(offset, payload[cursor:cursor + length])
            cursor += length

    def flatten_payload(self) -> bytes:
        return b"".join(bytes(self.data[s.data_offset:s.end]) for s in self.sectors)

    def save(self, path: str | Path) -> None:
        self.validate_structure()
        Path(path).write_bytes(self.data)

    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    def export(self, output_dir: str | Path, *, source_path: str | Path | None = None) -> None:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "payload.bin").write_bytes(self.flatten_payload())
        (out / "sectors.json").write_text(json.dumps({
            "schema": "valis-d88-export/v1",
            "source_sha256": self.sha256(),
            "source_size": len(self.data),
            "sector_count": len(self.sectors),
            "flat_payload_size": len(self.flatten_payload()),
            "source_path_is_metadata_only": str(source_path) if source_path else None,
            "sectors": self.sector_manifest(),
        }, indent=2) + "\n", encoding="utf-8")
        (out / "sha256.json").write_text(json.dumps({
            "d88_sha256": self.sha256(),
            "payload_sha256": hashlib.sha256(self.flatten_payload()).hexdigest(),
        }, indent=2) + "\n", encoding="utf-8")
