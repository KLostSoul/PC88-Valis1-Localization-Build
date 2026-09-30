import json
import csv
import tempfile
from pathlib import Path
import unittest

from tools.valis_rebuild.kanji import build_rom, load_assignments
from tools.valis_rebuild.pipeline import build_disk, build_kanji
from tools.valis_rebuild.text_sources import lint_text_sources


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_ROM = ROOT.parent / "upload" / "KANJI1(5).ROM"
ORIGINAL_D88 = ROOT.parent / "upload" / "Mugen Senshi Valis (1986)(Nihon Telenet)(Disk 1 of 2)(1).d88"


class SourceComponentTests(unittest.TestCase):
    def test_original_and_korean_event_tables_are_separate_literal_sources(self):
        original = ROOT / "source/text/event-block-2.jsonl"
        korean = ROOT / "source/text/event-block-2-korean.jsonl"
        original_rows = [json.loads(line) for line in original.read_text(encoding="utf-8").splitlines()]
        korean_rows = [json.loads(line) for line in korean.read_text(encoding="utf-8").splitlines()]
        self.assertGreater(len(original_rows), 0)
        self.assertEqual(len(korean_rows), 1653)
        self.assertTrue(all("original" in row and "translation" in row for row in original_rows))
        self.assertTrue(all("token_bytes" in row and "translation" in row for row in korean_rows))

    @unittest.skipUnless(ORIGINAL_ROM.exists(), "original KANJI1 is not supplied")
    def test_explicit_kanji_source_reproduces_known_rom_hash(self):
        assignments = load_assignments(
            ROOT / "source/tables/kanji/assignments.csv",
            ROOT / "source/kanji",
        )
        output, _ = build_rom(ORIGINAL_ROM.read_bytes(), assignments)
        self.assertEqual(
            __import__("hashlib").sha256(output).hexdigest(),
            "6856eed33acac7f5930231d6ffab735a6aeaa700aabc22961e15e340b21ea72a",
        )

    def test_text_source_index_has_original_translation_and_all_segment_sets(self):
        report = lint_text_sources(ROOT)
        self.assertEqual(report["status"], "OK", report)
        ending = [json.loads(line) for line in (ROOT / "source/text/ending-24.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["segment"] for row in ending], list(range(1, 25)))
        self.assertTrue(all(row["original"] and row["translation"] for row in ending))

    def test_literal_raw_tables_have_expected_counts_and_unique_offsets(self):
        expected = {1: 1449, 2: 3536, 3: 1934, 4: 1701, 5: 2848, 6: 817}
        for block, count in expected.items():
            path = ROOT / f"source/tables/events/block-{block}-raw-changes.csv"
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            offsets = []
            for row in rows:
                row_offsets = row["disk_offsets"].split()
                old_values = row["raw_old_bytes"].split()
                new_values = row["raw_new_bytes"].split()
                self.assertTrue(row_offsets)
                self.assertEqual(len(row_offsets), len(old_values))
                self.assertEqual(len(row_offsets), len(new_values))
                offsets.extend(row_offsets)
            self.assertEqual(len(offsets), count)
            self.assertEqual(len(offsets), len(set(offsets)))

    def test_logo_source_map_points_to_supplied_png_layers(self):
        source_map = ROOT / "source/tables/logo/source-map.csv"
        with source_map.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 6)
        for row in rows:
            path = ROOT / "source/tables/logo" / row["edit_png"]
            self.assertTrue(path.is_file(), path)
            self.assertEqual(path.suffix.lower(), ".png")

    @unittest.skipUnless(ORIGINAL_D88.exists() and ORIGINAL_ROM.exists(), "original media is not supplied")
    def test_integrated_build_from_original_media(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            disk = build_disk(ROOT, ORIGINAL_D88, output / "d88")
            kanji = build_kanji(ROOT, ORIGINAL_ROM, output / "kanji")
            self.assertEqual(disk["structure"], {"sectors": 422, "flat_payload": 407552})
            self.assertTrue(disk["exact_release_match"])
            self.assertEqual(
                disk["output"]["sha256"],
                "18e274dc730902f90e4d3939ad3ac2853c927d19baf896cee88e5b22321427b8",
            )
            self.assertEqual(disk["output"]["path"], str(output / "d88" / "valis_disk_a(K).d88"))
            self.assertTrue(kanji["exact_release_match"])
            self.assertEqual(kanji["output"]["sha256"], "6856eed33acac7f5930231d6ffab735a6aeaa700aabc22961e15e340b21ea72a")
            self.assertEqual(kanji["output"]["path"], str(output / "kanji" / "KANJI1(K).ROM"))


if __name__ == "__main__":
    unittest.main()
