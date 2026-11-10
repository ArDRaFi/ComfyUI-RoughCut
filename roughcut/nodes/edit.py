from __future__ import annotations

import math
import os
from collections import deque
from collections.abc import Iterator
from fractions import Fraction

import numpy as np

from .. import audio as audio_tools
from .. import frames as frame_tools
from .. import source as source_tools
from ..host import IO, InputImpl

MAX_CLIPS = 32


class RCCutVideo(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="RC_CutVideo",
            display_name="RC Cut Video",
            category="RoughCut/Edit",
            description="Split a video into two clips at a point in time.",
            search_aliases=["split video"],
            inputs=[IO.Video.Input("video"), IO.Float.Input("seconds", default=1.0, min=0.0, max=86400.0, step=0.1, tooltip="Where to cut.")],
            outputs=[IO.Video.Output("before", display_name="before"), IO.Video.Output("after", display_name="after")],
        )

    @classmethod
    def execute(cls, video, seconds: float) -> IO.NodeOutput:
        duration = video.get_duration()
        fps = video.get_frame_rate()
        cut = float(Fraction(round(Fraction(seconds) * fps)) / fps)
        if cut <= 0 or cut >= duration:
            raise ValueError(f"Choose a cut point inside the video, which is {duration:.2f}s long.")
        return IO.NodeOutput(video.as_trimmed(0.0, cut, False), video.as_trimmed(cut, float(duration) - cut, False))


class RCJoinVideos(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        names = [f"video_{i}" for i in range(1, MAX_CLIPS + 1)]
        return IO.Schema(
            node_id="RC_JoinVideos",
            display_name="RC Join Videos",
            category="RoughCut/Edit",
            description="Join clips in order. Clips of different size or frame rate are matched to the first clip.",
            search_aliases=["concatenate video", "merge videos", "crossfade"],
            inputs=[
                IO.Autogrow.Input("videos", template=IO.Autogrow.TemplateNames(IO.Video.Input("video"), names=names, min=2)),
                IO.Float.Input("crossfade", default=0.0, min=0.0, max=30.0, step=0.1, tooltip="Seconds of overlap between clips. 0 is a hard cut."),
                IO.Combo.Input("fit", options=["pad", "crop", "stretch"], default="pad", tooltip="How clips of a different shape match the first clip."),
            ],
            outputs=[IO.Video.Output("video", display_name="video")],
        )

    @classmethod
    def execute(cls, videos: dict, crossfade: float, fit: str) -> IO.NodeOutput:
        clips = [v for v in videos.values() if v is not None]
        if len(clips) < 2:
            raise ValueError("Connect at least two videos.")
        size = clips[0].get_dimensions()
        fps = clips[0].get_frame_rate()
        if crossfade <= 0 and all(c.get_dimensions() == size and c.get_frame_rate() == fps for c in clips):
            return IO.NodeOutput(InputImpl.VideoFromList(clips))  # nothing needs re-encoding

        width, height = max(2, size[0] - size[0] % 2), max(2, size[1] - size[1] % 2)
        clip_frames = [frame_tools.retime_count(c.get_frame_count(), c.get_frame_rate(), fps) for c in clips]
        overlap = frame_tools.crossfade_frames(crossfade, fps, clip_frames)
        sources = [source_tools.to_source(c) for c in clips]

        def clip_iter(index: int) -> Iterator[np.ndarray]:
            for frame in frame_tools.retime(frame_tools.iter_frames(sources[index]), clips[index].get_frame_rate(), fps):
                yield frame_tools.fit_frame(frame, width, height, fit)

        def joined() -> Iterator[np.ndarray]:
            carried: deque[np.ndarray] = deque()  # the previous clip's last frames
            for index in range(len(clips)):
                keep_back = overlap if index < len(clips) - 1 else 0
                held: deque[np.ndarray] = deque()
                position = 0
                for frame in clip_iter(index):
                    if carried:
                        ramp = (position + 1) / (overlap + 1)
                        frame = (carried.popleft().astype(np.float32) * (1 - ramp) + frame.astype(np.float32) * ramp).round().astype(np.uint8)
                    position += 1
                    held.append(frame)
                    if len(held) > keep_back:
                        yield held.popleft()
                yield from carried
                carried = held
            yield from carried

        tracks = []
        any_audio = any(source_tools.has_audio(c) for c in clips)
        if any_audio:
            for clip, source, count in zip(clips, sources, clip_frames, strict=True):
                sound = source_tools.video_audio(clip) if source_tools.has_audio(clip) else None
                seconds = float(Fraction(count) / fps)
                tracks.append(audio_tools.fit(sound, seconds) if sound is not None else audio_tools.silence(seconds))
        sound = audio_tools.join(tracks, float(Fraction(overlap) / fps)) if tracks else None
        total = sum(clip_frames) - overlap * (len(clips) - 1)
        return IO.NodeOutput(source_tools.render(joined(), width, height, fps, sound, total))


class RCSpeedReverse(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="RC_SpeedReverse",
            display_name="RC Speed / Reverse",
            category="RoughCut/Edit",
            description="Speed up, slow down or reverse a video. Audio stays in sync and keeps its pitch.",
            search_aliases=["slow motion", "fast forward", "reverse video", "timelapse"],
            inputs=[
                IO.Video.Input("video"),
                IO.Float.Input("speed", default=1.0, min=0.1, max=10.0, step=0.05, tooltip="2 is twice as fast, 0.5 is half speed."),
                IO.Boolean.Input("reverse", default=False),
            ],
            outputs=[IO.Video.Output("video", display_name="video")],
        )

    @classmethod
    def execute(cls, video, speed: float, reverse: bool) -> IO.NodeOutput:
        if speed == 1.0 and not reverse:
            return IO.NodeOutput(video)
        source = source_tools.to_source(video)
        fps = video.get_frame_rate()
        width, height = video.get_dimensions()
        factor = Fraction(speed).limit_denominator(1000)
        count = max(1, math.floor(Fraction(video.get_frame_count()) / factor))

        def timed() -> Iterator[np.ndarray]:
            yield from frame_tools.retime(frame_tools.iter_frames(source), Fraction(1), 1 / factor)

        sound = source_tools.video_audio(video)
        if sound is not None:
            sound = audio_tools.change_speed(sound, float(factor))
            if reverse:
                sound = audio_tools.reverse(sound)
            sound = audio_tools.fit(sound, float(Fraction(count) / fps))
        frames = _reversed_frames(timed(), width, height, count) if reverse else timed()
        return IO.NodeOutput(source_tools.render(frames, width, height, fps, sound, count))


def _reversed_frames(frames: Iterator[np.ndarray], width: int, height: int, count: int) -> Iterator[np.ndarray]:
    """Spool frames to a temporary file and read them backwards, so RAM use stays small."""
    path = source_tools.temp_path("raw")
    spool = None
    written = 0
    try:
        spool = np.memmap(path, dtype=np.uint8, mode="w+", shape=(count + 2, height, width, 3))
        for frame in frames:
            if written >= spool.shape[0]:
                break
            spool[written] = frame
            written += 1
        for index in range(written - 1, -1, -1):
            yield np.array(spool[index])
    finally:
        del spool
        try:
            os.unlink(path)
        except OSError:
            pass
