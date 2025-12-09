# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""
Simple runtime registry for simulator plugins.

For now we only need movement models, but this module can be extended
later to support other plugin types (arena extensions, custom entities, ...).

External modules can register plugins by importing this file and calling
`register_movement_model`. The main code only ever calls `get_movement_model`,
so the core logic remains stable.
"""

from typing import Callable, Dict, Any, Iterable, Optional
from core.configuration.plugin_base import DetectionModel, LogicModel, MessageBusModel, MovementModel, MotionModel

# Internal registry for movement models: name -> factory(agent) -> MovementModel
_movement_models: Dict[str, Callable[[Any], MovementModel]] = {}
# Internal registry for motion/kinematics models.
_motion_models: Dict[str, Callable[[Any], MotionModel]] = {}
# Internal registry for optional logic models.
_logic_models: Dict[str, Callable[[Any], LogicModel]] = {}
# Internal registry for detection/perception models.
_detection_models: Dict[str, Callable[[Any, Optional[dict]], DetectionModel]] = {}
# Internal registry for message bus implementations.
_message_buses: Dict[str, Callable[[Iterable[Any], Optional[dict], Optional[dict]], MessageBusModel]] = {}

def _normalize_name(name: str) -> str:
    """Normalize the name."""
    return (name or "").strip().lower()

def register_movement_model(name: str, factory: Callable[[Any], MovementModel]) -> None:
    """
    Register a new movement model.

    Parameters
    ----------
    name:
        Identifier of the movement model, typically the same string
        used in the config as `moving_behavior`.
    factory:
        A callable that receives an agent instance and returns an object
        implementing the `MovementModel` protocol for that agent.
    """
    _movement_models[_normalize_name(name)] = factory

def get_movement_model(name: str, agent: Any) -> Optional[MovementModel]:
    """
    Return a movement model instance for the given agent.

    If no model is registered under `name`, this function returns None.
    The caller (usually the Agent class) is then free to fall back to
    the legacy behaviour.
    """
    factory = _movement_models.get(_normalize_name(name))
    if factory is None:
        return None
    return factory(agent)

def available_movement_models() -> Dict[str, Callable[[Any], MovementModel]]:
    """Return the map of registered movement model factories."""
    return dict(_movement_models)

def register_motion_model(name: str, factory: Callable[[Any], MotionModel]) -> None:
    """Register a new motion/kinematics model."""
    _motion_models[_normalize_name(name)] = factory

def get_motion_model(name: Optional[str], agent: Any) -> Optional[MotionModel]:
    """Return an instantiated motion model."""
    if not name:
        return None
    factory = _motion_models.get(_normalize_name(name))
    if factory is None:
        return None
    return factory(agent)

def available_motion_models() -> Dict[str, Callable[[Any], MotionModel]]:
    """Return the map of registered motion models."""
    return dict(_motion_models)

def register_logic_model(name: str, factory: Callable[[Any], LogicModel]) -> None:
    """Register a new logic model factory."""
    _logic_models[_normalize_name(name)] = factory

def get_logic_model(name: Optional[str], agent: Any) -> Optional[LogicModel]:
    """Return a logic model instance for the given agent."""
    if not name:
        return None
    factory = _logic_models.get(_normalize_name(name))
    if factory is None:
        return None
    return factory(agent)

def available_logic_models() -> Dict[str, Callable[[Any], LogicModel]]:
    """Return the map of registered logic model factories."""
    return dict(_logic_models)

def register_detection_model(name: str, factory: Callable[[Any, Optional[dict]], DetectionModel]) -> None:
    """Register a detection/perception model factory."""
    _detection_models[_normalize_name(name)] = factory

def get_detection_model(name: Optional[str], agent: Any, context: Optional[dict] = None) -> Optional[DetectionModel]:
    """Return a detection model instance if registered."""
    if not name:
        return None
    factory = _detection_models.get(_normalize_name(name))
    if factory is None:
        return None
    return factory(agent, context)

def available_detection_models() -> Dict[str, Callable[[Any, Optional[dict]], DetectionModel]]:
    """Return the map of registered detection model factories."""
    return dict(_detection_models)

def register_message_bus(
    name: str,
    factory: Callable[[Iterable[Any], Optional[dict], Optional[dict]], MessageBusModel]
) -> None:
    """Register a message-bus implementation."""
    _message_buses[_normalize_name(name)] = factory

def get_message_bus(
    name: Optional[str],
    agent_entities: Iterable[Any],
    config: Optional[dict] = None,
    context: Optional[dict] = None
) -> Optional[MessageBusModel]:
    """Return an instantiated message bus."""
    if not name:
        return None
    factory = _message_buses.get(_normalize_name(name))
    if factory is None:
        return None
    return factory(agent_entities, config, context)

def available_message_buses() -> Dict[str, Callable[[Iterable[Any], Optional[dict], Optional[dict]], MessageBusModel]]:
    """Return the map of registered message-bus factories."""
    return dict(_message_buses)

def load_plugins_from_config(config: Any) -> None:
    """
    Optional helper that imports plugin modules listed in the config.

    Expected layout (all fields are optional, to preserve compatibility):

    {
      "plugins": ["my_package.my_plugin", ...],
      "environment": {
        "plugins": ["another.plugin.module"]
      }
    }

    Each module is imported for its side effects, typically registration
    of movement models via `register_movement_model`.
    """
    import importlib
    modules = []

    data = getattr(config, "data", None)
    if isinstance(data, dict):
        modules.extend(data.get("plugins", []))
        env = data.get("environment", {})
        modules.extend(env.get("plugins", []))

    for mod in modules:
        try:
            importlib.import_module(mod)
        except Exception as exc:
            # We do not fail hard here to keep behaviour robust;
            # the user will see a log from the main process.
            print(f"[plugin_registry] Failed to import plugin module '{mod}': {exc}")
