# CollectiPy for Developers

This document complements `README.md` with implementation details, extension points, and workflows for building on top of CollectiPy.

## Setup

- Python 3.10-3.12 is required. The helper scripts rely on PEP 604 union hints and will refuse older interpreters.
- Create/refresh the virtual environment with `./compile.sh` (or manually with `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`). On Debian/Ubuntu install the matching `python3.x-venv` package if `ensurepip` is missing.
- GUI builds need the X11/GL/audio libraries listed in `README.md`; headless runs do not.
- Run scenarios via `./run.sh` or directly: `python src/main.py -c config/random_wp_test_bounded.json`. Logging and results folders are created inside `environment.logging.base_path` / `environment.results.base_path` when enabled.
- Saving results is disabled while the GUI is active. Leave `environment.gui` empty and provide a non-empty `environment.results` block (for example, add `base_path` or an `agent_specs` entry) to capture traces.

## Project layout

- `config/`: sample JSON configurations; copy and tweak to define new experiments (see `config/random_wp_test_bounded_plugin_ex.json` for a plugin-enabled run that imports `plugins.examples.led_state_plugin`).
- `plugins/`: external plugin package. Includes `plugins/examples/led_state_plugin.py`, a ready-to-use logic plugin that visualizes messaging/handshake activity via the agents' LEDs.
- `src/main.py`: entry point; loads the config, configures logging, imports plugins, builds the environment, and starts the simulation.
- **Core package** (`src/core/`): main implementation split into subpackages:
  - `core.main`: process-level orchestration, split into `environment/` (`Environment`, process wrappers, CPU affinity, agent split), `arena/` (`ArenaFactory`, arena shapes, run loop, object placement) and `entity_manager/` (`EntityManager`).
    - `entity_manager/` modules: `initialize.py` (central agent placement and per-manager seeding), `loop.py` (main manager run loop) and `runtime.py` (the `EntityManager` class).
  - `core.messaging`: `MessageProxy`, `NullMessageProxy`, `MessageServer`, `run_message_server`.
  - `core.detection`: `DetectionProxy`, `DetectionServer`, `run_detection_server`.
  - `core.collision`: `CollisionDetector`.
  - `core.entities`: split into small modules:
    - `base` (Entity base type/UIDs)
    - `objects` (Object/StaticObject/MovableObject)
    - `agents` (Agent/StaticAgent/MovableAgent, messaging/detection hooks, seed helpers)
    - `entity_factory` (EntityFactory to instantiate by type)
    - everything is re-exported by `core.entities`.
  - `core.configuration`: `Config`, `plugin_base`, `plugin_registry`.
  - `core.gui`: Qt/matplotlib GUI factory.
  - `core.util`: logging/data handling, geometry utilities, spatial grid, shapes (`bodies`), hierarchy overlay, and folder helpers.
- `src/models/`: built-in plugins:
  - `movement/` (`random_walk`, `random_way_point`, `spin_model`)
  - `motion/` (`unicycle` integrator)
  - `detection/` (`GPS`, `visual` placeholder)
  - `spin_models/` (`spin_system` backend and `perception_system` used by the `spin_model` movement)
- `compile.sh` / `run.sh`: helper scripts for venv setup and running a selected config.

## Process model (orchestration)

The simulation is decomposed into cooperating processes:

