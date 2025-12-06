# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

import itertools
import json
from collections.abc import Callable

from logging_utils import get_logger

GUI_ON_CLICK_OPTIONS = {"messages", "detection", "spins"}
GUI_VIEW_OPTIONS = {"messages", "detection"}

ALLOWED_ARENA_IDS = {"rectangle", "square", "circle", "abstract", "unbounded"}
ARENA_DIMENSION_CONSTRAINTS = {
    "rectangle": {"width", "depth", "height"},
    "square": {"side", "height"},
    "circle": {"radius", "diameter", "height"},
    "abstract": set(),
    "unbounded": {"diameter", "radius", "height"},
}

ALLOWED_OBJECT_IDS = {"idle", "interactive"}
ALLOWED_OBJECT_SHAPES = {"circle", "square", "rectangle", "sphere", "cube", "cylinder", "none"}
OBJECT_DIMENSION_CONSTRAINTS = {
    "circle": {"radius", "diameter", "height"},
    "square": {"side", "height"},
    "rectangle": {"width", "depth", "height"},
    "sphere": {"radius", "diameter"},
    "cube": {"side", "width", "height", "depth"},
    "cylinder": {"radius", "diameter", "height"},
    "none": set(),
}

ALLOWED_AGENT_SHAPES = {"sphere", "cube", "cylinder", "none"}
AGENT_DIMENSION_CONSTRAINTS = OBJECT_DIMENSION_CONSTRAINTS

RESULT_AGENT_SPECS = {"base", "spin_model"}
RESULT_GROUP_SPECS = {"graph_messages", "graph_detection", "graphs"}

LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

MESSAGE_TYPES = {"broadcast", "rebroadcast", "hand-shake"}
MESSAGE_KINDS = {"anonymous", "id-aware"}
MESSAGE_CHANNELS = {"single", "dual"}
MESSAGE_TIMER_DISTRIBUTIONS = {"fixed", "uniform", "exp", "exponential", "gaussian"}

DIMENSION_SHAPES_WITH_DIAMETER = {"circle", "cylinder", "sphere", "unbounded"}

logger = get_logger("config")

_ENVIRONMENT_HOOKS: list[Callable[[dict], None]] = []
_ENTITY_HOOKS = {
    "arena": [],
    "object": [],
    "agent": []
}

_ALL_DIMENSION_KEYS = {"width", "depth", "height", "side", "radius", "diameter", "length"}

def _clone_config_obj(obj):
    """Deep-clone config data without using copy module."""
    return json.loads(json.dumps(obj))

def _populate_dimensions(entity: dict, shape_key: str | None = None) -> set[str]:
    """Merge a 'dimensions' block into the flat configuration fields."""
    provided = set()
    dims = entity.get("dimensions")
    if isinstance(dims, dict):
        for key, value in dims.items():
            entity.setdefault(key, value)
            provided.add(key)
        entity.pop("dimensions", None)
    provided.update(key for key in entity if key in _ALL_DIMENSION_KEYS)
    if shape_key:
        shape = entity.get(shape_key)
    else:
        shape = entity.get("_id")
    if shape in DIMENSION_SHAPES_WITH_DIAMETER:
        radius = entity.get("radius")
        diameter = entity.get("diameter")
        if diameter is None and isinstance(radius, (int, float)):
            entity["diameter"] = float(radius) * 2
    return provided

