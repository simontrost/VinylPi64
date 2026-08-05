"""Compatibility imports for the former web-owned config service.

Runtime configuration belongs to ``vinylpi.config``. Existing imports remain
valid while core and integration modules no longer depend on the web layer.
"""
from vinylpi.config.runtime import (
    clear_config_cache,
    get_current_fallback_path,
    read_config,
    reset_config,
    set_fallback_image_path,
    write_config,
)

__all__ = [
    "clear_config_cache",
    "get_current_fallback_path",
    "read_config",
    "reset_config",
    "set_fallback_image_path",
    "write_config",
]