- **Environment** (main) spawns and supervises the others; responsible for logging, config load, plugin import, and CPU affinity.
- **Arena** (per experiment) drives time, places objects and all agents at the start of every run (so the initial poses do not depend on how agents are split across managers), and throttles if the GUI lags. Arena and managers advance in lockstep on simulated time: a manager computes tick `k` once the arena has published a tick at or beyond `k / agent_tps`, and the arena closes tick `j` once every manager has completed `floor(j * agent_tps / arena_tps)` ticks, so the state recorded for an arena tick is exact for any pair of tick rates. Objects are sent with the run-start message; ticks only carry the clock.
- **Managers** (1..N): own a partition of agents; apply the poses received from the arena, run logic/movement, messaging proxy, and detection proxy; send exactly one snapshot per completed tick to the Arena (pose-only stand-ins instead of full shapes when no GUI is attached) and poses to the collision detector.
- **Collision detector** (optional): all-to-all collision resolution across managers, one round per tick; only created when `collisions` is true. It receives the agents' shapes once per run and then only their poses, and processes agents in name order.
- **Message server** (optional): central bus for messages when at least one agent group enables `messages`. Every tick each manager sends one packet with its agents' positions and transmissions; when all managers have reported, the server routes each message to the agents within the sender's `comm_range` (`"inf"` reaches everyone) and answers each manager with what its agents can hear. A message is on air only for that tick; a listening agent decodes one of the simultaneous messages (random pick) and keeps it in its local buffer, where the optional `timer` applies.
- **Detection server** (optional, auto when multiple managers): every tick each manager uploads a lightweight snapshot of its agents; when all managers have reported, the server merges them, filters via `SpatialGrid` and per-agent `detection_range`, and sends each manager the agents visible to it, in name order. Managers wait for the snapshot of the current tick; a single manager builds the same frozen snapshot locally. `detection.snapshot_per_second` can optionally throttle how often the view is refreshed (default: every tick).
- **GUI** (optional): spawned when `environment.gui` is non-empty; receives arena/agent snapshots from managers for rendering/graphs.

All inter-process exchanges are per-tick rounds processed in a canonical order, and servers sleep on their queues instead of polling: with the same config and seed the results are identical whatever the number of manager processes (and therefore on any machine).

Processes that are not required by the current config are not started (e.g., no message server when messaging is unused; no detection server when a single manager is sufficient; no collision process when `collisions` is false; no GUI when disabled).

## Configuration deep dive

Configurations are JSON files. Use the existing files under `config/` as templates.

- **Top-level**: optional `plugins` list (modules auto-imported before parsing) and the required `environment` block.
- **environment**:
  - Core timing/simulation: `collisions`, `ticks_per_second`, `time_limit`, `num_runs`, `snapshot_stride`.
  - Results: `results` with `base_path`, `agent_specs` (`"base"`, `"spin_model"`), `group_specs` (`"graph_messages"`, `"graph_detection"`, `"graphs"`, `"heading"`), `snapshots_per_second`.
  - Logging: `logging` with `base_path`, `level`, `to_file`, `to_console`.
  - GUI: `gui` with optional `_id` (default `2D`), `on_click`, `view`. An empty dict disables rendering.
  - Arenas: `arenas` map with keys starting `arena_` (e.g., `arena_0`). Each arena declares `_id` (`rectangle`, `square`, `circle`, `unbounded`; `abstract` is reserved but not implemented yet), `dimensions`, `color`. The optional `hierarchy` partitioning (`depth`, `branches`, `information_scope`) is not implemented yet: the block is ignored with a warning.
- **objects**: required map of keys starting with `static_` or `movable_`. Each object defines `_id` (`idle` or `interactive`), `shape` (`circle`, `square`, `rectangle`, `sphere`, `cube`, `cylinder`, `none`), `dimensions`, `color`, `strength`, `uncertainty`, optional `spawn` distribution, and optional hierarchy bindings (only flat shapes participate in the overlay/scope).
- **agents**: required map of keys starting with `movable_` or `static_` (static agents never move). Each group defines `ticks_per_second`, `number`, optional `spawn`, geometry (`shape`, `height`, `diameter`, color and velocity limits), behaviours (`motion_model`, `moving_behavior`, optional `fallback_moving_behavior`, optional `logic_behavior`), detection settings, spin-model parameters, messaging config, and optional hierarchy placement.
- **Parser behaviors**:
  - Saving runs only when `environment.results` is non-empty **and** the GUI is disabled; if the block is present but `agent_specs` is omitted, `"base"` is added automatically.
  - `spawn.*` (`distribution` + optional `parameters`) is honored for both agents and objects when positions are not explicitly provided.
  - Message timers (`messages.timer`) expire the messages an agent has stored locally. Lifetimes are in seconds: `fixed` uses `parameters.average`; `uniform` draws in `[min, max]` (`min` defaults to 0, `max` to twice `average`); `gaussian` uses `average` and optional `std` (default `average/3`); `exp` uses `lambda` (rate) or `average`. `avg`/`mean`/`mu`/`value` are accepted as aliases of `average`. Without a timer, stored messages never expire.
  - Agent speed keys `max_linear_velocity` / `max_angular_velocity` are mapped internally to runtime fields and scaled by `ticks_per_second`; legacy `linear_velocity` / `angular_velocity` inputs are rejected.