def _coerce_dimension_value(value):
    """Return a float for numeric dimensions, skip booleans."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _values_almost_equal(a, b, rel_tol=1e-9):
    """Compare floats with a small tolerance."""
    return abs(a - b) <= rel_tol * max(1.0, abs(a), abs(b))


def _radius_diameter_resolver(source_key, source_value):
    """Derive radius/diameter pair from the canonical value."""
    value = float(source_value)
    if source_key == "diameter":
        return {"diameter": value, "radius": value / 2.0}
    return {"radius": value, "diameter": value * 2.0}


def _make_equal_resolver(keys):
    """Create resolver that sets every dimension in keys to the canonical value."""
    def resolver(_source_key, source_value):
        normalized = float(source_value)
        return {key: normalized for key in keys}
    return resolver


_RADIUS_DIAMETER_KEYS = ("diameter", "radius")
_CUBE_DIMENSION_KEYS = ("depth", "height", "side", "width")

_SHAPE_DIMENSION_RULES = {
    "circle": [(_RADIUS_DIAMETER_KEYS, _radius_diameter_resolver)],
    "cylinder": [(_RADIUS_DIAMETER_KEYS, _radius_diameter_resolver)],
    "sphere": [(_RADIUS_DIAMETER_KEYS, _radius_diameter_resolver)],
    "unbounded": [(_RADIUS_DIAMETER_KEYS, _radius_diameter_resolver)],
    "cube": [(_CUBE_DIMENSION_KEYS, _make_equal_resolver(_CUBE_DIMENSION_KEYS))],
}


_DEFAULT_DIMENSION_VALUE = 1.0


def _apply_dimension_rule(entity, shape_id, context, entity_key, keys, resolver, provided_keys: set[str] | None):
    """Apply a single congruency rule and log when values disagree."""
    sorted_keys = sorted(keys)
    canonical_key = None
    canonical_value = None
    provided_keys = provided_keys or set()
    for key in sorted_keys:
        if provided_keys and key not in provided_keys:
            continue
        candidate = _coerce_dimension_value(entity.get(key))
        if candidate is not None:
            canonical_key = key
            canonical_value = candidate
            break
    if canonical_key is None:
        canonical_key = sorted_keys[0]
        canonical_value = _DEFAULT_DIMENSION_VALUE
    resolved = resolver(canonical_key, canonical_value)
    conflicts = []
    for target_key, target_value in resolved.items():
        new_value = float(target_value)
        prev_raw = entity.get(target_key)
        prev_value = _coerce_dimension_value(prev_raw)
        if (
            target_key in provided_keys
            and prev_raw is not None
            and (prev_value is None or not _values_almost_equal(prev_value, new_value))
        ):
            conflicts.append((target_key, prev_raw if prev_value is None else prev_value, new_value))
        entity[target_key] = new_value
    if conflicts:
        conflict_desc = "; ".join(f"{key} ({old} -> {new})" for key, old, new in conflicts)
        shape_label = "/".join(sorted_keys)
        logger.warning(
            "%s '%s' shape '%s': enforced %s congruency from '%s'=%.9g, overwrote %s",
            context.capitalize(),
            entity_key or "<unknown>",
            shape_id,
            shape_label,
            canonical_key,
            canonical_value,
            conflict_desc,
        )


def _enforce_dimension_congruency(entity, shape_field, context, entity_key, provided_keys: set[str] | None):
    """Ensure any related dimensions defined for `shape_field` agree."""
    shape_id = entity.get(shape_field)
    if not shape_id:
        return
    rules = _SHAPE_DIMENSION_RULES.get(shape_id)
    if not rules:
        return
    for keys, resolver in rules:
        _apply_dimension_rule(entity, shape_id, context, entity_key, keys, resolver, provided_keys)


def _finalize_dimensions(entity: dict, allowed_keys: set[str]):
    """Produce a dimensions dict containing only the allowed keys."""
    dims = {}
    for key in sorted(allowed_keys):
        value = _coerce_dimension_value(entity.get(key))
        dims[key] = value if value is not None else _DEFAULT_DIMENSION_VALUE
    entity["dimensions"] = dims
    for key in _ALL_DIMENSION_KEYS:
        entity.pop(key, None)


def _validate_list_options(name: str, values, allowed: set[str]):
    if not isinstance(values, list):
        raise ValueError(f"'{name}' must be a list of strings")
    invalid = [val for val in values if val not in allowed]
    if invalid:
        raise ValueError(f"Invalid entries for '{name}': {invalid}, allowed values: {sorted(allowed)}")

def _validate_dimensions_block(shape_id: str, dims, constraints: dict, context: str):
    if dims is None:
        return
    if not isinstance(dims, dict):
        raise ValueError(f"The 'dimensions' block for {context} '{shape_id}' must be a dictionary")
    allowed = constraints.get(shape_id)
    if allowed is None:
        raise ValueError(f"Unknown shape '{shape_id}' declared for {context}")
    extras = set(dims) - allowed
    if extras:
        raise ValueError(f"{context.capitalize()} '{shape_id}' does not accept dimensions {sorted(list(extras))}")

def _validate_results_block(results):
    if not isinstance(results, dict):
        raise ValueError("The 'results' block must be a dictionary")
    agent_specs = results.get("agent_specs")
    if agent_specs is not None:
        _validate_list_options("results.agent_specs", agent_specs, RESULT_AGENT_SPECS)
    group_specs = results.get("group_specs")
    if group_specs is not None:
        _validate_list_options("results.group_specs", group_specs, RESULT_GROUP_SPECS)

def _validate_logging_block(logging_cfg):
    if not isinstance(logging_cfg, dict):
        raise ValueError("The 'logging' block must be a dictionary")
    level_raw = logging_cfg.get("level")
    if level_raw is not None:
        if isinstance(level_raw, str):
            level = level_raw.upper()
            if level not in LOG_LEVELS:
                raise ValueError(f"Invalid logging.level '{level_raw}', must be one of {sorted(LOG_LEVELS)}")
            logging_cfg["level"] = level
        else:
            raise ValueError(f"Invalid logging.level '{level_raw}', must be a string in {sorted(LOG_LEVELS)}")
    to_file = logging_cfg.get("to_file")
    if to_file is not None and not isinstance(to_file, bool):
        raise ValueError("'logging.to_file' must be a boolean")
    to_console = logging_cfg.get("to_console")
    if to_console is not None and not isinstance(to_console, bool):
        raise ValueError("'logging.to_console' must be a boolean")
    base_path = logging_cfg.get("base_path")
    if base_path is not None and not isinstance(base_path, str):
        raise ValueError("'logging.base_path' must be a string")

def _validate_gui_block(gui_cfg):
    if not isinstance(gui_cfg, dict):
        raise ValueError("The 'gui' block must be a dictionary")
    gui_id = gui_cfg.get("_id")
    if not gui_id or not isinstance(gui_id, str):
        raise ValueError("The '_id' field is required in the gui block and must be a string")
    if "on_click" in gui_cfg:
        _validate_list_options("gui.on_click", gui_cfg["on_click"], GUI_ON_CLICK_OPTIONS)
    if "view" in gui_cfg:
        _validate_list_options("gui.view", gui_cfg["view"], GUI_VIEW_OPTIONS)

def _validate_timer_block(timer_cfg):
    if not isinstance(timer_cfg, dict):
        raise ValueError("The 'timer' block inside messages must be a dictionary")
    distribution = timer_cfg.get("distribution")
    if distribution is not None and distribution not in MESSAGE_TIMER_DISTRIBUTIONS:
        raise ValueError(f"Invalid messages.timer.distribution '{distribution}', allowed: {sorted(MESSAGE_TIMER_DISTRIBUTIONS)}")
    params = timer_cfg.get("parameters")
    if params is not None and not isinstance(params, dict):
        raise ValueError("The 'timer.parameters' block inside messages must be a dictionary when provided")

def _validate_messages_block(messages_cfg):
    if not isinstance(messages_cfg, dict):
        raise ValueError("The 'messages' block must be a dictionary")
    if "type" in messages_cfg and messages_cfg["type"] not in MESSAGE_TYPES:
        raise ValueError(f"Invalid messages.type '{messages_cfg['type']}', allowed: {sorted(MESSAGE_TYPES)}")
    if "kind" in messages_cfg and messages_cfg["kind"] not in MESSAGE_KINDS:
        raise ValueError(f"Invalid messages.kind '{messages_cfg['kind']}', allowed: {sorted(MESSAGE_KINDS)}")
    if "channels" in messages_cfg and messages_cfg["channels"] not in MESSAGE_CHANNELS:
        raise ValueError(f"Invalid messages.channels '{messages_cfg['channels']}', allowed: {sorted(MESSAGE_CHANNELS)}")
    timer_cfg = messages_cfg.get("timer")
    if timer_cfg is not None:
        _validate_timer_block(timer_cfg)
    # Optional numeric rate checks (send/receive)
    rate_keys = (
        "send_message_per_seconds",
        "send_message_per_second",  # allow missing trailing s
        "receive_message_per_seconds",
        "receive_message_per_second",  # allow missing trailing s
    )
    for key in rate_keys:
        value = messages_cfg.get(key)
        if value is None:
            continue
        if not isinstance(value, (int, float)):
            raise ValueError(f"'messages.{key}' must be numeric if provided")

def _validate_arena_cfg(arena_cfg):
    if "_id" not in arena_cfg or arena_cfg["_id"] not in ALLOWED_ARENA_IDS:
        raise ValueError(f"Arena '_id' must be one of {sorted(ALLOWED_ARENA_IDS)}")
    _validate_dimensions_block(arena_cfg["_id"], arena_cfg.get("dimensions"), ARENA_DIMENSION_CONSTRAINTS, "arena")

def _validate_object_cfg(object_cfg):
    if "_id" not in object_cfg or object_cfg["_id"] not in ALLOWED_OBJECT_IDS:
        raise ValueError(f"Object '_id' must be one of {sorted(ALLOWED_OBJECT_IDS)}")
    shape = object_cfg.get("shape")
    if shape not in ALLOWED_OBJECT_SHAPES:
        raise ValueError(f"Object 'shape' must be one of {sorted(ALLOWED_OBJECT_SHAPES)}")
        _validate_dimensions_block(shape, object_cfg.get("dimensions"), OBJECT_DIMENSION_CONSTRAINTS, "object")

def _validate_agent_cfg(agent_cfg):
    shape = agent_cfg.get("shape")
    if shape not in ALLOWED_AGENT_SHAPES:
        raise ValueError(f"Agent 'shape' must be one of {sorted(ALLOWED_AGENT_SHAPES)}")
    _validate_dimensions_block(shape, agent_cfg.get("dimensions"), AGENT_DIMENSION_CONSTRAINTS, "agent")
    messages_cfg = agent_cfg.get("messages")
    if messages_cfg is not None:
        _validate_messages_block(messages_cfg)

def register_environment_hook(func: Callable[[dict], None]):
    """Allow plugins to mutate the environment before base validation."""
    _ENVIRONMENT_HOOKS.append(func)
    return func

def register_entity_hook(entity_type: str, func: Callable[[str, dict], None]):
    """Invoke `func(name, cfg)` before each arena/object/agent validation."""
    if entity_type not in _ENTITY_HOOKS:
        raise ValueError(f"Unknown entity type '{entity_type}' for hooks")
    _ENTITY_HOOKS[entity_type].append(func)
    return func

def register_arena_shape(shape_id: str, allowed_dimensions: set[str]):
    """Extend the supported arenas and their allowed dimensions."""
    ALLOWED_ARENA_IDS.add(shape_id)
    ARENA_DIMENSION_CONSTRAINTS[shape_id] = set(allowed_dimensions)

def register_object_shape(shape_id: str, allowed_dimensions: set[str]):
    """Extend the supported object shapes and their allowed dimensions."""
    ALLOWED_OBJECT_SHAPES.add(shape_id)
    OBJECT_DIMENSION_CONSTRAINTS[shape_id] = set(allowed_dimensions)

def register_agent_shape(shape_id: str, allowed_dimensions: set[str]):
    """Extend the supported agent shapes and their allowed dimensions."""
    ALLOWED_AGENT_SHAPES.add(shape_id)
    AGENT_DIMENSION_CONSTRAINTS[shape_id] = set(allowed_dimensions)

def register_message_type(name: str):
    """Allow plugins to define custom message flow types."""
    MESSAGE_TYPES.add(name)

def register_message_timer_distribution(name: str):
    """Allow plugins to add new timer distributions to the messages.timer block."""
    MESSAGE_TIMER_DISTRIBUTIONS.add(name)

class Config:
    """Config."""
    def __init__(self, config_path: str = "", new_data: dict = {}):
        """Initialize the instance."""
        if config_path:
            self.config_path = config_path
            self.data = self.load_config()
        elif new_data:
            self.data = new_data
        else:
            raise ValueError("Either config_path or new_data must be provided")

    def load_config(self):
        """Load config."""
        with open(self.config_path, 'r') as file:
            return json.load(file)

    def _expand_entity(self, entity: dict, required_fields: list, optional_fields: list):
        # required field check
        """Expand entity."""
        for field in required_fields:
            if field not in entity:
                raise ValueError(f"Missing required field '{field}' in {entity.get('_id', 'entity')}")
            if field == 'number':
                if not isinstance(entity[field], list):
                    raise ValueError(f"Field '{field}' must be a list in {entity.get('_id', 'entity')}")
                if len(entity[field]) == 0:
                    raise ValueError(f"Field '{field}' must not be empty in {entity.get('_id', 'entity')}")
                for n in entity[field]:
                    if not isinstance(n, int) or n <= 0:
                        raise ValueError(f"All elements in '{field}' must be positive integers in {entity.get('_id', 'entity')}")
        if 'time_delay' in entity:
            td = entity['time_delay']
            if isinstance(td, list):
                if not td:
                    raise ValueError("Optional field 'time_delay' must not be an empty list in {}".format(entity.get('_id', 'entity')))
                for v in td:
                    if not isinstance(v, int) or v < 1:
                        raise ValueError("All elements in optional field 'time_delay' must be integers >= 1 in {}".format(entity.get('_id', 'entity')))
            else:
                if not isinstance(td, int) or td < 1:
                    raise ValueError("Optional field 'time_delay' must be an integer >= 1 in {}".format(entity.get('_id', 'entity')))
        # check on position field
        if 'position' in entity:
            tmp = entity['position']
            if not (isinstance(tmp, list) and all(isinstance(t, list) and len(t) in (2, 3) and all(isinstance(x, (int, float)) for x in t) for t in tmp)):
                raise ValueError(f"Optional field 'position' must be a list of [x, y] o [x, y, z] arrays in {entity.get('_id', 'entity')}")
        # check on orientation field
        if 'orientation' in entity:
            tmp = entity['orientation']
            if not (isinstance(tmp, list) and all(isinstance(t, list) and len(t) in (1, 3) and all(isinstance(x, (int, float)) for x in t) for t in tmp)):
                raise ValueError(f"Optional field 'orientation' must be a list of [z] o [x, y, z] arrays in {entity.get('_id', 'entity')}")
        if 'strength' in entity:
            tmp = entity['strength']
            if not isinstance(tmp, list) and all(isinstance(t, (int,float)) for t in tmp):
                raise ValueError(f"Optional field 'strength' must be a list of int|float in {entity.get('_id', 'entity')}")
        if 'uncertainty' in entity:
            tmp = entity['uncertainty']
            if not isinstance(tmp, list) and all(isinstance(t, (int,float)) for t in tmp):
                raise ValueError(f"Optional field 'strength' must be a list of int|float in {entity.get('_id', 'entity')}")
        list_fields = [f for f in required_fields + optional_fields if f in entity and isinstance(entity[f], list) and f not in ("position","orientation","strength","uncertainty")]
        if not list_fields:
            return [entity]
        values = []
        for f in list_fields:
            v = entity[f]
            if not isinstance(v, list):
                v = [v]
            values.append(v)
        combinations = list(itertools.product(*values))
        expanded = []
        for combo in combinations:
            new_entity = _clone_config_obj(entity)
            for idx, f in enumerate(list_fields):
                new_entity[f] = combo[idx]
            for k in list_fields:
                if isinstance(entity[k], list) and len(entity[k]) == 1:
                    new_entity[k] = entity[k][0]
            expanded.append(new_entity)
        return expanded

    def parse_experiments(self) -> list:
        """Parse experiments."""
        experiments = []
        objects = {}
        agents = {}
        arenas = {}
        try:
            environment = self.data['environment']
        except KeyError:
            raise ValueError("The 'environment' field is required")

        if 'results' in environment:
            _validate_results_block(environment['results'])
        if 'logging' in environment:
            _validate_logging_block(environment['logging'])
        if 'gui' in environment:
            _validate_gui_block(environment['gui'])

        for hook in _ENVIRONMENT_HOOKS:
            hook(environment)

        try:
            for k, v in environment['arenas'].items():
                if k.startswith('arena_'):
                    if '_id' not in v:
                        raise ValueError("Each arena must have an '_id' field")
                    arena_cfg = _clone_config_obj(v)
                    for hook in _ENTITY_HOOKS["arena"]:
                        hook(k, arena_cfg)
                    _validate_arena_cfg(arena_cfg)
                    provided_dims = _populate_dimensions(arena_cfg, shape_key="_id")
                    _enforce_dimension_congruency(arena_cfg, "_id", "arena", k, provided_dims)
                    allowed_dims = ARENA_DIMENSION_CONSTRAINTS.get(arena_cfg["_id"], set())
                    _finalize_dimensions(arena_cfg, allowed_dims)
                    arenas.update({k: arena_cfg})
                else:
                    raise KeyError
        except KeyError:
            raise ValueError("The 'arenas' field is required with dictionary entries 'arena_#'")

        object_required_fields = ['_id', 'number']
        object_optional_fields = [
            'strength', 'uncertainty','position','orientation','hierarchy_node','hierarchy'
        ]
        try:
            for k, v in environment['objects'].items():
                if k.startswith('static_') or k.startswith('movable_'):
                    object_cfg = _clone_config_obj(v)
                    if "spawn" not in object_cfg and isinstance(object_cfg.get("distribute"), dict):
                        object_cfg["spawn"] = _clone_config_obj(object_cfg["distribute"])
                    for hook in _ENTITY_HOOKS["object"]:
                        hook(k, object_cfg)
                    _validate_object_cfg(object_cfg)
                    provided_dims = _populate_dimensions(object_cfg, shape_key="shape")
                    _enforce_dimension_congruency(object_cfg, "shape", "object", k, provided_dims)
                    shape = object_cfg.get("shape")
                    allowed_dims = OBJECT_DIMENSION_CONSTRAINTS.get(shape, set())
                    _finalize_dimensions(object_cfg, allowed_dims)
                    objects[k] = self._expand_entity(object_cfg, object_required_fields, object_optional_fields)
                else:
                    raise KeyError
        except KeyError:
            raise ValueError("The 'objects' field is required with dictionary entries 'static_#' or 'movable_#'")

        agent_required_fields = ['number']
        agent_optional_fields = ['ticks_per_second','position','orientation','hierarchy_node']
        try:
            for k, v in environment['agents'].items():
                if k.startswith('static_') or k.startswith('movable_'):
                    agent_cfg = _clone_config_obj(v)
                    if "spawn" not in agent_cfg and isinstance(agent_cfg.get("distribute"), dict):
                        agent_cfg["spawn"] = _clone_config_obj(agent_cfg["distribute"])
                    if "linear_velocity" not in agent_cfg and "max_linear_velocity" in agent_cfg:
                        agent_cfg["linear_velocity"] = agent_cfg["max_linear_velocity"]
                    if "angular_velocity" not in agent_cfg and "max_angular_velocity" in agent_cfg:
                        agent_cfg["angular_velocity"] = agent_cfg["max_angular_velocity"]
                    for hook in _ENTITY_HOOKS["agent"]:
                        hook(k, agent_cfg)
                    _validate_agent_cfg(agent_cfg)
                    provided_dims = _populate_dimensions(agent_cfg, shape_key="shape")
                    _enforce_dimension_congruency(agent_cfg, "shape", "agent", k, provided_dims)
                    shape = agent_cfg.get("shape")
                    allowed_dims = AGENT_DIMENSION_CONSTRAINTS.get(shape, set())
                    _finalize_dimensions(agent_cfg, allowed_dims)
                    agents[k] = self._expand_entity(agent_cfg, agent_required_fields, agent_optional_fields)
                else:
                    raise KeyError
        except KeyError:
            raise ValueError("The 'agents' field is required with dictionary entries 'static_#' or 'movable_#'")

        if 'gui' in environment:
            if "_id" not in environment['gui']:
                raise ValueError("The '_id' field is required in the gui")

        agent_keys = list(agents.keys())
        object_keys = list(objects.keys())
        agent_combos = list(itertools.product(*[agents[k] for k in agent_keys])) if agent_keys else [()]
        object_combos = list(itertools.product(*[objects[k] for k in object_keys])) if object_keys else [()]
        logging_cfg = environment.get("logging") if "logging" in environment else None

        for arena_key, arena_value in arenas.items():
            for agent_combo in agent_combos:
                for object_combo in object_combos:
                    experiment = {
                        "environment": {
                            "collisions": environment.get("collisions", False),
                            "ticks_per_second": environment.get("ticks_per_second", 3),
                            "time_limit": environment.get("time_limit", 0),
                            "num_runs": environment.get("num_runs", 1),
                            "results": {} if environment.get("gui") else environment.get("results",{}),
                            "gui": environment.get("gui",{}),
                            "arena": arena_value,
                            "objects": {},
                            "agents": {}
                        }
                    }
                    if logging_cfg is not None:
                        experiment["environment"]["logging"] = _clone_config_obj(logging_cfg)
                    for idx, agent_key in enumerate(agent_keys):
                        experiment["environment"]["agents"][agent_key] = agent_combo[idx] if agent_keys else {}
                    for idx, obj_key in enumerate(object_keys):
                        experiment["environment"]["objects"][obj_key] = object_combo[idx] if object_keys else {}
                    experiments.append(Config(new_data=experiment))
        return experiments

    @property
    def environment(self) -> dict:
        """Return the environment configuration."""
        return self.data.get('environment', {})

    @property
    def arenas(self) -> dict:
        """Return the arena configuration."""
        return self.data.get('environment', {}).get('arenas', {})

    @property
    def arena(self) -> dict:
        """Return the arena configuration."""
        return self.data.get('environment', {}).get('arena', {})

    @property
    def objects(self) -> dict:
        """Return the object configuration."""
        return self.data.get('environment', {}).get('objects', {})

    @property
    def agents(self) -> dict:
        """Return the agent configuration."""
        return self.data.get('environment', {}).get('agents', {})

    @property
    def results(self) -> dict:
        """Return the results configuration."""
        return self.data.get('environment', {}).get('results', {})

    @property
    def gui(self) -> dict:
        """Return the GUI configuration."""
        return self.data.get('environment', {}).get('gui', {})
