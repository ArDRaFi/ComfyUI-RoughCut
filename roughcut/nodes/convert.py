from __future__ import annotations

import math
from fractions import Fraction

import numpy as np
import torch

from .. import audio as audio_tools
from .. import frames as frame_tools
from .. import source as source_tools
from ..frames import Source
from ..host import IO, InputImpl, Types


def _fraction(value: float) -> Fraction:
    return Fraction(value).limit_denominator(1001)


class RCImagesToVideo(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="RC_ImagesToVideo",
            display_name="RC Images to Video",
            category="RoughCut/Convert",
            description="Turn an IMAGE batch into a VIDEO, by frame rate, target length, or to fit an audio clip.",
            search_aliases=["batch to video", "frames to video", "create video"],
            inputs=[
                IO.Image.Input("images"),
                IO.DynamicCombo.Input(
                    "timing",
                    options=[
                        IO.DynamicCombo.Option("frame rate", [IO.Float.Input("fps", default=24.0, min=0.1, max=240.0, step=0.1)]),
                        IO.DynamicCombo.Option("target seconds", [IO.Float.Input("seconds", default=5.0, min=0.01, max=86400.0, step=0.1)]),
                        IO.DynamicCombo.Option("fit to audio", []),
                    ],
                ),
                IO.Audio.Input("audio", optional=True),
            ],
            outputs=[IO.Video.Output("video", display_name="video")],
            has_intermediate_output=True,
        )

    @classmethod
    def execute(cls, images, timing: dict, audio=None) -> IO.NodeOutput:
        count = images.shape[0]
        mode = timing["timing"]
        if mode == "fit to audio":
            if audio is None:
                raise ValueError("Connect an audio clip, or choose a different timing.")
            seconds = audio["waveform"].shape[-1] / int(audio["sample_rate"])
            fps = _fraction(max(count / seconds, 0.01))
        elif mode == "target seconds":
            fps = _fraction(count / timing["seconds"])
        else:
            fps = _fraction(timing["fps"])
        if audio is not None:
            audio = audio_tools.fit(audio, float(Fraction(count) / fps))
        video = InputImpl.VideoFromComponents(Types.VideoComponents(images=images[..., :3], audio=audio, frame_rate=fps))
        return IO.NodeOutput(video, ui=source_tools.preview_ui(video))


class RCVideoToImages(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="RC_VideoToImages",
            display_name="RC Video to Images",
            category="RoughCut/Convert",
            description="Decode just the part of a video you need into an IMAGE batch.",
            search_aliases=["extract frames", "video frames", "every nth frame"],
            inputs=[
                IO.Video.Input("video"),
                IO.Float.Input("start", default=0.0, min=0.0, max=86400.0, step=0.1, tooltip="Seconds."),
                IO.Float.Input("end", default=0.0, min=0.0, max=86400.0, step=0.1, tooltip="Seconds. 0 means the end of the video."),
                IO.Int.Input("every_nth", default=1, min=1, max=1000, tooltip="Keep one frame in every N."),
                IO.Int.Input("max_frames", default=0, min=0, max=1000000, tooltip="0 means no limit."),
                IO.Int.Input("longest_side", default=0, min=0, max=16384, step=8, tooltip="Shrink so the longest side is at most this. 0 keeps the size."),
            ],
            outputs=[IO.Image.Output("images", display_name="images"), IO.Float.Output("fps", display_name="fps"), IO.Int.Output("frames", display_name="frames")],
        )

    @classmethod
    def execute(cls, video, start: float, end: float, every_nth: int, max_frames: int, longest_side: int) -> IO.NodeOutput:
        duration = video.get_duration()
        stop = min(end, duration) if end > 0 else duration
        if stop <= start:
            raise ValueError(f"The range {start}s to {stop}s is empty. This video is {duration:.2f}s long.")
        source = source_tools.to_source(video)
        window = Source(source.path, source.start + start, stop - start)
        fps = video.get_frame_rate()
        width, height = video.get_dimensions()
        expected = round((stop - start) * fps)
        images = frame_tools.decode_images([window], width, height, expected, every_nth, max_frames, longest_side)
        return IO.NodeOutput(images, float(fps) / every_nth, images.shape[0])


class RCGrabFrame(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="RC_GrabFrame",
            display_name="RC Grab Frame",
            category="RoughCut/Convert",
            description="Take one frame from a video. Useful for chaining image-to-video generations.",
            search_aliases=["last frame", "first frame", "video frame to image"],
            inputs=[
                IO.Video.Input("video"),
                IO.DynamicCombo.Input(
                    "position",
                    options=[
                        IO.DynamicCombo.Option("last", []),
                        IO.DynamicCombo.Option("first", []),
                        IO.DynamicCombo.Option("at time", [IO.Float.Input("seconds", default=0.0, min=0.0, max=86400.0, step=0.1)]),
                        IO.DynamicCombo.Option("at percent", [IO.Float.Input("percent", default=50.0, min=0.0, max=100.0, step=1.0)]),
                    ],
                ),
            ],
            outputs=[IO.Image.Output("image", display_name="image")],
        )

    @classmethod
    def execute(cls, video, position: dict) -> IO.NodeOutput:
        source = source_tools.to_source(video)
        duration = video.get_duration()
        fps = video.get_frame_rate()
        frame_time = float(Fraction(1) / fps)
        mode = position["position"]
        if mode == "last":
            window = Source(source.path, source.start + max(0.0, duration - 1.0), min(duration, 1.0))
            last = None
            for last in frame_tools.iter_frames(window):
                pass
            frame = last
        else:
            seconds = {"first": 0.0, "at time": position.get("seconds", 0.0), "at percent": duration * position.get("percent", 0.0) / 100.0}[mode]
            seconds = min(math.floor(seconds * fps) / fps, max(0.0, float(duration) - frame_time))
            frame = next(frame_tools.iter_frames(Source(source.path, source.start + float(seconds), frame_time * 2), max_frames=1), None)
        if frame is None:
            raise ValueError("No frame found at that position.")
        return IO.NodeOutput(torch.from_numpy(np.expand_dims(frame.astype(np.float32) / 255.0, 0)))
