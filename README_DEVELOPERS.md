# CollectiPy for Developers

This document complements `README.md` with implementation details, extension points, and workflows for building on top of CollectiPy.

## Setup

- Python 3.10-3.12 is required. The helper scripts rely on PEP 604 union hints and will refuse older interpreters.
- Create/refresh the virtual environment with `./compile.sh` (or manually with `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`). On Debian/Ubuntu install the matching `python3.x-venv` package if `ensurepip` is missing.
- GUI builds need the X11/GL/audio libraries listed in `README.md`; headless runs do not.
- Run scenarios via `./run.sh` or directly: `python src/main.py -c config/random_wp_test_bounded.json`. Logging and results folders are created inside `environment.logging.base_path` / `environment.results.base_path` when enabled.
- Saving results is disabled while the GUI is active. Leave `environment.gui` empty and set `environment.results` to capture traces.

## Project layout

- `config/`: sample JSON configurations; copy and tweak to define new experiments.
- `plugins/`: external plugin package. Includes `plugins/examples/group_stats_plugin.py` as a ready-to-use logic plugin.
- `src/main.py`: entry point; loads the config, configures logging, imports plugins, builds the environment, and starts the simulation.
- **Core package** (`src/core/`): main implementation split into subpackages:
  - `core.processes`: `Environment`, `EntityManager`, `ArenaFactory` plus hierarchy overlays and process launch helpers.
    - `entity_manager/` helpers: `init.py` (placement/seeding) and `loop.py` (main manager run loop), used by `EntityManager` for readability.
  - `core.messaging`: `MessageProxy`, `NullMessageProxy`, `MessageServer`, `run_message_server`.
  - `core.detection`: `DetectionProxy`, `DetectionServer`, `run_detection_server`.
  - `core.collision`: `CollisionDetector`.
  - `core.entities`: split into small modules:
    - `base` (Entity base type/UIDs)
    - `objects` (Object/StaticObject/MovableObject)
    - `agents` (Agent/StaticAgent/MovableAgent, messaging/detection hooks, seed helpers)
    - `entity_factory` (EntityFactory to instantiate by type)
    - imports remain available via `core.entities` and the wrapper `src/entity.py`.
  - `core.configuration`: `Config`, `plugin_base`, `plugin_registry`.
  - `core.gui`: Qt/matplotlib GUI factory.
  - `core.util`: logging/data handling, geometry utilities, spatial grid, shapes (`bodies`), hierarchy overlay, and folder helpers.
- `src/*.py` wrappers: compatibility shims re-exporting the core modules (`config`, `environment`, `arena`, `entityManager`, `message_*`, `detection_*`, `collision_detector`, `logging_util`, `dataHandling`, etc.) for legacy imports.
- `src/models/`: built-in plugins:
  - `movement/` (`random_walk`, `random_way_point`, `spin_model`)
  - `motion/` (`unicycle` integrator)
  - `detection/` (`GPS`, `visual` placeholder)
- `compile.sh` / `run.sh`: helper scripts for venv setup and running a selected config.

## Process model (orchestration)

The simulation is decomposed into cooperating processes:

- **Environment** (main) spawns and supervises the others; responsible for logging, config load, plugin import, and CPU affinity.
- **Arena** (per experiment) drives time, sends object state to managers and optional detector, throttles if the GUI lags.
- **Managers** (1..N): own a partition of agents; run logic/movement, messaging proxy, and detection proxy; push snapshots to Arena and collision detector.
- **Collision detector** (optional): asynchronous, all-to-all collision resolution across managers; only created when `collisions` is true.
- **Message server** (optional): central bus for messages when at least one agent group enables `messages`.
- **Detection server** (optional, auto when multiple managers): aggregates lightweight agent snapshots, filters via `SpatialGrid` and per-agent `detection_range`, broadcasts visibility-reduced snapshots back to managers. Managers pull at `detection.snapshot_per_second` (default 3 Hz) while uploads happen every manager tick.
- **GUI** (optional): spawned when `environment.gui` is non-empty; receives arena/agent snapshots from managers for rendering/graphs.

Processes that are not required by the current config are not started (e.g., no message server when messaging is unused; no detection server when a single manager is sufficient; no collision process when `collisions` is false; no GUI when disabled).

## Configuration deep dive

Configurations are JSON files. Use the existing files under `config/` as templates.

