"""The verified 0x400-byte reverse storage codec."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import BuildError


def _address_sum(index: int) -> int:
    """The loader adds HIGH(DE)+LOW(DE), with DE = index + 1."""
    de = index + 1
    return ((de >> 8) + (de & 0xFF)) & 0xFF


def encode_byte(decoded: int, index: int, correction: int) -> int:
    return (decoded + _address_sum(index) - correction) & 0xFF


def decode_byte(raw: int, index: int, correction: int) -> int:
    return (raw - _address_sum(index) + correction) & 0xFF


def encode_block(decoded: bytes, correction: int) -> bytes:
    if len(decoded) != 0x400:
        raise BuildError(f"reverse codec requires exactly 0x400 bytes, got {len(decoded):#x}")
    raw = bytearray(0x400)
    for index, value in enumerate(decoded):
        raw[0x3FF - index] = encode_byte(value, index, correction)
    return bytes(raw)


def decode_block(raw: bytes, correction: int) -> bytes:
    if len(raw) != 0x400:
        raise BuildError(f"reverse codec requires exactly 0x400 bytes, got {len(raw):#x}")
    decoded = bytearray(0x400)
    for index in range(0x400):
        decoded[index] = decode_byte(raw[0x3FF - index], index, correction)
    return bytes(decoded)


@dataclass(frozen=True)
class CorrectionSegment:
    start: int
    end: int
    correction: int

    def contains(self, address: int) -> bool:
        return self.start <= address <= self.end


def correction_for(segments: list[CorrectionSegment], address: int) -> int:
    matches = [s.correction for s in segments if s.contains(address)]
    if len(matches) != 1:
        raise BuildError(f"expected one correction for address 0x{address:X}, got {matches}")
    return matches[0]


def encode_event(decoded: bytes, *, runtime_base: int, capacity: int,
                 corrections: list[CorrectionSegment]) -> bytes:
    if capacity < 0 or capacity % 0x400:
        raise BuildError("event capacity must be a multiple of 0x400")
    if len(decoded) > capacity:
        raise BuildError(f"decoded stream length {len(decoded)} exceeds capacity {capacity}")
    padded = decoded + bytes(capacity - len(decoded))
    raw = bytearray(capacity)
    for index, value in enumerate(padded):
        matches = [s.correction for s in corrections
                   if s.contains(runtime_base + index)]
        # A source table may end before the allocated physical area.  In that
        # case the caller preserves the original tail and no correction is
        # needed for the synthetic zero padding.  Missing or overlapping
        # coverage for a real source byte still fails closed.
        if not matches and index >= len(decoded):
            continue
        if len(matches) != 1:
            raise BuildError(
                f"expected one correction for address 0x{runtime_base + index:X}, got {matches}"
            )
        correction = matches[0]
        raw[0x3FF - (index % 0x400) + (index // 0x400) * 0x400] = encode_byte(
            value, index % 0x400, correction
        )
    return bytes(raw)


def decode_event(raw: bytes, *, runtime_base: int,
                 corrections: list[CorrectionSegment]) -> bytes:
    if len(raw) % 0x400:
        raise BuildError("event raw storage must be a multiple of 0x400")
    out = bytearray(len(raw))
    for index in range(len(raw)):
        correction = correction_for(corrections, runtime_base + index)
        block_start = (index // 0x400) * 0x400
        local = index % 0x400
        out[index] = decode_byte(raw[block_start + 0x3FF - local], local, correction)
    return bytes(out)


def make_reverse_plan(decoded: bytes, *, sub_start: int,
                      correction: int,
                      data_bases: dict[int, int]) -> dict[int, int]:
    """Map a decoded SUB range to physical D88 data offsets.

    `data_bases` maps each 0x400-aligned decoded block to the corresponding
    sector data offset.  The map is explicit so no global address heuristic can
    silently write into a neighbouring resource.
    """
    plan: dict[int, int] = {}
    for offset, value in enumerate(decoded):
        address = sub_start + offset
        block = address & ~0x3FF
        if block not in data_bases:
            raise BuildError(f"no explicit D88 data base for decoded block 0x{block:X}")
        local = address - block
        file_offset = data_bases[block] + 0x3FF - local
        encoded = encode_byte(value, local, correction)
        old = plan.get(file_offset)
        if old is not None:
            raise BuildError(f"conflicting duplicate raw offset 0x{file_offset:X}")
        plan[file_offset] = encoded
    return plan


def apply_plan(image, plan: dict[int, int]) -> None:
    """Apply an explicit offset plan with no last-write-wins behavior."""
    for offset, value in sorted(plan.items()):
        image.write_data(offset, bytes([value]))
