"""Exact-range frame decoding, retiming and fitting frames to a new size."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from fractions import Fraction

import av
import numpy as np
from PIL import Image

from .probe import rotation_quarters, stream_fps

try:
    from comfy.model_management import throw_exception_if_processing_interrupted as check_interrupt
except ImportError:  # running outside ComfyUI (unit tests)

    def check_interrupt() -> None:
        return None


class MemoryLimitError(RuntimeError):
    pass


@dataclass(frozen=True)
class Source:
    """A video file and the window of it to use. A duration of 0 means to the end."""

    path: str
    start: float = 0.0
    duration: float = 0.0


def fits_longest_side(width: int, height: int, longest: int) -> tuple[int, int]:
    if longest <= 0 or max(width, height) <= longest:
        return width, height
    scale = longest / max(width, height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def iter_frames(source: Source, every: int = 1, max_frames: int = 0, longest: int = 0) -> Iterator[np.ndarray]:
    """Yield H x W x 3 uint8 RGB frames from exactly the requested window."""
    with av.open(source.path) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        origin = stream.start_time or 0
        half_frame = float(Fraction(1, 2) / stream_fps(stream))
        end = source.start + source.duration if source.duration else float("inf")
        if source.start > 0:
            container.seek(origin + int(source.start / stream.time_base), stream=stream, backward=True)
        seen = kept = 0
        for frame in container.decode(stream):
            check_interrupt()
            if frame.pts is not None:
                t = float((frame.pts - origin) * stream.time_base)
                if t < source.start - half_frame:
                    continue
                if t >= end - half_frame:
                    break
            if seen % every == 0:
                turns = rotation_quarters(frame)
                width, height = fits_longest_side(frame.width, frame.height, longest)
                if (width, height) != (frame.width, frame.height):
                    frame = frame.reformat(width=width, height=height)
                array = frame.to_ndarray(format="rgb24")
                yield np.rot90(array, k=turns, axes=(0, 1)).copy() if turns else array
                kept += 1
                if max_frames and kept >= max_frames:
                    break
            seen += 1


def retime(frames: Iterable, source_rate: Fraction, target_rate: Fraction) -> Iterator:
    """Repeat or drop frames to convert between frame rates."""
    produced = 0
    for index, frame in enumerate(frames):
        end_of_frame = Fraction(index + 1) / source_rate
        while Fraction(produced) / target_rate < end_of_frame:
            yield frame
            produced += 1


def retime_count(frames: int, source_rate: Fraction, target_rate: Fraction) -> int:
    return sum(1 for _ in retime(range(frames), source_rate, target_rate))


def fit_frame(frame: np.ndarray, width: int, height: int, mode: str) -> np.ndarray:
    """Make a frame exactly width x height. Mode is pad, crop or stretch."""
    source_height, source_width = frame.shape[:2]
    if (source_width, source_height) == (width, height):
        return frame
    picture = Image.fromarray(frame)
    if mode == "stretch":
        return np.asarray(picture.resize((width, height), Image.Resampling.BICUBIC))
    scale = (max if mode == "crop" else min)(width / source_width, height / source_height)
    scaled = picture.resize((max(1, round(source_width * scale)), max(1, round(source_height * scale))), Image.Resampling.BICUBIC)
    if mode == "crop":
        left, top = (scaled.width - width) // 2, (scaled.height - height) // 2
        return np.asarray(scaled.crop((left, top, left + width, top + height)))
    canvas = Image.new("RGB", (width, height))
    canvas.paste(scaled, ((width - scaled.width) // 2, (height - scaled.height) // 2))
    return np.asarray(canvas)


def crossfade_frames(requested_seconds: float, fps: Fraction, clip_frames: list[int]) -> int:
    """Overlap in frames, limited so each clip keeps some footage of its own."""
    if requested_seconds <= 0 or len(clip_frames) < 2:
        return 0
    return max(0, min(round(Fraction(requested_seconds) * fps), min(clip_frames) // 2))


def image_bytes(frames: int, width: int, height: int) -> int:
    """Memory an IMAGE batch needs, as 32-bit floats."""
    return frames * width * height * 3 * 4


def guard_memory(frames: int, width: int, height: int, available: int) -> None:
    needed = image_bytes(frames, width, height)
    if needed > available * 0.85:
        raise MemoryLimitError(
            f"Decoding {frames} frames at {width}x{height} needs about {needed / 2**30:.1f} GB, "
            f"but only {available / 2**30:.1f} GB is free. Use RC Video to Images with every Nth, max frames or longest side."
        )


def decode_images(sources: list[Source], width: int, height: int, expected: int, every: int = 1, max_frames: int = 0, longest: int = 0):
    """Decode to one IMAGE batch without holding a second copy in memory."""
    import psutil
    import torch

    target_width, target_height = fits_longest_side(width, height, longest)
    count = max(1, expected // every + 1)
    if max_frames:
        count = min(count, max_frames)
    guard_memory(count, target_width, target_height, psutil.virtual_memory().available)

    batch = torch.zeros((count, target_height, target_width, 3), dtype=torch.float32)
    filled = 0
    done = False
    for source in sources:
        remaining = max_frames - filled if max_frames else 0
        for frame in iter_frames(source, every, remaining, longest):
            if filled >= batch.shape[0]:  # the estimate was short
                batch = torch.cat([batch, torch.zeros((16, target_height, target_width, 3), dtype=torch.float32)])
            batch[filled] = torch.from_numpy(frame.astype(np.float32) / 255.0)
            filled += 1
        if max_frames and filled >= max_frames:
            done = True
        if done:
            break
    if filled == 0:
        raise ValueError("No frames found in the selected range.")
    return batch[:filled]
