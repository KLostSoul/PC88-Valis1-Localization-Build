"""Strict gates between manual analysis, accepted source metadata, and builds.

This module does not parse project documents or infer source rows. It validates
the hand-authored ledger, accepted source metadata, and declared logo inputs.
"""

from __future__ import annotations

import json
import csv
from pathlib import Path
import re

from .errors import BuildError
from .logo import lint_logo_inputs
from .text_sources import lint_text_sources
from .kanji import load_assignments, read_visual_txt
from .serializer import load_raw_writes, _byte
from .codec import decode_byte
from .gameover import lint_gameover_sources


REQUIRED_FACT_FIELDS = {
    "id", "component", "assertion", "source_documents", "source_location",
    "literal_observation", "address_layer", "status", "review",
}
ALLOWED_FACT_STATUS = {"observed", "derived", "confirmed", "conflict", "blocked"}
REQUIRED_COMPONENT_STATUS = "accepted"


def _repository_file(root: Path, reference: str) -> bool:
    if not isinstance(reference, str) or not reference:
        return False
    relative = Path(reference.split("#", 1)[0])
    if relative.is_absolute() or ".." in relative.parts:
        return False
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        return False
    if "#" in reference and path.suffix == ".md":
        anchor = reference.split("#", 1)[1]
        headings = re.findall(r"^#+\s+(.+)$", path.read_text(encoding="utf-8"), re.M)
        anchors = {re.sub(r"[^\w\s-]", "", heading).strip().lower().replace(" ", "-") for heading in headings}
        if anchor not in anchors:
            return False
    return True


def _load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"cannot read evidence/source manifest: {path}") from exc
    if not isinstance(value, dict):
        raise BuildError(f"manifest must be a JSON object: {path}")
    return value


def lint_ledger(repo_root: str | Path) -> dict:
    root = Path(repo_root)
    path = root / "analysis" / "evidence-ledger.json"
    doc = _load(path)
    if doc.get("schema") != "valis-manual-evidence-ledger/v2":
        raise BuildError("unexpected evidence ledger schema")
    facts = doc.get("facts")
    if not isinstance(facts, list):
        raise BuildError("evidence ledger facts must be a list")
    errors: list[str] = []
    ids: set[str] = set()
    for index, fact in enumerate(facts):
        if not isinstance(fact, dict):
            errors.append(f"fact {index} is not an object")
            continue
        missing = sorted(REQUIRED_FACT_FIELDS - set(fact))
        if missing:
            errors.append(f"fact {index} missing fields: {', '.join(missing)}")
        fact_id = fact.get("id")
        if fact_id in ids:
            errors.append(f"duplicate fact id: {fact_id}")
        if isinstance(fact_id, str):
            ids.add(fact_id)
        if fact.get("status") not in ALLOWED_FACT_STATUS:
            errors.append(f"fact {fact_id} has invalid status")
        review = fact.get("review")
        if not isinstance(review, dict) or review.get("status") not in {"pending", "confirmed", "blocked"}:
            errors.append(f"fact {fact_id} has invalid review status")
        if fact.get("status") == "confirmed" and (not isinstance(review, dict) or review.get("status") != "confirmed"):
            errors.append(f"fact {fact_id} claims confirmed without confirmed review")
        if fact.get("status") != "confirmed":
            errors.append(f"fact {fact_id} is not confirmed")
        documents = fact.get("source_documents")
        if not isinstance(documents, list) or not documents:
            errors.append(f"fact {fact_id} lacks repository sources")
        else:
            for reference in documents:
                if not _repository_file(root, reference):
                    errors.append(f"fact {fact_id} references a missing repository file: {reference}")
    return {
        "path": str(path.relative_to(root)),
        "fact_count": len(facts),
        "fact_ids": sorted(ids),
        "errors": errors,
        "status": "OK" if not errors else "INVALID",
    }


