"""ComfyUI custom node pack: GCRip mocap helpers (see nodes.py).

Install: junction or copy this folder into ComfyUI/custom_nodes/ (e.g.
``mklink /J ComfyUI\\custom_nodes\\gcrip_mocap "Z:\\3d ripper\\comfyui\\gcrip_mocap"``)."""

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
