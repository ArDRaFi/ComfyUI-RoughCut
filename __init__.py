"""ComfyUI-RoughCut: small nodes for rough video editing inside ComfyUI workflows."""

from .roughcut.extension import comfy_entrypoint

WEB_DIRECTORY = "./web"

__all__ = ["comfy_entrypoint", "WEB_DIRECTORY"]