- **Top-level**: optional `plugins` list (modules auto-imported before parsing) and the required `environment` block.
- **environment**:
  - Core timing/simulation: `collisions`, `ticks_per_second`, `time_limit`, `num_runs`, `snapshot_stride`.
  - Results: `results` with `base_path`, `agent_specs` (`"base"`, `"spin_model"`), `group_specs` (`"graph_messages"`, `"graph_detection"`, or `"graphs"`), `snapshots_per_second`.
  - Logging: `logging` with `base_path`, `level`, `to_file`, `to_console`.
  - GUI: `gui` with optional `_id` (default `2D`), `on_click`, `view`. An empty dict disables rendering.
  - Arenas: `arenas` map with keys starting `arena_` (e.g., `arena_0`). Each arena declares `_id` (`rectangle`, `square`, `circle`, `abstract`, `unbounded`), `dimensions`, `color`, and optional `hierarchy` partitioning (`depth`, `branches`, `information_scope`).
- **objects**: required map of keys starting with `static_`. Each object defines `_id` (`idle` or `interactive`), `shape` (`circle`, `square`, `rectangle`, `sphere`, `cube`, `cylinder`, `none`), `dimensions`, `color`, `strength`, `uncertainty`, optional `spawn` distribution, and optional hierarchy bindings (only flat shapes participate in the overlay/scope).
- **agents**: required map of keys starting with `movable_`. Each group defines `ticks_per_second`, `number`, optional `spawn`, geometry (`shape`, `height`, `diameter`, color and velocity limits), behaviours (`motion_model`, `moving_behavior`, optional `fallback_moving_behavior`, optional `logic_behavior`), detection settings, spin-model parameters, messaging config, and optional hierarchy placement.
- **Parser behaviors**:
  - Saving runs only when `environment.results` is non-empty **and** the GUI is disabled; if the block is present but `agent_specs` is omitted, `"base"` is added automatically.
  - `spawn.*` (`distribution` + optional `parameters`) is honored for both agents and objects when positions are not explicitly provided.
  - Message timers accept a `parameters` dict (`average`, `max`, `lambda`, `mean`/`mu` are supported depending on distribution).
  - Agent speed keys `max_linear_velocity` / `max_angular_velocity` are mapped internally to runtime fields and scaled by `ticks_per_second`; legacy `linear_velocity` / `angular_velocity` inputs are rejected.
- **Spawning**:
  - Default spawn uses center `[0, 0]` and an inferred radius; override via `spawn.center`, `spawn.radius`, `spawn.distribution` (`uniform`|`gaussian`|`exp`).
  - Bounded arenas default to the inradius when `r` is omitted; the sampled disk is clamped to the footprint while avoiding walls/objects/agents.
  - Unbounded arenas infer a finite radius so the requested population fits in a reasonable square.
  - When multiple groups share a center, overlapping disks are nudged apart (up to 16 attempts) before falling back to per-entity collision checks.

The full commented schema lives in `README.md` under "Config.json Example".

### Extra fields not shown in the user README

- **Global/environment**:
  - `plugins` (both top-level and `environment.plugins`): list of modules auto-imported before parsing.
  - `quiet` (bool): suppresses CLI tick printing in headless runs.
  - `auto_agents_per_proc_target` (int, default 5): heuristic target agents per manager process used to split work; final cap 5–30 agents per proc and max 8 procs.
  - GUI backpressure: `gui.max_backlog` (alias of `gui.throttle.max_backlog`), `gui.poll_interval_ms` (alias of `gui.throttle.poll_interval_ms`), and `gui.adaptive_throttle` (alias of `gui.throttle.enabled`) let you pause the simulation loop when the GUI queue grows too much (defaults: enabled, backlog 6, poll interval 8 ms).
  - `snapshot_stride` (already in the schema): also passed to managers to thin collision snapshots.
- **Spawn/placement aliases**:
  - `distribute` is accepted as an alias of `spawn` for agents/objects.
  - `position` / `orientation`: lists of explicit poses (objects and agents) instead of sampled spawn; each entry must be `[x, y]` or `[x, y, z]` for position and `[z]` or `[x, y, z]` for orientation.
- **Objects**:
  - `strength` / `uncertainty` accept lists; a single-value list is broadcast to all instances of that object type.
