import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from tools.valis_rebuild.errors import BuildError
from tools.valis_rebuild.cli import _verify_ips
from tools.valis_rebuild.ips import apply_ips, encode_ips
from tools.valis_rebuild.outputs import publish_outputs
from tools.valis_rebuild.pipeline import _write_build_outputs


class IpsTests(unittest.TestCase):
    def test_known_standard_record_bytes(self):
        source = b"abcdef"
        target = b"aXYdeZ"
        expected = b"PATCH\x00\x00\x01\x00\x02XY\x00\x00\x05\x00\x01ZEOF"
        self.assertEqual(encode_ips(source, target), expected)
        self.assertEqual(apply_ips(source, expected), target)
        self.assertEqual(encode_ips(source, source), b"PATCHEOF")

    def test_long_run_is_split_at_record_limit(self):
        source = bytes(65536)
        target = b"x" * len(source)
        encoded = encode_ips(source, target)
        self.assertEqual(encoded[5:10], b"\x00\x00\x00\xff\xff")
        self.assertEqual(encoded[65545:65550], b"\x00\xff\xff\x00\x01")
        self.assertEqual(apply_ips(source, encoded), target)

    def test_unrepresentable_inputs_are_rejected(self):
        with self.assertRaises(BuildError):
            encode_ips(b"x", b"xx")
        oversized = bytes(0x1000001)
        with self.assertRaises(BuildError):
            encode_ips(oversized, oversized)
        source = bytes(0x454F47)
        target = source[:-1] + b"x"
        with self.assertRaisesRegex(BuildError, "EOF"):
            encode_ips(source, target)

    def test_malformed_records_are_rejected(self):
        invalid = (
            b"BAD", b"PATCH", b"PATCHEOFx", b"PATCH\x00\x00\x00",
            b"PATCH\x00\x00\x00\x00\x08xEOF",
            b"PATCH\x00\x00\x02\x00\x01xEOF",
        )
        for record in invalid:
            with self.subTest(record=record), self.assertRaises(BuildError):
                apply_ips(b"ab", record)


class ArtifactFailureTests(unittest.TestCase):
    def test_verification_rejects_stale_missing_and_truncated_patches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, image, ips = root / "original", root / "disk.d88", root / "disk.ips"
            source.write_bytes(b"abc")
            image.write_bytes(b"aXc")
            ips.write_bytes(b"PATCH\x00\x00\x01\x00\x01XEOF")
            self.assertTrue(_verify_ips(image, source, required=True)["reapplied_matches_output"])
            for invalid in (b"PATCHEOF", ips.read_bytes()[:-1]):
                ips.write_bytes(invalid)
                with self.assertRaises(BuildError):
                    _verify_ips(image, source, required=True)
            ips.unlink()
            with self.assertRaises(BuildError):
                _verify_ips(image, source, required=True)
            self.assertIsNone(_verify_ips(image, source, required=False))

    def test_single_build_restores_image_when_ips_is_locked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "original"
            source.write_bytes(b"abc")
            output = root / "output"
            output.mkdir()
            image, ips = output / "disk.d88", output / "disk.ips"
            image.write_bytes(b"previous image")
            ips.write_bytes(b"previous patch")
            replace = Path.replace

            def fail_patch(path, target):
                if path.name == "disk.ips" and path.parent != output:
                    raise PermissionError("locked patch")
                return replace(path, target)

            with patch.object(Path, "replace", fail_patch), self.assertRaises(PermissionError):
                _write_build_outputs(image, b"abc", b"aXc", source)
            self.assertEqual(image.read_bytes(), b"previous image")
            self.assertEqual(ips.read_bytes(), b"previous patch")
            self.assertEqual(set(root.iterdir()), {source, output})

    def test_all_four_outputs_restore_on_each_publication_failure(self):
        names = ("disk.d88", "disk.ips", "kanji.rom", "kanji.ips")
        for existing in (False, True):
            for failed in names:
                with self.subTest(failed=failed, existing=existing), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    output, staging = root / "output", root / "staging"
                    output.mkdir()
                    staging.mkdir()
                    for name in names:
                        if existing:
                            (output / name).write_bytes(b"previous")
                        (staging / name).write_bytes(b"new")
                    reports = tuple({"output": {"path": str(staging / names[i])},
                                     "ips": {"path": str(staging / names[i + 1])}} for i in (0, 2))
                    replace = Path.replace

                    def fail_one(path, target):
                        if path == staging / failed:
                            raise PermissionError("locked output")
                        return replace(path, target)

                    with patch.object(Path, "replace", fail_one), self.assertRaises(PermissionError):
                        publish_outputs(reports, output, set())
                    self.assertEqual({p.name: p.read_bytes() for p in output.iterdir()},
                                     {name: b"previous" for name in names} if existing else {})


if __name__ == "__main__":
    unittest.main()
