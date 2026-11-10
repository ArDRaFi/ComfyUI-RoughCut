"""Tests that need no ComfyUI. Run from the repo root: python -m unittest discover tests"""

import os
import sys
import unittest
from fractions import Fraction

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from roughcut import parts  # noqa: E402

FPS = Fraction(24)

try:
    from roughcut import frames as frame_tools
except ImportError:
    frame_tools = None


class Parse(unittest.TestCase):
    def test_empty_is_whole_video(self):
        self.assertEqual(parts.parse(""), [])

    def test_valid(self):
        self.assertEqual(parts.parse('[{"start": 1, "end": 2.5}]'), [(1.0, 2.5)])

    def test_bad_json(self):
        with self.assertRaises(parts.PartsError):
            parts.parse("nope")

    def test_missing_field(self):
        with self.assertRaises(parts.PartsError):
            parts.parse('[{"start": 1}]')


class Normalize(unittest.TestCase):
    def test_empty_selects_everything(self):
        self.assertEqual(parts.normalize([], 10.0, FPS), [(0.0, 10.0)])

    def test_snaps_to_frames(self):
        result = parts.normalize([(1.01, 2.02)], 10.0, FPS)
        self.assertEqual(result, [(1.0, 2.0)])

    def test_clamps_to_video(self):
        self.assertEqual(parts.normalize([(8.0, 99.0)], 10.0, FPS), [(8.0, 10.0)])

    def test_sorted(self):
        self.assertEqual(parts.normalize([(5.0, 6.0), (1.0, 2.0)], 10.0, FPS), [(1.0, 2.0), (5.0, 6.0)])

    def test_overlap_rejected(self):
        with self.assertRaises(parts.PartsError):
            parts.normalize([(1.0, 3.0), (2.0, 4.0)], 10.0, FPS)

    def test_touching_parts_allowed(self):
        self.assertEqual(len(parts.normalize([(1.0, 2.0), (2.0, 3.0)], 10.0, FPS)), 2)

    def test_all_outside_is_error(self):
        with self.assertRaises(parts.PartsError):
            parts.normalize([(20.0, 30.0)], 10.0, FPS)

    def test_frame_count(self):
        self.assertEqual(parts.frame_count([(1.0, 3.0), (6.5, 7.5)], FPS), 72)

    def test_covers_whole(self):
        self.assertTrue(parts.covers_whole([(0.0, 10.0)], 10.0, FPS))
        self.assertFalse(parts.covers_whole([(0.0, 5.0)], 10.0, FPS))
        self.assertFalse(parts.covers_whole([(0.0, 5.0), (5.0, 10.0)], 10.0, FPS))


class Links(unittest.TestCase):
    PROMPT = {"1": {"inputs": {"file": "a.mp4"}}, "2": {"inputs": {"images": ["1", 1], "x": 3}}, "3": {"inputs": {"video": ["1", 0]}}}

    def test_found(self):
        self.assertEqual(parts.linked_outputs(self.PROMPT, "1"), {0, 1})

    def test_none_when_unknown(self):
        self.assertIsNone(parts.linked_outputs(None, "1"))
        self.assertIsNone(parts.linked_outputs({}, "1"))


@unittest.skipIf(frame_tools is None, "PyAV and friends are not installed")
class Timing(unittest.TestCase):
    def test_retime_up(self):
        self.assertEqual(frame_tools.retime_count(24, Fraction(24), Fraction(48)), 48)

    def test_retime_down(self):
        self.assertEqual(frame_tools.retime_count(48, Fraction(48), Fraction(24)), 24)

    def test_retime_keeps_order(self):
        out = list(frame_tools.retime(range(4), Fraction(2), Fraction(4)))
        self.assertEqual(out, [0, 0, 1, 1, 2, 2, 3, 3])

    def test_crossfade_is_limited_by_shortest_clip(self):
        self.assertEqual(frame_tools.crossfade_frames(10.0, FPS, [40, 100]), 20)

    def test_no_crossfade(self):
        self.assertEqual(frame_tools.crossfade_frames(0.0, FPS, [40, 100]), 0)

    def test_longest_side(self):
        self.assertEqual(frame_tools.fits_longest_side(1920, 1080, 960), (960, 540))
        self.assertEqual(frame_tools.fits_longest_side(640, 360, 960), (640, 360))

    def test_memory_guard(self):
        frame_tools.guard_memory(10, 100, 100, 10**9)
        with self.assertRaises(frame_tools.MemoryLimitError):
            frame_tools.guard_memory(100000, 1920, 1080, 8 * 2**30)


if __name__ == "__main__":
    unittest.main()
