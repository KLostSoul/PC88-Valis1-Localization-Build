import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import re
import subprocess
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from tools.valis_rebuild import cli
from tools.valis_rebuild.d88 import D88Image
from tools.valis_rebuild.errors import BuildError
from tools.valis_rebuild.logo import (
    _read_source_map, _read_ram_map, load_binary_png_rows,
    decode_061f_planes, decode_05ce_columns,
    EncodedLogo, LogoBuildPlan, apply_logo_build,
)
from tools.valis_rebuild.source_gate import lint_all
from tools.valis_rebuild.codec import decode_byte
from tools.valis_rebuild.kanji import load_assignments
from tests.media_inputs import ROOT, original_media


ORIGINAL_D88 = original_media("d88")
ORIGINAL_ROM = original_media("rom")


def source_copy(destination):
    for folder in ("source", "analysis", "docs", "tools"):
        shutil.copytree(ROOT / folder, destination / folder, ignore=shutil.ignore_patterns("__pycache__"))


def write_binary_png(path, rows):
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    width, height = len(rows[0]) * 8, len(rows)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" +
                    chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0)) +
                    chunk(b"IDAT", zlib.compress(b"".join(b"\0" + bytes(row) for row in rows))) +
                    chunk(b"IEND", b""))


class SourceFailureTests(unittest.TestCase):
    def test_missing_logo_input_and_wrong_source_length_contract_block_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_copy(root)
            source_map = root / "source/tables/logo/source-map.csv"
            saved = source_map.read_bytes()
            with source_map.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                fields, rows = reader.fieldnames, list(reader)
            with source_map.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fields)
                writer.writeheader()
                writer.writerows(rows[:-1])
            self.assertEqual(lint_all(root)["status"], "BLOCKED")
            source_map.write_bytes(saved)
            baseline = root / "source/release-baseline.json"
            record = json.loads(baseline.read_text(encoding="utf-8"))
            record["component_contract"]["logo_encoded_source_bytes"] -= 1
            baseline.write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(lint_all(root)["status"], "BLOCKED")

    def test_hold_and_error_command_metadata_disagreement_blocks_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_copy(root)
            self.assertEqual(lint_all(root)["status"], "OK")
            for relative, field, bad in (
                ("source/tables/gameover/hold-34-35.json", "runtime_new", "31"),
                ("source/tables/error07/input-provenance.json", "command_raw_start", "0x31C7"),
            ):
                path = root / relative
                saved = path.read_bytes()
                record = json.loads(saved)
                record[field] = bad
                path.write_text(json.dumps(record), encoding="utf-8")
                self.assertEqual(lint_all(root)["status"], "BLOCKED", field)
                path.write_bytes(saved)

    def test_document_links_and_declared_repository_references_exist(self):
        for path in ROOT.rglob("*.md"):
            if any(part in {".git", "import", "output", "결과", "build"} for part in path.relative_to(ROOT).parts):
                continue
            content = path.read_text(encoding="utf-8")
            references = re.findall(r"\[[^\]]*\]\(([^)]+)\)", content)
            references += re.findall(r'<img[^>]+src="([^"]+)"', content)
            for reference in references:
                if reference.startswith(("https://", "http://", "#", "mailto:")):
                    continue
                target = (path.parent / reference.strip("<>").split("#", 1)[0]).resolve()
                self.assertTrue(target.exists(), (path, reference))
        for path in (ROOT / "source").rglob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            references = record.get("source_tables", [])
            if record.get("source_table"):
                references.append(record["source_table"])
            for reference in references:
                self.assertTrue((ROOT / reference).is_file(), (path, reference))

    def test_local_media_and_outputs_are_ignored_in_all_suffix_casings(self):
        paths = ["fixture.d88", "fixture.D88", "fixture.rOm", "fixture.RoM", "fixture.IpS",
                 "fixture.zIp", "fixture.BIN", "import/fixture", "output/fixture", "결과/fixture"]
        result = subprocess.run(["git", "-c", "core.quotepath=false", "check-ignore", "--stdin"],
                                input=("\n".join(paths) + "\n").encode("utf-8"),
                                cwd=ROOT, capture_output=True, check=True)
        self.assertEqual(set(result.stdout.decode("utf-8").splitlines()), set(paths))

    def test_kanji_out_of_range_slot_escaping_path_and_inconsistent_token_are_rejected(self):
        with (ROOT / "source/tables/kanji/assignments.csv").open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields, rows = reader.fieldnames, list(reader)
        for changes in ({"slot": "4096", "rom_offset": "0x20000"},
                        {"source": "../outside.txt"}, {"token": "A018"}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "assignments.csv"
                changed = [dict(row) for row in rows]
                changed[0].update(changes)
                with path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fields)
                    writer.writeheader()
                    writer.writerows(changed)
                with self.assertRaises(BuildError):
                    load_assignments(path, ROOT / "source/kanji")

    def test_unconfirmed_evidence_missing_reference_and_bad_raw_arrays_are_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_copy(root)
            ledger_path = root / "analysis/evidence-ledger.json"
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            ledger["facts"][0]["status"] = "conflict"
            ledger["facts"][0]["source_documents"] = ["missing.md"]
            ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
            raw = root / "source/tables/events/block-1-raw-changes.csv"
            raw.write_text(raw.read_text(encoding="utf-8").replace("AC 57,2C 31", "AC,2C 31", 1), encoding="utf-8")
            report = lint_all(root)
            self.assertEqual(report["status"], "BLOCKED")
            self.assertEqual(report["ledger"]["status"], "INVALID")
            self.assertEqual(report["binary_sources"]["status"], "BLOCKED")
            with patch.object(cli, "repo_root", return_value=root), patch("sys.stderr"):
                with self.assertRaises(SystemExit) as raised:
                    cli.main(["source-lint"])
            self.assertEqual(raised.exception.code, 2)

    def test_invalid_glyph_is_detected_before_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_copy(root)
            glyph = next((root / "source/kanji").glob("*.txt"))
            glyph.write_text("invalid bitmap", encoding="utf-8")
            self.assertEqual(lint_all(root)["binary_sources"]["status"], "BLOCKED")

    def test_png_missing_iend_and_column_overflow_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "fixture.png"
            write_binary_png(image, [[0]])
            image.write_bytes(image.read_bytes()[:-12])
            with self.assertRaises(BuildError):
                load_binary_png_rows(image, 8, 1, 1)
        with self.assertRaises(BuildError):
            decode_05ce_columns(bytes([5, 2, 0, 255]), 1, 2)


