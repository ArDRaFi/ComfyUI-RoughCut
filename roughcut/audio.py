"""Audio helpers working on ComfyUI AUDIO dicts: {"waveform": [B, C, T], "sample_rate": int}."""

from __future__ import annotations

from fractions import Fraction

import av
import numpy as np
import torch

from .frames import Source, check_interrupt


def silence(seconds: float, rate: int = 44100, channels: int = 1) -> dict:
    return {"waveform": torch.zeros((1, channels, max(1, round(seconds * rate)))), "sample_rate": rate}


def _layout(channels: int) -> str:
    return "stereo" if channels >= 2 else "mono"


def load_range(source: Source) -> dict | None:
    """Decode the audio in a window. Returns None when the file has no audio."""
    with av.open(source.path) as container:
        if not container.streams.audio:
            return None
        stream = container.streams.audio[0]
        rate = int(stream.codec_context.sample_rate)
        layout = _layout(stream.codec_context.channels or 1)
        if source.start > 0:
            container.seek(int(source.start * av.time_base), backward=True)
        resampler = av.AudioResampler(format="fltp", layout=layout, rate=rate)
        parts: list[np.ndarray] = []
        first_time: float | None = None
        for frame in container.decode(stream):
            check_interrupt()
            if first_time is None:
                first_time = frame.time if frame.time is not None else 0.0
            parts += [f.to_ndarray() for f in resampler.resample(frame)]
            if source.duration and frame.time is not None and frame.time > source.start + source.duration + 0.5:
                break
        parts += [f.to_ndarray() for f in resampler.resample(None)]
    if not parts:
        return None
    samples = np.concatenate(parts, axis=1).astype(np.float32)
    skip = max(0, round((source.start - (first_time or 0.0)) * rate))
    stop = skip + round(source.duration * rate) if source.duration else samples.shape[1]
    return {"waveform": torch.from_numpy(samples[:, skip:stop].copy()).unsqueeze(0), "sample_rate": rate}


def resample(audio: dict, rate: int, channels: int) -> dict:
    """Convert sample rate and channel count."""
    waveform = audio["waveform"][0]
    source_rate = int(audio["sample_rate"])
    if source_rate == rate and waveform.shape[0] == channels:
        return audio
    if waveform.shape[0] > 2:
        waveform = waveform[:2]
    frame = av.AudioFrame.from_ndarray(waveform.detach().cpu().float().numpy(), format="fltp", layout=_layout(waveform.shape[0]))
    frame.sample_rate = source_rate
    resampler = av.AudioResampler(format="fltp", layout=_layout(channels), rate=rate)
    out = [f.to_ndarray() for f in resampler.resample(frame) + resampler.resample(None)]
    return {"waveform": torch.from_numpy(np.concatenate(out, axis=1).astype(np.float32)).unsqueeze(0), "sample_rate": rate}


def fit(audio: dict, seconds: float) -> dict:
    """Trim or pad with silence to an exact length."""
    rate = int(audio["sample_rate"])
    samples = round(seconds * rate)
    waveform = audio["waveform"]
    if waveform.shape[-1] >= samples:
        return {"waveform": waveform[..., :samples], "sample_rate": rate}
    padding = torch.zeros((*waveform.shape[:-1], samples - waveform.shape[-1]), dtype=waveform.dtype)
    return {"waveform": torch.cat([waveform, padding], dim=-1), "sample_rate": rate}


def join(clips: list[dict], overlap_seconds: float = 0.0) -> dict:
    """Join clips in order, with an optional linear crossfade between them."""
    rate = max(int(c["sample_rate"]) for c in clips)
    channels = max(min(c["waveform"].shape[1], 2) for c in clips)
    converted = [resample(c, rate, channels)["waveform"][0] for c in clips]
    overlap = round(overlap_seconds * rate)
    result = converted[0]
    for clip in converted[1:]:
        fade = min(overlap, result.shape[-1], clip.shape[-1])
        if fade:
            ramp = torch.linspace(0.0, 1.0, fade)
            mixed = result[..., -fade:] * (1 - ramp) + clip[..., :fade] * ramp
            result = torch.cat([result[..., :-fade], mixed, clip[..., fade:]], dim=-1)
        else:
            result = torch.cat([result, clip], dim=-1)
    return {"waveform": result.unsqueeze(0), "sample_rate": rate}


def _atempo_steps(speed: float) -> list[float]:
    """FFmpeg's atempo works best between 0.5x and 2x per step."""
    steps: list[float] = []
    while speed > 2.0:
        steps.append(2.0)
        speed /= 2.0
    while speed < 0.5:
        steps.append(0.5)
        speed /= 0.5
    steps.append(speed)
    return steps


def change_speed(audio: dict, speed: float) -> dict:
    """Change speed while keeping the pitch."""
    if speed == 1.0:
        return audio
    waveform = audio["waveform"][0][:2]
    rate = int(audio["sample_rate"])
    layout = _layout(waveform.shape[0])
    graph = av.filter.Graph()
    node = graph.add_abuffer(format="fltp", sample_rate=rate, layout=layout, time_base=Fraction(1, rate))
    source = node
    for step in _atempo_steps(speed):
        tempo = graph.add("atempo", str(step))
        node.link_to(tempo)
        node = tempo
    sink = graph.add("abuffersink")
    node.link_to(sink)
    graph.configure()

    data = waveform.detach().cpu().float().numpy()
    out: list[np.ndarray] = []

    def drain() -> None:
        while True:
            try:
                out.append(sink.pull().to_ndarray())
            except (BlockingIOError, EOFError, av.error.BlockingIOError, av.error.EOFError):
                return

    chunk = rate // 4 or 1
    for position in range(0, data.shape[1], chunk):
        check_interrupt()
        frame = av.AudioFrame.from_ndarray(data[:, position : position + chunk], format="fltp", layout=layout)
        frame.sample_rate = rate
        frame.pts = position
        frame.time_base = Fraction(1, rate)
        source.push(frame)
        drain()
    source.push(None)
    drain()
    samples = np.concatenate(out, axis=1).astype(np.float32) if out else np.zeros((waveform.shape[0], 1), dtype=np.float32)
    return fit({"waveform": torch.from_numpy(samples).unsqueeze(0), "sample_rate": rate}, waveform.shape[1] / rate / speed)


def reverse(audio: dict) -> dict:
    return {"waveform": torch.flip(audio["waveform"], dims=[-1]), "sample_rate": audio["sample_rate"]}
