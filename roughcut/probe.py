"""Reads basic facts about a video file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from fractions import Fraction

import av

_BROWSER_CODECS = {"h264", "vp8", "vp9", "av1"}
_BROWSER_EXTENSIONS = {".mp4", ".m4v", ".mov", ".webm"}  # MKV shares WebM's demuxer name


@dataclass(frozen=True)
class VideoFacts:
    width: int
    height: int
    fps: Fraction
    frames: int
    duration: float
    has_audio: bool
    browser_playable: bool


def stream_fps(stream) -> Fraction:
    rate = stream.average_rate or stream.guessed_rate or stream.base_rate
    return Fraction(rate) if rate else Fraction(24)


def rotation_quarters(frame) -> int:
    """Number of quarter turns stored in a frame, as phones record it."""
    rotation = getattr(frame, "rotation", 0)
    return int(round(rotation // 90)) % 4 if rotation else 0


def _duration_from_last_packets(container, stream, fps: Fraction) -> float:
    """Containers like MKV only give an overall length, which audio padding can stretch.
    Read the last video packets instead, which needs no full scan of the file."""
    if container.duration is None:
        return 0.0
    overall = container.duration / av.time_base
    origin = stream.start_time or 0
    target = origin + int(max(overall - 5.0, 0.0) / stream.time_base)
    container.seek(target, stream=stream, backward=True)
    last = None
    for packet in container.demux(stream):
        if packet.pts is not None and (last is None or packet.pts > last):
            last = packet.pts
    if last is None:
        return overall
    return float((last - origin) * stream.time_base + Fraction(1) / fps)


def probe(path: str) -> VideoFacts:
    with av.open(path) as container:
        if not container.streams.video:
            raise ValueError("This file has no video stream.")
        stream = container.streams.video[0]
        fps = stream_fps(stream)
        if stream.duration is not None and stream.time_base is not None:
            duration = float(stream.duration * stream.time_base)
        else:
            duration = _duration_from_last_packets(container, stream, fps)
        frames = stream.frames or round(duration * fps)
        container.seek(0)
        width, height = stream.codec_context.width, stream.codec_context.height
        first = next(container.decode(stream), None)
        if first is not None and rotation_quarters(first) % 2:
            width, height = height, width
        playable = stream.codec.canonical_name in _BROWSER_CODECS and os.path.splitext(path)[1].lower() in _BROWSER_EXTENSIONS
        if frames and not duration:
            duration = float(Fraction(frames) / fps)
        return VideoFacts(width, height, fps, int(frames), duration, bool(container.streams.audio), playable)
