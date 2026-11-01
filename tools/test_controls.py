"""Actual ARM input tests for the ADJ-press confirm/fire binding.

Usage: python tools/test_controls.py RUNTIME_DIR
"""
import argparse
import struct
import unittest
from pathlib import Path
from elftools.elf.elffile import ELFFile
from verify import Runtime

DIRECTORY = None


class ControlsTests(unittest.TestCase):
    def setUp(self):
        if DIRECTORY is None:
            self.skipTest("Run this script with a runtime directory")
        self.p = Runtime(DIRECTORY)
        self.p.init(); self.p.tick(4)
        with (DIRECTORY / 'doom.elf').open('rb') as stream:
            elf = ELFFile(stream)
            self.symbols = {s.name: s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}

    def event_count(self):
        head = struct.unpack('<I', self.p.uc.mem_read(self.p.base + self.symbols['eventhead'], 4))[0]
        return head

    def test_adj_selects_menus_and_fires_without_ok(self):
        for _ in range(4): self.p.tap(30)
        self.p.tick(80)
        self.assertEqual(self.p.call('gr3_status', 5), 0, 'ADJ did not enter a level')
        self.assertEqual(self.p.call('gr3_status', 6), 0, 'Menu remains open')
        # Check the real game's ammo rather than just the input event queue.
        before = self.p.call('gr3_status', 9)
        self.assertGreater(before, 0)
        self.assertEqual(self.p.call('gr3_key', 30, 1), 1)
        self.p.tick(20)
        self.assertEqual(self.p.call('gr3_key', 30, 0), 1)
        after = self.p.call('gr3_status', 9)
        self.assertLess(after, before, 'ADJ did not fire the pistol')
        self.assertEqual(self.p.call('gr3_status', 4), 0)

    def test_adj_repeat_and_overlap_with_ok_do_not_release_held_confirm(self):
        self.assertEqual(self.p.call('gr3_key', 30, 1), 1)
        first = self.event_count()
        self.assertEqual(self.p.call('gr3_key', 30, 1), 1)
        self.assertEqual(self.event_count(), first, 'ADJ repeat duplicated key-down')
        self.assertEqual(self.p.call('gr3_key', 8, 1), 1)
        self.assertEqual(self.event_count(), first, 'Second confirm button duplicated key-down')
        self.assertEqual(self.p.call('gr3_key', 30, 0), 1)
        self.assertEqual(self.event_count(), first, 'ADJ release released a still-held OK')
        self.assertEqual(self.p.call('gr3_key', 8, 0), 1)
        self.assertEqual(self.event_count(), (first + 2) & 63, 'Final release must release ENTER and CTRL')
        self.assertEqual(self.p.call('gr3_status', 4), 0)

    def test_release_all_clears_both_confirm_buttons(self):
        self.p.call('gr3_key', 8, 1)
        self.assertEqual(self.p.call('gr3_key', 30, 1), 1)
        before = self.event_count()
        self.p.call('gr3_release_keys')
        self.assertEqual(self.event_count(), (before + 2) & 63)
        self.assertEqual(self.p.call('gr3_status', 4), 0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args, rest = parser.parse_known_args(); DIRECTORY = args.directory
    unittest.main(argv=['test_controls', *rest])