- **Agents**:
  - Velocity limits: use `max_linear_velocity` and `max_angular_velocity` (scaled by `ticks_per_second`).
  - Detection range fallbacks: `detection.range` or `detection.distance`, legacy `detection_settings.range|distance`, or `perception_distance` are all honored; `inf`/`infinite` strings allow unlimited range.
  - Detection frequency keys: `detection.acquisition_per_second` (preferred) plus aliases `acquisition_frequency`, `acquisition_rate`, `frequency`; `inf` for one sample per tick.
  - Messaging rate aliases: `send_message_per_seconds` / `send_message_per_second` and `receive_message_per_seconds` / `receive_message_per_second`.
  - Messaging extras: `rebroadcast_steps` (with legacy alias `rebroadcast_hops`), `delete_trigger` (custom bus-specific hint), `handshake_auto` (default true), `handshake_timeout` (seconds), and `timer.reset_each_cycle` (boolean to drop TTLs every tick). Timer averages can be inferred from `parameters.average|avg|mean|mu|max|lambda|rate|value` if `average` is omitted.
  - Information scope overrides: `information_scope` or `info_restrictions` at the agent level mirror the arena hierarchy rules to gate detection/messages/move by hierarchy nodes (see `_allowed_nodes_for_channel` in `entity.py`).
  - Behaviour knobs used by built-ins: `crw_exponent`, `levy_exponent`, `max_turning_ticks`, `standard_motion_steps` influence random-walk models; `task` is stored on the agent for plugins to consume.
- **Hierarchy helpers**:
  - Agents accept `hierarchy_node` to attach to the arena overlay; arenas own the `hierarchy`/`information_scope` definition. Flat objects (circle/square/rectangle) can also carry a `hierarchy_node` and optional scope, and are the only objects shown in the hierarchy overlay.

## Data and logging

- Base results live under `environment.results.base_path` (one `run_<n>` folder per run). When logging is enabled with `to_file=true`, `main.py` also writes the resolved config copy under the session log folder.
- Per-agent pickles (`<group>_<idx>.pkl`) emit sampled `[tick, pos x, pos y, pos z]` rows and, when `"spin_model"` is requested, `<group>_<idx>_spins.pkl` adds spin payloads.
- Group specs write detection/message adjacency snapshots under `graphs/<mode>/step_<tick>.pkl` and zip them into `{mode}_graphs.zip`; the entire run folder is zipped at the end.
- Snapshots default to once per simulated second; set `snapshots_per_second: 2` to add mid-second captures. Tick `0` and the last tick are always stored.
- Example loader:

```python
import pickle, pandas as pd

rows = []
with open("run_0/agent_0.pkl", "rb") as fh:
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
from plugin_registry import register_movement_model

class MyMovement:
    def __init__(self, agent):
        self.agent = agent

    def step(self, agent, tick, arena_shape, objects, agents):
        ...

register_movement_model("my_movement", lambda agent: MyMovement(agent))
```

Agents can opt in via `"moving_behavior": "my_movement"` in the config. Similar helpers exist for `register_detection_model`, `register_logic_model`, and `register_motion_model`. Message buses can be swapped with `register_message_bus`, returning a `plugin_base.MessageBusModel` implementation.

Config parsing can also be extended by registering hooks in `config.py`:

```python
import config

@config.register_environment_hook
def enable_magic_logging(environment):
    environment.setdefault("logging", {}).setdefault("level", "DEBUG")

config.register_agent_shape("custom_prism", {"height", "width", "depth"})
```

## Development workflow tips

- Keep sample configs under `config/` and point `run.sh` (or a direct `python src/main.py -c <cfg>`) at them. Use a headless config when you need reproducible traces or batch runs.
- When capturing results, ensure `environment.results` is set and `environment.gui` is empty; otherwise the simulator prioritizes rendering over persistence.
- If you add plugins, list their module paths in the config so they are auto-imported on startup. Keep plugin code under `plugins/` to avoid altering core modules.

### Batch / grid expansion

- Multiple arenas (`arena_0`, `arena_1`, …) generate one experiment each.
- For every arena, list-valued scalar fields on agent/object groups (except `position`, `orientation`, `strength`, `uncertainty`) are expanded with a Cartesian product. Examples: `number: [2, 5]`, `ticks_per_second: [3, 6]`, `motion_model: ["unicycle", "random_walk"]`.
- Object groups behave the same (`strength`, `number`, etc.).
- The expanded experiments run sequentially; `environment.num_runs` repeats each one deterministically (unless you randomise seeds).
