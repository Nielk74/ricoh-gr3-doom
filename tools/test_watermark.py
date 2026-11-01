"""Check the small fixed watermark in pixels rendered by the actual ARM game."""
import argparse
import unittest
from pathlib import Path
from verify import Runtime

DIRECTORY = None
# The seven 5x7 glyphs spell Nielk74, with a single pixel between characters.
GLYPHS = (
    (17, 25, 25, 21, 19, 19, 17),
    (4, 0, 12, 4, 4, 4, 14),
    (0, 0, 14, 17, 31, 16, 14),
    (12, 4, 4, 4, 4, 4, 14),
    (16, 16, 18, 20, 24, 20, 18),
    (31, 1, 2, 4, 8, 8, 8),
    (2, 6, 10, 18, 31, 2, 2),
)


class WatermarkTests(unittest.TestCase):
    def test_fixed_small_mark_on_title_and_gameplay_at_both_pitches(self):
        if DIRECTORY is None:
            self.skipTest('Run this script with a runtime directory')
        p = Runtime(DIRECTORY); p.init(); p.tick(4)
        ink = {(632 + c * 6 + x, 8 + y)
               for c, glyph in enumerate(GLYPHS) for y, row in enumerate(glyph)
               for x in range(5) if row & (16 >> x)}
        outline = {(x + dx, y + dy) for x, y in ink
                   for dx in (-1, 0, 1) for dy in (-1, 0, 1)} - ink

        def check_frame():
            image = p.frame(736)  # Also checks all padding and memory canaries.
            self.assertEqual(p.frame(720), image)
            for points, color in ((ink, b'\xff\xff\xff\xff'),
                                  (outline, b'\0\0\0\xff')):
                for x, y in points:
                    at = (y * 720 + x) * 4
                    self.assertEqual(image[at:at + 4], color,
                                     f'Wrong watermark pixel at {x},{y}')
            return image

        title = check_frame()
        for _ in range(4): p.tap(30)
        p.tick(80)
        self.assertEqual(p.call('gr3_status', 5), 0, 'Did not enter a level')
        self.assertNotEqual(check_frame(), title)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args, rest = parser.parse_known_args(); DIRECTORY = args.directory
    unittest.main(argv=['test_watermark', *rest])
