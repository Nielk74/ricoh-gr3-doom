"""Host contracts; the ARM execution checks live in verify.py."""
import importlib.util
import struct
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('doom_build', HERE / 'build.py')
        cls.build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.build)

    def test_relocation_changes_only_declared_words(self):
        raw = struct.pack('<4I', 8, 0x12345678, 0, 12)
        result = self.build.relocate(raw, [0, 12], 0x68000000)
        self.assertEqual(struct.unpack('<4I', result),
                         (0x68000008, 0x12345678, 0, 0x6800000c))

    def test_reject_bad_relocation(self):
        for offsets in ([1], [8], [-4], [0, 0]):
            with self.subTest(offsets=offsets), self.assertRaises(ValueError):
                self.build.relocate(bytes(8), offsets, 0x68000000)

    def test_reject_truncated_or_invalid_wad(self):
        for raw in (b'', b'IWAD', struct.pack('<4sII', b'PWAD', 1, 12),
                    struct.pack('<4sII', b'IWAD', 100, 12)):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.build.validate_wad(raw)

    def test_wad_directory_must_fit(self):
        raw = struct.pack('<4sII', b'IWAD', 1, 12) + struct.pack('<II8s', 0, 0, b'E1M1')
        self.build.validate_wad(raw)
        with self.assertRaises(ValueError):
            self.build.validate_wad(raw[:-1])


if __name__ == '__main__':
    unittest.main()