- **Spawning**:
  - Default spawn uses center `[0, 0]` and an inferred radius; override via `spawn.center`, `spawn.radius`, `spawn.distribution` (`uniform`|`gaussian`|`exp`).
  - Bounded arenas default to the inradius when `r` is omitted; the sampled disk is clamped to the footprint while avoiding walls/objects/agents.
  - Unbounded arenas use half of the arena `diameter` (default 1) as spawn radius when `spawn.radius` is omitted.
  - Groups sharing a center share the spawn area and rely on per-entity overlap checks. Groups with different centers whose disks overlap heavily (center distance below 70% of the summed radii) have the later center shifted away once; after 200 failed attempts an agent is placed at the last sample and a warning is logged.

The full commented schema lives in `README.md` under "Config.json Example".

### Extra fields not shown in the user README

- **Global/environment**:
  - `plugins` (both top-level and `environment.plugins`): list of modules auto-imported before parsing.
  - `quiet` (bool): suppresses CLI tick printing in headless runs.
  - `auto_agents_per_proc_target` (int, optional): agents per manager process. When omitted a workload heuristic is used (6 with spin models, 10 with messaging or fast detection, 20 otherwise). A value at least as large as the population keeps everything in one process; in any case at most 8 manager processes are started, fewer on machines with few cores.
  - GUI backpressure: `gui.max_backlog` (alias of `gui.throttle.max_backlog`), `gui.poll_interval_ms` (alias of `gui.throttle.poll_interval_ms`), and `gui.adaptive_throttle` (alias of `gui.throttle.enabled`) let you pause the simulation loop when the GUI queue grows too much (defaults: enabled, backlog 6, poll interval 8 ms).
  - `snapshot_stride` (already in the schema): also passed to managers to thin collision snapshots.
- **Spawn/placement aliases**:
- `distribute` is accepted as an alias of `spawn` for agents/objects.
- `position` / `orientation`: lists of explicit poses (objects and agents) instead of sampled spawn; each entry must be `[x, y]` or `[x, y, z]` for position and `[z]` or `[x, y, z]` for orientation. The entries are applied in creation order (extras are ignored, missing entities fall back to the spawn/orientation logic) and these lists are not part of the Cartesian expansion that generates multiple experiments.
- **Objects**:
  - `strength` / `uncertainty` accept lists; a single-value list is broadcast to all instances of that object type.
- **Agents**:
  - Velocity limits: use `max_linear_velocity` and `max_angular_velocity` (scaled by `ticks_per_second`).
  - Detection range fallbacks: `detection.range` or `detection.distance`, legacy `detection_settings.range|distance`, or `perception_distance` are all honored; `inf`/`infinite` strings allow unlimited range.
  - Detection frequency keys: `detection.acquisition_per_second` (preferred, default 1) plus aliases `acquisition_frequency`, `acquisition_rate`, `frequency`; `inf` for one sample per tick.
  - Messaging rate aliases: `send_message_per_seconds` / `send_message_per_second` and `receive_message_per_seconds` / `receive_message_per_second`.
  - Messaging extras: `rebroadcast_steps`, `handshake_auto` (default true), `handshake_timeout` (seconds) and the `timer` block described above. `bus` and `delete_trigger` are stored on the agent but not used by the core yet.
  - Information scope overrides (`information_scope` / `info_restrictions` at the agent level) belong to the hierarchy feature and have no effect yet.
  - Behaviour knobs used by built-ins: `crw_exponent` and `levy_exponent` influence the random walk (turning and forward durations use the fixed constants `max_turning_ticks` / `standard_motion_steps` set in `MovableAgent`); `task` is stored on the agent for plugins to consume (for example, the
    ``spin_model`` movement plugin uses the task value to pick either the
    plain or ``_flocking`` spin system backend).