def lint_source_manifest(repo_root: str | Path) -> dict:
    root = Path(repo_root)
    path = root / "source" / "source-manifest.json"
    doc = _load(path)
    if doc.get("schema") != "valis-accepted-source-manifest/v2":
        raise BuildError("unexpected accepted source manifest schema")
    components = doc.get("components")
    if not isinstance(components, list) or not components:
        raise BuildError("accepted source manifest has no components")
    ids: set[str] = set()
    errors: list[str] = []
    for component in components:
        if not isinstance(component, dict) or not component.get("id"):
            errors.append("component without id")
            continue
        component_id = component["id"]
        if component_id in ids:
            errors.append(f"duplicate component id: {component_id}")
        ids.add(component_id)
        if component.get("required") and component.get("status") != REQUIRED_COMPONENT_STATUS:
            errors.append(f"required component is not accepted: {component_id}")
    accepted_files = doc.get("accepted_files")
    if not isinstance(accepted_files, list):
        errors.append("accepted_files must be a list")
    known_reviews = {fact["id"] for fact in _load(root / "analysis/evidence-ledger.json")["facts"]}
    seen_files: set[str] = set()
    for item in accepted_files or []:
        if not isinstance(item, dict) or not item.get("path") or not item.get("review_ids"):
            errors.append("accepted file lacks path or review_ids")
            continue
        if item.get("generated") is True:
            errors.append(f"generated file cannot be accepted: {item.get('path')}")
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            errors.append(f"accepted file path escapes repository: {item['path']}")
            continue
        if not _repository_file(root, item["path"]):
            errors.append(f"accepted file is missing: {item['path']}")
        if item["path"] in seen_files:
            errors.append(f"duplicate accepted file: {item['path']}")
        seen_files.add(item["path"])
        review_ids = item.get("review_ids")
        if not isinstance(review_ids, list) or not all(isinstance(value, str) and value for value in review_ids):
            errors.append(f"accepted file has invalid review_ids: {item['path']}")
        elif any(value not in known_reviews for value in review_ids):
            errors.append(f"accepted file has unknown review_ids: {item['path']}")
    buildable = doc.get("status") == "accepted" and doc.get("buildable") is True and not errors
    return {
        "path": str(path.relative_to(root)),
        "component_count": len(components),
        "accepted_file_count": len(accepted_files or []),
        "errors": errors,
        "declared_status": doc.get("status"),
        "buildable": buildable,
        "status": "OK" if buildable else "BLOCKED",
    }


def lint_release_baseline(repo_root: str | Path) -> dict:
    root = Path(repo_root)
    path = root / "source" / "release-baseline.json"
    doc = _load(path)
    errors: list[str] = []
    if doc.get("schema") != "valis-release-baseline/v1":
        errors.append("unexpected release baseline schema")
    for section in ("input", "output"):
        value = doc.get(section)
        if not isinstance(value, dict):
            errors.append(f"missing {section} release values")
            continue
        for key in ("d88_sha256", "d88_size", "kanji1_sha256", "kanji1_size"):
            if key not in value:
                errors.append(f"missing {section}.{key}")
            elif key.endswith("sha256"):
                if not isinstance(value[key], str) or re.fullmatch(r"[0-9a-f]{64}", value[key]) is None:
                    errors.append(f"invalid {section}.{key}")
            elif type(value[key]) is not int or value[key] <= 0:
                errors.append(f"invalid {section}.{key}")
    for media, prefix in (("d88", "d88"), ("kanji1", "kanji1")):
        layout = _load(root / f"source/media/{media}-layout.json")
        for field in ("sha256", "size"):
            if layout.get("input", {}).get(field) != doc.get("input", {}).get(f"{prefix}_{field}"):
                errors.append(f"{media} input layout disagrees with release baseline: {field}")
    contract = doc.get("component_contract")
    if not isinstance(contract, dict):
        errors.append("missing final component contract")
    required_contract = {"rule", "logo_png_inputs", "logo_source_groups", "logo_encoded_source_bytes", "gameover_scroll_records", "event_final_raw_updates", "error07_final_raw_updates"}
    if isinstance(contract, dict) and not required_contract.issubset(contract):
        errors.append("final component contract is incomplete")
    return {
        "path": str(path.relative_to(root)),
        "logo_png_inputs": contract.get("logo_png_inputs") if isinstance(contract, dict) else None,
        "logo_source_groups": contract.get("logo_source_groups") if isinstance(contract, dict) else None,
        "logo_encoded_source_bytes": contract.get("logo_encoded_source_bytes") if isinstance(contract, dict) else None,
        "errors": errors,
        "status": "OK" if not errors else "INVALID",
    }


