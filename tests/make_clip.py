"""Synthetic test media. Every frame carries its own index as black and white blocks,
so tests can prove exactly which frames survived an edit."""

import fractions
import sys

import av
import numpy as np

BITS = 12
BLOCK = 16


def encode_index(index: int, width: int, height: int, background: int = 90) -> np.ndarray:
    frame = np.full((height, width, 3), background, dtype=np.uint8)
    for bit in range(BITS):
        value = 255 if (index >> bit) & 1 else 0
        frame[0:BLOCK, bit * BLOCK : (bit + 1) * BLOCK] = value
    return frame


def read_index(frame: np.ndarray, scale: float = 1.0) -> int:
    """Read a frame's index from an H x W x 3 uint8 array. `scale` is for resized frames."""
    index = 0
    for bit in range(BITS):
        if frame[int(BLOCK / 2 * scale), int((bit + 0.5) * BLOCK * scale)].mean() > 127:
            index |= 1 << bit
    return index


def make_clip(path: str, frames: int = 240, fps: int = 24, width: int = 320, height: int = 180, gop: int = 48, audio: bool = True, tone: float = 440.0, start: int = 0) -> None:
    with av.open(path, "w") as container:
        stream = container.add_stream("libx264", rate=fps)
        stream.width, stream.height, stream.pix_fmt = width, height, "yuv420p"
        stream.gop_size = gop
        stream.options = {"crf": "10", "bf": "2", "preset": "veryfast"}
        stream.time_base = fractions.Fraction(1, fps)
        audio_stream = container.add_stream("aac", rate=48000, layout="mono") if audio else None
        for index in range(frames):
            frame = av.VideoFrame.from_ndarray(encode_index(start + index, width, height), format="rgb24")
            frame.pts = index
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
        if audio_stream is not None:
            total = int(48000 * frames / fps)
            samples = (0.3 * np.sin(2 * np.pi * tone * np.arange(total) / 48000)).astype(np.float32).reshape(1, -1)
            frame = av.AudioFrame.from_ndarray(samples, format="fltp", layout="mono")
            frame.sample_rate = 48000
            for packet in audio_stream.encode(frame):
                container.mux(packet)
            for packet in audio_stream.encode(None):
                container.mux(packet)


def read_file_indices(path: str, scale: float = 1.0) -> list[int]:
    with av.open(path) as container:
        return [read_index(f.to_ndarray(format="rgb24"), scale) for f in container.decode(video=0)]


if __name__ == "__main__":
    make_clip(sys.argv[1])