- **Hierarchy helpers**:
  - Not implemented yet: `hierarchy_node` on agents/objects and the arena `hierarchy`/`information_scope` definition are parsed but have no effect.

## Data and logging

- Base results live under `environment.results.base_path`, in one folder per experiment containing `config.json` and one `run_<n>.zip` archive per run. When logging is enabled with `to_file=true`, `main.py` also writes the resolved config copy under the session log folder.
- Each archive holds one pickle per agent, named after the agent UID (`<group>.<letter>#<idx>.pkl`, e.g. `movable_0.m#3.pkl`): a header record followed by one row record per sampled tick, each row a dict with `tick`, `pos x`, `pos y`, `pos z`, `orientation_z`. When `"spin_model"` is requested, `<uid>_spins.pkl` adds the spin payloads.
- Group specs write detection/message adjacency snapshots as `graphs/<mode>/step_<tick>.pkl`, zipped into `{mode}_graphs.zip` inside the run archive; `"heading"` adds `group_heading.csv` with the circular mean heading of each group.
- Snapshots default to once per simulated second; set `snapshots_per_second: 2` to add mid-second captures. Tick `0` and the last tick are always stored.
- Example loader:

```python
import pickle, pandas as pd

import zipfile

rows = []
with zipfile.ZipFile("run_1.zip") as archive, archive.open("run_1/movable_0.m#0.pkl") as fh:
    while True:
        try:
            entry = pickle.load(fh)
        except EOFError:
            break
        if entry.get("type") == "row":
            rows.append(entry["value"])
df = pd.DataFrame(rows)
```

## Plugins and extension points

Movement, motion, logic, detection models, and message buses are resolved through registries in `plugin_registry.py`. Modules listed in the top-level `plugins` or `environment.plugins` arrays are imported before parsing so they can register new models or hooks.

```python
# plugins/my_movement.py
from core.configuration.plugin_registry import register_movement_model

class MyMovement:
    def __init__(self, agent):
        self.agent = agent

    def step(self, agent, tick, arena_shape, objects, agents):
        ...

register_movement_model("my_movement", lambda agent: MyMovement(agent))
```

Agents can opt in via `"moving_behavior": "my_movement"` in the config; an unknown `moving_behavior`, `logic_behavior` or `fallback_moving_behavior` stops the run with the list of registered names. Similar helpers exist for `register_detection_model`, `register_logic_model`, and `register_motion_model`. `register_message_bus` already exists in the registry, but the core does not select buses from it yet.

CollectiPy ships with `plugins/examples/led_state_plugin.py`, a logic plugin that tints each agent's LED according to ongoing messaging and handshake activity. Import that module (see `config/random_wp_test_bounded_plugin_ex.json`) and set `"logic_behavior": "led_state"` on an agent group to reproduce the demo.

Config parsing can also be extended by registering hooks in `config.py`:

```python
from core.configuration import config

@config.register_environment_hook
def enable_magic_logging(environment):
    environment.setdefault("logging", {}).setdefault("level", "DEBUG")

config.register_agent_shape("custom_prism", {"height", "width", "depth"})
```

## Development workflow tips

- Keep sample configs under `config/` and point `run.sh` (or a direct `python src/main.py -c <cfg>`) at them. Use a headless config when you need reproducible traces or batch runs.
- When capturing results, ensure `environment.results` is set to a non-empty object (e.g., include `base_path` or specs) and `environment.gui` is empty; otherwise the simulator prioritizes rendering over persistence.
- If you add plugins, list their module paths in the config so they are auto-imported on startup. Keep plugin code under `plugins/` to avoid altering core modules.

### Batch / grid expansion

- Multiple arenas (`arena_0`, `arena_1`, …) generate one experiment each.
- For every arena, list-valued scalar fields on agent/object groups (except `position`, `orientation`, `strength`, `uncertainty`) are expanded with a Cartesian product. Examples: `number: [2, 5]`, `ticks_per_second: [3, 6]`, `motion_model: ["unicycle", "random_walk"]`.
- Object groups behave the same (`number`, etc.); `strength` and `uncertainty` are per-instance lists and are never expanded.
- The expanded experiments run sequentially; `environment.num_runs` repeats each one deterministically (unless you randomise seeds).
