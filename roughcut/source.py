"""Turns any ComfyUI VIDEO into a file plus time window, and writes edited results."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterable
from fractions import Fraction

import av
import numpy as np

from . import audio as audio_tools
from .frames import Source, check_interrupt
from .host import InputImpl, ProgressBar, Types, UI, IO, folder_paths
from .probe import probe


def temp_path(extension: str = "mp4") -> str:
    directory = folder_paths.get_temp_directory()
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, f"roughcut_{uuid.uuid4().hex}.{extension}")


def to_source(video) -> Source:
    """Plain trimmed files are used directly. Anything else is written to a temp file first."""
    if isinstance(video, InputImpl.VideoFromFile):
        stream_source = video.get_stream_source()
        if isinstance(stream_source, str) and video.get_dimensions() == _file_dimensions(stream_source):
            start, duration = video.get_active_trim_window()
            return Source(stream_source, start, duration)
    path = temp_path()
    video.save_to(path, format=Types.VideoContainer.MP4, codec=Types.VideoCodec.AUTO)
    return Source(path)


def _file_dimensions(path: str) -> tuple[int, int]:
    facts = probe(path)
    return facts.width, facts.height


def has_audio(video) -> bool:
    if isinstance(video, InputImpl.VideoFromList):
        return video.complete_audio is not None or any(has_audio(v) for v in video.videos)
    if isinstance(video, InputImpl.VideoFromFile):
        stream_source = video.get_stream_source()
        with av.open(stream_source) as container:
            return bool(container.streams.audio)
    return video.get_components().audio is not None


def video_audio(video) -> dict | None:
    """The audio of any VIDEO, or None."""
    if not has_audio(video):
        return None
    if isinstance(video, InputImpl.VideoFromFile):
        source = to_source(video)
        return audio_tools.load_range(source)
    return video.get_components().audio


def _even(value: int) -> int:
    return max(2, value - value % 2)


def render(frames: Iterable[np.ndarray], width: int, height: int, fps: Fraction, audio: dict | None = None, total: int = 0):
    """Stream frames straight to an H.264 file, so long videos never sit in memory."""
    width, height = _even(width), _even(height)
    path = temp_path()
    progress = ProgressBar(total) if total else None
    with av.open(path, "w") as container:
        stream = container.add_stream("libx264", rate=fps)
        stream.width, stream.height, stream.pix_fmt = width, height, "yuv420p"
        stream.options = {"crf": "18", "preset": "veryfast"}
        stream.time_base = Fraction(1) / fps
        audio_stream = None
        channels = 0
        if audio is not None:
            channels = min(audio["waveform"].shape[1], 2)
            audio_stream = container.add_stream("aac", rate=int(audio["sample_rate"]), layout="stereo" if channels == 2 else "mono")
        written = 0
        for array in frames:
            check_interrupt()
            frame = av.VideoFrame.from_ndarray(array[:height, :width], format="rgb24")
            frame.pts = written
            for packet in stream.encode(frame):
                container.mux(packet)
            written += 1
            if progress is not None:
                progress.update(1)
        for packet in stream.encode(None):
            container.mux(packet)
        if audio_stream is not None:
            _write_audio(container, audio_stream, audio, channels)
    return InputImpl.VideoFromFile(path)


def _write_audio(container, stream, audio: dict, channels: int) -> None:
    samples = audio["waveform"][0][:channels].detach().cpu().float().numpy()
    frame = av.AudioFrame.from_ndarray(samples, format="fltp", layout="stereo" if channels == 2 else "mono")
    frame.sample_rate = int(audio["sample_rate"])
    for packet in stream.encode(frame):
        container.mux(packet)
    for packet in stream.encode(None):
        container.mux(packet)


def with_new_audio(video, audio: dict | None):
    """Replace or remove audio by copying the picture stream, so the picture is untouched."""
    source = to_source(video)
    if source.start or source.duration:  # copying can only start on a keyframe
        path = temp_path()
        video.save_to(path, format=Types.VideoContainer.MP4, codec=Types.VideoCodec.AUTO)
        source = Source(path)
    output = temp_path("mkv")
    with av.open(source.path) as reader, av.open(output, "w") as writer:
        input_stream = reader.streams.video[0]
        output_stream = writer.add_stream_from_template(input_stream)
        audio_stream = None
        channels = 0
        if audio is not None:
            channels = min(audio["waveform"].shape[1], 2)
            audio_stream = writer.add_stream("aac", rate=int(audio["sample_rate"]), layout="stereo" if channels == 2 else "mono")
        for packet in reader.demux(input_stream):
            check_interrupt()
            if packet.dts is None:
                continue
            packet.stream = output_stream
            writer.mux(packet)
        if audio_stream is not None:
            _write_audio(writer, audio_stream, audio, channels)
    return InputImpl.VideoFromFile(output)


def preview_ui(video):
    """Write a small temp copy for the node's video preview."""
    full_folder, filename, counter, subfolder, _ = folder_paths.get_save_image_path("RoughCut_preview", folder_paths.get_temp_directory(), 0, 0)
    file = f"{filename}_{counter:05}_.mp4"
    video.save_to(os.path.join(full_folder, file), format=Types.VideoContainer.MP4, codec=Types.VideoCodec.AUTO, preset="ultrafast")
    return UI.PreviewVideo([UI.SavedResult(file, subfolder, IO.FolderType.temp)])
