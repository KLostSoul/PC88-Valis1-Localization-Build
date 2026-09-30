"""IPS patch encoding and round-trip validation."""

from __future__ import annotations

from .errors import BuildError


def encode_ips(source: bytes, target: bytes) -> bytes:
    """Encode same-size binary changes as a standard IPS patch."""
    if len(source) != len(target):
        raise BuildError("IPS 출력은 입력과 크기가 같아야 합니다")
    if len(source) > 0x1000000:
        raise BuildError("IPS 입력은 16 MiB 이하이어야 합니다")

    patch = bytearray(b"PATCH")
    offset = 0
    while offset < len(source):
        while offset < len(source) and source[offset] == target[offset]:
            offset += 1
        if offset == len(source):
            break
        start = offset
        offset += 1
        while offset < len(source) and source[offset] != target[offset] and offset - start < 0xFFFF:
            offset += 1
        if start == 0x454F46:
            raise BuildError("IPS 레코드 주소가 EOF 종료 표식과 충돌합니다")
        patch.extend(start.to_bytes(3, "big"))
        patch.extend((offset - start).to_bytes(2, "big"))
        patch.extend(target[start:offset])
    patch.extend(b"EOF")
    return bytes(patch)


def apply_ips(source: bytes, patch: bytes) -> bytes:
    """Apply generated standard IPS records to a same-size source."""
    if not patch.startswith(b"PATCH"):
        raise BuildError("IPS 헤더가 잘못되었습니다")
    result = bytearray(source)
    cursor = 5
    while True:
        if cursor + 3 > len(patch):
            raise BuildError("IPS 종료 표식이 없습니다")
        if patch[cursor:cursor + 3] == b"EOF":
            cursor += 3
            if cursor != len(patch):
                raise BuildError("IPS 종료 표식 뒤에 데이터가 있습니다")
            return bytes(result)
        offset = int.from_bytes(patch[cursor:cursor + 3], "big")
        cursor += 3
        if cursor + 2 > len(patch):
            raise BuildError("IPS 레코드 길이가 잘렸습니다")
        length = int.from_bytes(patch[cursor:cursor + 2], "big")
        cursor += 2
        if length == 0:
            raise BuildError("IPS RLE 레코드는 지원하지 않습니다")
        end = offset + length
        if end > len(result) or cursor + length > len(patch):
            raise BuildError("IPS 레코드가 입력 또는 패치 범위를 벗어났습니다")
        result[offset:end] = patch[cursor:cursor + length]
        cursor += length
