from __future__ import annotations

from .. import audio as audio_tools
from .. import source as source_tools
from ..host import IO


class RCVideoAudio(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="RC_VideoAudio",
            display_name="RC Video Audio",
            category="RoughCut/Audio",
            description="Replace or remove a video's sound, or take its sound out as AUDIO.",
            search_aliases=["extract audio", "mute video", "replace audio", "add music"],
            inputs=[
                IO.Video.Input("video"),
                IO.Combo.Input("mode", options=["keep", "replace", "mute"], default="keep", tooltip="Keep leaves the video as it is and outputs its sound."),
                IO.Audio.Input("audio", optional=True, tooltip="The new sound, for replace. It is trimmed or padded to the video's length."),
            ],
            outputs=[IO.Video.Output("video", display_name="video"), IO.Audio.Output("audio", display_name="audio")],
        )

    @classmethod
    def execute(cls, video, mode: str, audio=None) -> IO.NodeOutput:
        seconds = float(video.get_duration())
        if mode == "replace":
            if audio is None:
                raise ValueError("Connect an audio clip to replace the sound with.")
            fitted = audio_tools.fit(audio, seconds)
            return IO.NodeOutput(source_tools.with_new_audio(video, fitted), fitted)
        if mode == "mute":
            return IO.NodeOutput(source_tools.with_new_audio(video, None), audio_tools.silence(seconds))
        sound = source_tools.video_audio(video)
        return IO.NodeOutput(video, sound if sound is not None else audio_tools.silence(seconds))
