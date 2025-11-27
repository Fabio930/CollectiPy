# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

import json, itertools

def _clone_config_obj(obj):
    """Deep-clone config data without using copy module."""
    return json.loads(json.dumps(obj))

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

        try:
            for k, v in environment['arenas'].items():
                if k.startswith('arena_'):
                    if '_id' not in v:
                        raise ValueError("Each arena must have an '_id' field")
                    arenas.update({k: v})
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
                    objects[k] = self._expand_entity(v, object_required_fields, object_optional_fields)
                else:
                    raise KeyError
        except KeyError:
            raise ValueError("The 'objects' field is required with dictionary entries 'static_#' or 'movable_#'")

        agent_required_fields = ['number']
        agent_optional_fields = ['ticks_per_second','position','orientation','hierarchy_node']
        try:
            for k, v in environment['agents'].items():
                if k.startswith('static_') or k.startswith('movable_'):
                    agents[k] = self._expand_entity(v, agent_required_fields, agent_optional_fields)
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

        for arena_key, arena_value in arenas.items():
            for agent_combo in agent_combos:
                for object_combo in object_combos:
                    experiment = {
                        "environment": {
                            "collisions": environment.get("collisions", False),
                            "ticks_per_second": environment.get("ticks_per_second", 3),
                            "time_limit": environment.get("time_limit", 0),
                            "num_runs": environment.get("num_runs", 1),
                            "results": environment.get("results",{}),
                            "logging": environment.get("logging") or {},
                            "gui": environment.get("gui",{}),
                            "arena": arena_value,
                            "objects": {},
                            "agents": {}
                        }
                    }
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
