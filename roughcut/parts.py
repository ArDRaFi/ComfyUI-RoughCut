"""The parts of a video chosen on the timeline. No ComfyUI imports, so it is easy to test."""

from __future__ import annotations

import json
from fractions import Fraction


class PartsError(ValueError):
    pass


def parse(text: str) -> list[tuple[float, float]]:
    """Read the timeline's JSON. Empty text means the whole video."""
    text = (text or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError as e:
        raise PartsError(f"The parts list is not valid JSON: {e}") from e
    if not isinstance(data, list):
        raise PartsError('Parts must be a list, such as [{"start": 1.0, "end": 2.5}].')
    out: list[tuple[float, float]] = []
    for item in data:
        try:
            out.append((float(item["start"]), float(item["end"])))
        except (TypeError, KeyError, ValueError) as e:
            raise PartsError('Each part needs a number "start" and "end".') from e
    return out


def _snap(seconds: float, fps: Fraction) -> Fraction:
    return Fraction(round(Fraction(seconds) * fps)) / fps


def normalize(parts: list[tuple[float, float]], duration: float, fps: Fraction) -> list[tuple[float, float]]:
    """Clamp to the video, snap to whole frames and sort. Overlapping parts are an error,
    because they would silently repeat footage."""
    total_frames = max(1, round(Fraction(duration) * fps))
    end_of_video = Fraction(total_frames) / fps
    if not parts:
        return [(0.0, float(end_of_video))]

    snapped: list[tuple[Fraction, Fraction]] = []
    for start, end in parts:
        a = max(Fraction(0), _snap(start, fps))
        b = min(end_of_video, _snap(end, fps))
        if b > a:
            snapped.append((a, b))
    if not snapped:
        raise PartsError("None of the parts fall inside this video.")
    snapped.sort()
    for (_, previous_end), (next_start, _) in zip(snapped, snapped[1:], strict=False):
        if next_start < previous_end:
            raise PartsError("Parts overlap. Adjust them on the timeline so that each covers its own section.")
    return [(float(a), float(b)) for a, b in snapped]


def covers_whole(parts: list[tuple[float, float]], duration: float, fps: Fraction) -> bool:
    """True when the selection is simply the entire video."""
    if len(parts) != 1:
        return False
    half_frame = float(Fraction(1, 2) / fps)
    return parts[0][0] <= half_frame and parts[0][1] >= duration - half_frame


def frame_count(parts: list[tuple[float, float]], fps: Fraction) -> int:
    return sum(round(Fraction(end - start) * fps) for start, end in parts)


def linked_outputs(prompt: dict | None, node_id: str | None) -> set[int] | None:
    """Which output indexes of a node are connected. None means it could not be determined."""
    if not prompt or node_id is None:
        return None
    used: set[int] = set()
    for node in prompt.values():
        for value in (node.get("inputs") or {}).values():
            if isinstance(value, (list, tuple)) and len(value) == 2 and str(value[0]) == str(node_id):
                used.add(int(value[1]))
    return used