@unittest.skipUnless(ORIGINAL_D88.is_file() and ORIGINAL_ROM.is_file(), "original media is not supplied")
class MediaContractTests(unittest.TestCase):
    def test_logo_sector_mapping_must_match_actual_original_sector(self):
        group = _read_source_map(ROOT)[0]
        row = _read_ram_map(ROOT)[group.base]
        logo = EncodedLogo("sector-check", group.base, bytes([int(row["stored_byte"], 16)]), "061F", (), "png_encoded")
        original = ORIGINAL_D88.read_bytes()
        valid = apply_logo_build(D88Image.parse(original), LogoBuildPlan((logo,), {group.base: row}))
        self.assertEqual(valid["writes"], 1)
        for field in ("d88_c", "d88_h", "d88_r", "sector_raw_base", "raw_index"):
            corrupted = dict(row)
            corrupted[field] = f"{int(row[field], 16) + 1:X}"
            with self.subTest(field=field), self.assertRaisesRegex(BuildError, "disagrees with D88 sector"):
                apply_logo_build(D88Image.parse(original), LogoBuildPlan((logo,), {group.base: corrupted}))

    def test_combined_build_cannot_overwrite_original_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            disk, rom = output / "valis_disk_a(K).d88", output / "KANJI1(K).ROM"
            shutil.copyfile(ORIGINAL_D88, disk)
            shutil.copyfile(ORIGINAL_ROM, rom)
            with self.assertRaises(BuildError):
                cli.command_build(argparse.Namespace(d88=str(disk), rom=str(rom), out=str(output)))
            self.assertEqual(disk.read_bytes(), ORIGINAL_D88.read_bytes())
            self.assertEqual(rom.read_bytes(), ORIGINAL_ROM.read_bytes())

    def test_failed_publication_rolls_back_first_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output, staging = root / "output", root / "staging"
            output.mkdir()
            staging.mkdir()
            reports = []
            for filename in ("disk.d88", "kanji.rom"):
                (output / filename).write_bytes(b"previous")
                (staging / filename).write_bytes(b"new")
                reports.append({"output": {"path": str(staging / filename)}})
            replace = Path.replace
            def fail_second(path, target):
                if path == staging / "kanji.rom":
                    raise PermissionError("simulated locked output")
                return replace(path, target)
            with patch.object(Path, "replace", fail_second):
                with self.assertRaises(PermissionError):
                    cli._publish_outputs(tuple(reports), output, set())
            self.assertTrue(all(path.read_bytes() == b"previous" for path in output.iterdir()))

    def test_original_resolution_uses_contents_and_accepts_identical_copies(self):
        with tempfile.TemporaryDirectory(prefix="final-") as directory:
            root = Path(directory)
            first = root / "completed.data"
            shutil.copyfile(ORIGINAL_D88, first)
            shutil.copyfile(first, root / "duplicate.unknown")
            data = first.read_bytes()
            selected = cli._resolve_hashed_input(root, expected_hash=hashlib.sha256(data).hexdigest(),
                                                  expected_size=len(data), label="D88", suffix=".d88")
            self.assertEqual(selected.read_bytes(), data)

    def test_corrupt_d88_header_and_duplicate_component_write_are_rejected(self):
        data = ORIGINAL_D88.read_bytes()
        for offset, replacement in ((0x1C, 1), (0x24, int.from_bytes(data[0x20:0x24], "little"))):
            corrupt = bytearray(data)
            struct.pack_into("<I", corrupt, offset, replacement)
            with self.assertRaises(BuildError):
                D88Image.parse(corrupt)
        image = D88Image.parse(data)
        offset = image.sectors[0].data_offset
        image.write_data(offset, b"\0")
        with self.assertRaises(BuildError):
            image.write_data(offset, b"\0")

    def test_failed_combined_build_preserves_previous_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            output.mkdir()
            for filename in ("valis_disk_a(K).d88", "KANJI1(K).ROM"):
                (output / filename).write_bytes(b"previous output")
            args = argparse.Namespace(d88=str(ORIGINAL_D88), rom=str(ORIGINAL_ROM), out=str(output))
            with patch.object(cli, "build_kanji", side_effect=BuildError("ROM failure")):
                with self.assertRaises(BuildError):
                    cli.command_build(args)
            self.assertTrue(all(path.read_bytes() == b"previous output" for path in output.iterdir()))
            self.assertEqual(list(output.parent.iterdir()), [output])

    def test_verify_rejects_corrupted_disk_and_rom_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            build_args = argparse.Namespace(d88=str(ORIGINAL_D88), rom=str(ORIGINAL_ROM), out=str(output))
            result = cli.command_build(build_args)
            disk = Path(result["d88"]["output"]["path"])
            rom = Path(result["kanji1"]["output"]["path"])
            args = argparse.Namespace(d88=str(disk), rom=str(rom), original_d88=str(ORIGINAL_D88),
                                      original_rom=str(ORIGINAL_ROM), report=None)
            self.assertTrue(cli.command_verify(args)["matches_current_source"])
            original = disk.read_bytes()
            corrupt = bytearray(original)
            corrupt[D88Image.parse(original).sectors[0].data_offset] ^= 1
            disk.write_bytes(corrupt)
            with self.assertRaises(BuildError):
                cli.command_verify(args)
            disk.write_bytes(original)
            corrupt = bytearray(rom.read_bytes())
            corrupt[0] ^= 1
            rom.write_bytes(corrupt)
            with self.assertRaises(BuildError):
                cli.command_verify(args)

    def test_all_korean_event_tokens_match_decoded_output(self):
        from tools.valis_rebuild.pipeline import build_disk
        with tempfile.TemporaryDirectory() as directory:
            result = build_disk(ROOT, ORIGINAL_D88, Path(directory))
            built = Path(result["output"]["path"]).read_bytes()
            for number in range(2, 7):
                maps = {}
                with (ROOT / f"source/tables/events/block-{number}-raw-changes.csv").open(encoding="utf-8-sig") as handle:
                    for row in csv.DictReader(handle):
                        for address, index, base, key in zip(row["runtime_addrs"].split(), row["segment_indices"].split(),
                                                             row["payload_starts"].split(), row["decode_keys"].split()):
                            maps[int(address, 16) - int(index, 16)] = (int(base, 16), int(key, 16) + 1)
                records = [json.loads(line) for line in (ROOT / f"source/text/event-block-{number}-korean.jsonl").read_text(encoding="utf-8").splitlines()]
                for record in records:
                    start = int(record["runtime_range"].split("~")[0], 16)
                    for index, value in enumerate(record["token_bytes"]):
                        address = start + index
                        matches = [(base, payload, key) for base, (payload, key) in maps.items() if base <= address < base + 0x400]
                        self.assertEqual(len(matches), 1)
                        base, payload, key = matches[0]
                        local = address - base
                        actual = decode_byte(built[payload + 0x3FF - local], local, key)
                        self.assertEqual(actual, int(value, 16), (number, record["ordinal"], address))

    def test_every_logo_png_edit_builds_and_roundtrips_from_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_copy(root)
            with patch.object(cli, "repo_root", return_value=root):
                baseline_result = cli.command_build(argparse.Namespace(
                    d88=str(ORIGINAL_D88), rom=str(ORIGINAL_ROM), out=str(root / "output")))
            baseline = Path(baseline_result["d88"]["output"]["path"]).read_bytes()
            groups = _read_source_map(root)
            ram_map = _read_ram_map(root)
            saved_images = {}
            edited_rows = {}
            try:
                for group in groups:
                    for image in group.images:
                        saved_images[image.path] = image.path.read_bytes()
                        rows = load_binary_png_rows(image.path, group.width_pixels, group.height, group.width_bytes)
                        rows[0][0] ^= 0x80 >> (len(saved_images) - 1)
                        edited_rows[image.target] = rows
                        write_binary_png(image.path, rows)
                with patch.object(cli, "repo_root", return_value=root):
                    result = cli.command_build(argparse.Namespace(
                        d88=str(ORIGINAL_D88), rom=str(ORIGINAL_ROM), out=str(root / "output")))
                self.assertEqual(result["status"], "OK")
                self.assertFalse(result["d88"]["exact_release_match"])
                built = Path(result["d88"]["output"]["path"]).read_bytes()
                allowed = set()
                for group in groups:
                    encoded = bytearray()
                    for address in range(group.base, group.base + group.length):
                        mapping = ram_map[address]
                        offset = int(mapping["raw_file_offset"], 16)
                        allowed.add(offset)
                        de = 0x400 - int(mapping["raw_index"], 16)
                        encoded.append((built[offset] - (de >> 8) - (de & 255) +
                                        0x40 - int(mapping["d88_c"], 16)) & 255)
                    if group.encoder == "061F":
                        actual = decode_061f_planes(bytes(encoded), group.width_bytes, group.height,
                                                    tuple(item.plane for item in group.images))
                        for image in group.images:
                            self.assertEqual(actual[image.plane], edited_rows[image.target])
                    else:
                        actual = decode_05ce_columns(bytes(encoded), group.width_bytes, group.height)
                        self.assertEqual(actual, edited_rows[group.images[0].target])
                self.assertTrue({i for i, (a, b) in enumerate(zip(baseline, built)) if a != b} <= allowed)
                with patch.object(cli, "repo_root", return_value=root):
                    verified = cli.command_verify(argparse.Namespace(
                        d88=str(root / "output"), rom=str(root / "output"),
                        original_d88=str(ORIGINAL_D88), original_rom=str(ORIGINAL_ROM), report=None))
                self.assertTrue(verified["matches_current_source"])
                self.assertEqual(len(list((root / "output").iterdir())), 4)
            finally:
                for path, content in saved_images.items():
                    path.write_bytes(content)


if __name__ == "__main__":
    unittest.main()