def lint_binary_sources(repo_root: str | Path) -> dict:
    root = Path(repo_root)
    offsets: set[int] = set()
    counts: dict[str, int] = {}
    assignments = load_assignments(root / "source/tables/kanji/assignments.csv", root / "source/kanji")
    for assignment in assignments:
        read_visual_txt(assignment.source)
    glyphs_by_char = {chr(int(a.unicode[2:], 16)): a for a in assignments}
    with (root / "source/tables/kanji/gameover-token-assignments.csv").open(encoding="utf-8-sig", newline="") as handle:
        for record in csv.DictReader(handle):
            assignment = glyphs_by_char.get(record["syllable"])
            if assignment is None or record["token"].replace(" ", "") != assignment.token or int(record["slot"]) != assignment.slot or int(record["rom_offset"], 16) != assignment.rom_offset:
                raise BuildError("gameover KANJI assignment disagrees with assignments.csv")
            if not _repository_file(root, record["source_document"]) or int(record["source_index"]) != assignment.index:
                raise BuildError("gameover KANJI assignment has an invalid source reference")
    glyph_tokens = {a.token: chr(int(a.unicode[2:], 16)) for a in assignments}
    for path in sorted((root / "source/tables").rglob("*raw-changes.csv")):
        component = path.relative_to(root).as_posix()
        writes = load_raw_writes(path, component)
        for write in writes:
            if write.disk_offset < 0x2B0 or write.disk_offset >= 414992:
                raise BuildError(f"raw offset is outside the disk: {component}")
            if write.disk_offset in offsets:
                raise BuildError(f"duplicate raw source offset: 0x{write.disk_offset:X}")
            offsets.add(write.disk_offset)
        counts[component] = len(writes)
        if path.parent.name == "events":
            with path.open(encoding="utf-8-sig", newline="") as handle:
                records = list(csv.DictReader(handle))
            decoded_by_address = {}
            for record in records:
                for address, decoded in zip(record["runtime_addrs"].split(), record["decoded_new_bytes"].split()):
                    decoded_by_address[int(address, 16)] = int(decoded, 16)
                char = record["char"]
                if record["kind"] == "문자" and record["byte_indices"] == "0 1" and len(char) == 1 and 0xAC00 <= ord(char) <= 0xD7A3:
                    values = record["decoded_new_bytes"].split()
                    token = f"{int(values[0], 16) & 0xF7:02X}" + values[1]
                    if glyph_tokens.get(token) != char:
                        raise BuildError(f"event character label disagrees with KANJI token: {component}, row {record['row']}")
            number = path.name.split("-")[1]
            korean_path = root / f"source/text/event-block-{number}-korean.jsonl"
            if korean_path.is_file():
                korean_records = [json.loads(line) for line in korean_path.read_text(encoding="utf-8").splitlines()]
                for record in korean_records:
                    start = int(record["runtime_range"].split("~")[0], 16)
                    for index, value in enumerate(record["token_bytes"]):
                        address = start + index
                        if address in decoded_by_address and decoded_by_address[address] != int(value, 16):
                            raise BuildError(f"Korean token disagrees with raw table: {number}, 0x{address:04X}")
                with (path.parent / f"block-{number}-audit.csv").open(encoding="utf-8-sig", newline="") as handle:
                    audit_records = list(csv.DictReader(handle))
                if len(audit_records) != len(korean_records):
                    raise BuildError(f"event audit row count differs from Korean source: {number}")
                for audit, record in zip(audit_records, korean_records):
                    if int(audit["작업순번"]) != record["ordinal"] or bytes.fromhex(audit["바이트"]) != bytes.fromhex(" ".join(record["token_bytes"])) or audit["문자열"] != record["translation"]:
                        raise BuildError(f"event audit disagrees with Korean source: {number}, row {record['ordinal']}")
    with (root / "source/tables/ending/layout.csv").open(encoding="utf-8-sig", newline="") as handle:
        ending_layout = list(csv.DictReader(handle))
    with (root / "source/tables/ending/text-basecode-tokens.csv").open(encoding="utf-8-sig", newline="") as handle:
        ending_tokens = list(csv.DictReader(handle))
    streams = {number: bytearray() for number in range(1, 25)}
    for record in ending_tokens:
        streams[int(record["segment"])].extend(bytes.fromhex(record["base_code_pair"]))
    if [int(record["segment"]) for record in ending_layout] != list(range(1, 25)):
        raise BuildError("ending layout must declare segments 1..24")
    cursor = 0
    for record in ending_layout:
        stream = streams[int(record["segment"])]
        if not stream or stream[-1] != 0x0F or len(stream) != int(record["decoded_length"]) or int(record["decoded_start_index"]) != cursor or int(record["decoded_end_index"]) != cursor + len(stream) - 1:
            raise BuildError(f"ending token/layout mismatch: {record['segment']}")
        cursor += len(stream)
    ending_stream = b"".join(streams.values())
    with (root / "source/tables/ending/raw-changes.csv").open(encoding="utf-8-sig", newline="") as handle:
        for record in csv.DictReader(handle):
            index, key = int(record["sector_local_index"], 16), int(record["sector_key"], 16) + 1
            if int(record["disk_offset"], 16) != int(record["payload_start"], 16) + 0x3FF - index:
                raise BuildError("ending source address mapping mismatch")
            for kind in ("old", "new"):
                if decode_byte(int(record[f"raw_{kind}"], 16), index, key) != int(record[f"decoded_{kind}"], 16):
                    raise BuildError("ending decoded byte disagrees with raw byte")
            global_index = int(record["global_index"])
            if not 0 <= global_index < len(ending_stream) or ending_stream[global_index] != int(record["decoded_new"], 16):
                raise BuildError("ending raw byte disagrees with the token stream")
    error_meta = _load(root / "source/tables/error07/input-provenance.json")
    if error_meta["original_d88_sha256"] != _load(root / "source/release-baseline.json")["input"]["d88_sha256"]:
        raise BuildError("ERROR 07 input hash disagrees with the release baseline")
    error_writes = load_raw_writes(root / "source/tables/error07/raw-changes.csv", "error07")
    if len(error_writes) != error_meta["write_count"] or sum(w.raw_old != w.raw_new for w in error_writes) != error_meta["reported_changed_byte_count"]:
        raise BuildError("ERROR 07 source counts disagree with the raw table")
    if not _repository_file(root, error_meta["command_source"]):
        raise BuildError("ERROR 07 command source is missing")
    asm = (root / error_meta["command_source"]).read_text(encoding="utf-8")
    commands = bytes(int(value, 16) for line in asm.splitlines() if re.match(r"\s*DB\b", line, re.I)
                     for value in re.findall(r"\b0([0-9a-f]+)h\b", line, re.I))
    if len(commands) != error_meta["command_length"]:
        raise BuildError("ERROR 07 command length disagrees with the ASM source")
    expected = commands + bytes(error_meta["tail_length"])
    raw = {write.disk_offset: write.raw_new for write in error_writes}
    start = int(error_meta["command_raw_start"], 16)
    base = int(error_meta["command_payload_start"], 16)
    correction = int(error_meta["decode_correction"], 16)
    for index, value in enumerate(expected):
        offset = start - index
        local = base + 0x3FF - offset
        if offset not in raw or not 0 <= local < 0x400 or decode_byte(raw[offset], local, correction) != value:
            raise BuildError("ERROR 07 command source disagrees with the raw table")
    hold = _load(root / "source/tables/gameover/hold-34-35.json")
    if hold.get("schema") != "valis-gameover-hold-patch/v1":
        raise BuildError("invalid hold patch schema")
    for field in ("raw_old", "raw_new", "runtime_old", "runtime_new"):
        _byte(hold.get(field), field, 0)
    local = int(hold["runtime_address"], 16) - int(hold["runtime_base"], 16)
    correction = _byte(hold["decode_correction"], "decode_correction", 0)
    if not 0 <= local < 0x400 or any(decode_byte(int(hold[f"raw_{kind}"], 16), local, correction) != int(hold[f"runtime_{kind}"], 16) for kind in ("old", "new")):
        raise BuildError("hold runtime metadata disagrees with the raw bytes")
    if not _repository_file(root, hold.get("source", {}).get("document")):
        raise BuildError("hold patch references a missing repository document")
    hold_offset = int(hold["disk_offset"], 16)
    if not 0x2B0 <= hold_offset < 414992 or hold_offset in offsets:
        raise BuildError("invalid or overlapping hold patch offset")
    for key in ("c", "h", "r", "n"):
        _byte(hold["d88_sector"].get(key), key, 0)
    offsets.add(hold_offset)
    gameover = lint_gameover_sources(root / "source")
    for component, component_offsets in gameover.items():
        for offset in component_offsets:
            if offset in offsets:
                raise BuildError(f"overlapping gameover source offset: 0x{offset:X}")
            offsets.add(offset)
    return {"glyphs": len(assignments), "raw_writes": counts, "gameover_writes": {key: len(value) for key, value in gameover.items()}, "hold_records": 1, "status": "OK"}


