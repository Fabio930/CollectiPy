# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""
Movement model package.

Importing submodules registers the built-in movement models.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

from core.configuration.plugin_registry import register_movement_model


def _resolve_movement_class(module):
    """Resolve the movement class exposed by a movement plugin module."""
    declared = getattr(module, "MOVEMENT_MODEL_CLASS", None)
    if inspect.isclass(declared):
        return declared

    candidates = [
        cls
        for _, cls in inspect.getmembers(module, inspect.isclass)
        if cls.__module__ == module.__name__
        and callable(getattr(cls, "step", None))
        and cls.__name__.lower().endswith(("movement", "movementmodel"))
    ]
    if len(candidates) == 1:
        return candidates[0]
    return None


def _autoregister_builtin_movement_models() -> None:
    """Import and register built-in movement plugin modules."""
    package_name = __name__
    for module_info in pkgutil.iter_modules(__path__):
        module_name = module_info.name
        if module_name.startswith("_") or module_name in {"common"}:
            continue

        try:
            module = importlib.import_module(f"{package_name}.{module_name}")
        except Exception:
            # Keep startup resilient: a broken optional plugin should not prevent
            # the rest of the built-in movement models from being available.
            continue
        movement_cls = _resolve_movement_class(module)
        if movement_cls is None:
            continue

        register_movement_model(module_name, lambda agent, cls=movement_cls: cls(agent))
        aliases = getattr(module, "MOVEMENT_MODEL_ALIASES", ()) or ()
        for alias in aliases:
            register_movement_model(str(alias), lambda agent, cls=movement_cls: cls(agent))


_autoregister_builtin_movement_models()
