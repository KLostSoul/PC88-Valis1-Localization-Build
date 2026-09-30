from pathlib import Path
import unittest

from tools.valis_rebuild.d88 import D88Image
from tests.media_inputs import original_media


ROOT = Path(__file__).resolve().parents[1]
D88_PATH = original_media("d88")


@unittest.skipUnless(D88_PATH.exists(), "original D88 is not supplied")
class D88LayoutTests(unittest.TestCase):
    def test_original_geometry_only(self):
        image = D88Image.read(D88_PATH)
        self.assertEqual(len(image.data), 414_992)
        self.assertEqual(len(image.sectors), 422)
        self.assertEqual(len(image.flatten_payload()), 407_552)


if __name__ == "__main__":
    unittest.main()