def lint_all(repo_root: str | Path) -> dict:
    ledger = lint_ledger(repo_root)
    manifest = lint_source_manifest(repo_root)
    release = lint_release_baseline(repo_root)
    try:
        logos = lint_logo_inputs(repo_root)
    except (BuildError, OSError, ValueError) as exc:
        logos = {"errors": [str(exc)], "status": "BLOCKED"}
    text_sources = lint_text_sources(repo_root)
    try:
        binary_sources = lint_binary_sources(repo_root)
    except (BuildError, OSError, ValueError, KeyError, TypeError) as exc:
        binary_sources = {"errors": [str(exc)], "status": "BLOCKED"}
    return {
        "ledger": ledger,
        "source_manifest": manifest,
        "release_baseline": release,
        "logo_inputs": logos,
        "text_sources": text_sources,
        "binary_sources": binary_sources,
        "status": "OK" if ledger["status"] == "OK" and manifest["buildable"] and release["status"] == "OK" and logos["status"] == "OK" and text_sources["status"] == "OK" and binary_sources["status"] == "OK" else "BLOCKED",
    }


def require_buildable(repo_root: str | Path) -> dict:
    report = lint_all(repo_root)
    if report["status"] != "OK":
        raise BuildError(
            "build is blocked: manual evidence review is incomplete; "
            "run source-lint and populate source only from reviewed literal data"
        )
    return report
