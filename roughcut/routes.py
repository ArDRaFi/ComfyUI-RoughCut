"""Routes used by the timeline. They only ever read files inside ComfyUI's input folder."""

from __future__ import annotations

import asyncio
import hashlib
import os

import av
from aiohttp import web

from .frames import fits_longest_side
from .host import PromptServer, folder_paths
from .probe import probe

_PROXY_LONGEST = 640
_registered = False


def resolve_input_file(name: str) -> str | None:
    """A file inside the input folder, or None for anything else."""
    if not name or "\0" in name:
        return None
    root = os.path.realpath(folder_paths.get_input_directory())
    path = os.path.realpath(os.path.join(root, name))
    try:
        if os.path.commonpath([root, path]) != root:
            return None
    except ValueError:  # different drive on Windows
        return None
    return path if os.path.isfile(path) else None


def _proxy_path(path: str) -> str:
    stamp = f"{path}|{os.path.getmtime(path)}".encode()
    directory = folder_paths.get_temp_directory()
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, f"roughcut_proxy_{hashlib.sha256(stamp).hexdigest()[:24]}.mp4")


def _build_proxy(path: str, target: str) -> None:
    """A small browser-friendly copy, used only for the timeline preview."""
    partial = f"{target}.part"
    with av.open(path) as reader, av.open(partial, "w", format="mp4") as writer:
        source = reader.streams.video[0]
        source.thread_type = "AUTO"
        width, height = fits_longest_side(source.codec_context.width, source.codec_context.height, _PROXY_LONGEST)
        width, height = max(2, width - width % 2), max(2, height - height % 2)
        rate = source.average_rate or 24
        stream = writer.add_stream("libx264", rate=rate)
        stream.width, stream.height, stream.pix_fmt = width, height, "yuv420p"
        stream.options = {"crf": "30", "preset": "ultrafast", "g": "12"}
        for index, frame in enumerate(reader.decode(source)):
            scaled = frame.reformat(width=width, height=height, format="yuv420p")
            scaled.pts = index
            scaled.time_base = 1 / rate
            for packet in stream.encode(scaled):
                writer.mux(packet)
        for packet in stream.encode(None):
            writer.mux(packet)
    os.replace(partial, target)


def register() -> None:
    global _registered
    if _registered:
        return
    _registered = True
    routes = PromptServer.instance.routes

    @routes.get("/roughcut/info")
    async def info(request: web.Request) -> web.Response:
        path = resolve_input_file(request.query.get("file", ""))
        if path is None:
            return web.json_response({"error": "File not found in the input folder"}, status=404)
        try:
            facts = await asyncio.get_running_loop().run_in_executor(None, probe, path)
        except (ValueError, av.error.FFmpegError):
            return web.json_response({"error": "This file could not be read as a video"}, status=415)
        return web.json_response({
            "width": facts.width,
            "height": facts.height,
            "fps": float(facts.fps),
            "frames": facts.frames,
            "duration": facts.duration,
            "has_audio": facts.has_audio,
            "browser_playable": facts.browser_playable,
        })

    @routes.get("/roughcut/media")
    async def media(request: web.Request) -> web.StreamResponse:
        path = resolve_input_file(request.query.get("file", ""))
        if path is None:
            return web.Response(status=404)
        loop = asyncio.get_running_loop()
        try:
            facts = await loop.run_in_executor(None, probe, path)
        except (ValueError, av.error.FFmpegError):
            return web.Response(status=415)
        if facts.browser_playable:
            return web.FileResponse(path)
        target = _proxy_path(path)
        if not os.path.isfile(target):
            await loop.run_in_executor(None, _build_proxy, path, target)
        return web.FileResponse(target)
