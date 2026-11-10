from __future__ import annotations

import os

import torch

from .. import audio as audio_tools
from .. import parts as parts_tools
from ..frames import Source, decode_images
from ..host import IO, InputImpl, PromptServer, folder_paths
from ..probe import probe

_IMAGE_OUTPUT = 1
_AUDIO_OUTPUT = 2


def _running_links(node_id: str | None) -> list[int] | None:
    """Connected outputs in the workflow now running. ComfyUI's cache ignores connections,
    so without this an output left empty on an earlier run would be reused once connected."""
    try:
        for item in PromptServer.instance.prompt_queue.currently_running.values():
            prompt = item[2]
            if node_id in prompt:
                return sorted(parts_tools.linked_outputs(prompt, node_id) or [])
    except (AttributeError, IndexError, TypeError):
        pass
    return None


class RCLoadVideo(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        input_dir = folder_paths.get_input_directory()
        files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))]
        files = folder_paths.filter_files_content_types(files, ["video"])
        return IO.Schema(
            node_id="RC_LoadVideo",
            display_name="RC Load Video",
            category="RoughCut",
            description="Load a video and choose which parts of it to pass on.",
            search_aliases=["trim video", "pick video parts", "video segments"],
            inputs=[
                IO.Combo.Input("file", options=sorted(files), tooltip="A video from ComfyUI's input folder. Use Upload on the timeline, or drop a video on this node."),
                IO.String.Input("parts", default="", optional=True, tooltip='Set on the timeline. As text: [{"start": 1.0, "end": 2.5}]. Empty uses the whole video.'),
            ],
            outputs=[
                IO.Video.Output("video", display_name="video"),
                IO.Image.Output("images", display_name="images", tooltip="Decoded only when connected."),
                IO.Audio.Output("audio", display_name="audio", tooltip="Decoded only when connected."),
                IO.Float.Output("fps", display_name="fps"),
                IO.Int.Output("frames", display_name="frames"),
            ],
            hidden=[IO.Hidden.unique_id, IO.Hidden.prompt],
        )

    @classmethod
    def validate_inputs(cls, file, parts=""):
        if not folder_paths.exists_annotated_filepath(file):
            return f"Video not found: {file}"
        return True

    @classmethod
    def fingerprint_inputs(cls, file, parts=""):
        path = folder_paths.get_annotated_filepath(file)
        return f"{os.path.getmtime(path)}|{_running_links(cls.hidden.unique_id)}"

    @classmethod
    def execute(cls, file: str, parts: str = "") -> IO.NodeOutput:
        path = folder_paths.get_annotated_filepath(file)
        facts = probe(path)
        selected = parts_tools.normalize(parts_tools.parse(parts), facts.duration, facts.fps)
        count = parts_tools.frame_count(selected, facts.fps)

        whole = InputImpl.VideoFromFile(path)
        if parts_tools.covers_whole(selected, facts.duration, facts.fps):
            video = whole
        else:
            clips = [whole.as_trimmed(start, end - start, False) for start, end in selected]
            video = clips[0] if len(clips) == 1 else InputImpl.VideoFromList(clips)

        linked = parts_tools.linked_outputs(cls.hidden.prompt, cls.hidden.unique_id)
        sources = [Source(path, start, end - start) for start, end in selected]
        if linked is None or _IMAGE_OUTPUT in linked:
            images = decode_images(sources, facts.width, facts.height, count)
        else:
            images = torch.zeros((1, 1, 1, 3))
        if linked is None or _AUDIO_OUTPUT in linked:
            pieces = [audio_tools.load_range(source) for source in sources]
            pieces = [p for p in pieces if p is not None]
            sound = audio_tools.join(pieces) if pieces else audio_tools.silence(count / float(facts.fps))
        else:
            sound = audio_tools.silence(0.01)
        return IO.NodeOutput(video, images, sound, float(facts.fps), count)
