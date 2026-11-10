from __future__ import annotations

from .. import source as source_tools
from ..host import IO


class RCVideoInfo(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="RC_VideoInfo",
            display_name="RC Video Info",
            category="RoughCut/Info",
            description="Read a video's size, frame rate, length and whether it has sound.",
            inputs=[IO.Video.Input("video")],
            outputs=[
                IO.Int.Output("width", display_name="width"),
                IO.Int.Output("height", display_name="height"),
                IO.Float.Output("fps", display_name="fps"),
                IO.Int.Output("frames", display_name="frames"),
                IO.Float.Output("seconds", display_name="seconds"),
                IO.Boolean.Output("has_audio", display_name="has_audio"),
            ],
        )

    @classmethod
    def execute(cls, video) -> IO.NodeOutput:
        width, height = video.get_dimensions()
        return IO.NodeOutput(width, height, float(video.get_frame_rate()), video.get_frame_count(), float(video.get_duration()), source_tools.has_audio(video))


class RCPreviewVideo(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="RC_PreviewVideo",
            display_name="RC Preview Video",
            category="RoughCut/Info",
            description="See any video on the node without saving a file to your output folder.",
            search_aliases=["show video"],
            inputs=[IO.Video.Input("video")],
            outputs=[IO.Video.Output("video", display_name="video")],
            is_output_node=True,
        )

    @classmethod
    def execute(cls, video) -> IO.NodeOutput:
        return IO.NodeOutput(video, ui=source_tools.preview_ui(video))
