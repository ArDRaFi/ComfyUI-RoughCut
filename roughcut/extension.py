from __future__ import annotations

from typing_extensions import override

from . import routes
from .host import IO, ComfyExtension
from .nodes.audio import RCVideoAudio
from .nodes.convert import RCGrabFrame, RCImagesToVideo, RCVideoToImages
from .nodes.edit import RCCutVideo, RCJoinVideos, RCSpeedReverse
from .nodes.info import RCPreviewVideo, RCVideoInfo
from .nodes.load import RCLoadVideo


class RoughCut(ComfyExtension):
    @override
    async def get_node_list(self) -> list[type[IO.ComfyNode]]:
        return [
            RCLoadVideo,
            RCImagesToVideo,
            RCVideoToImages,
            RCGrabFrame,
            RCCutVideo,
            RCJoinVideos,
            RCSpeedReverse,
            RCVideoAudio,
            RCVideoInfo,
            RCPreviewVideo,
        ]


async def comfy_entrypoint() -> RoughCut:
    routes.register()
    return RoughCut()
