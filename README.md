# Decision Making Simulation Framework

CollectiPy is a minimal sandbox for decision-making experiments. It keeps the physics simple and focuses on agent reasoning, arenas, GUI helpers, and data exports. You can disable the GUI, extend movement/detection logic with plugins, or add custom arenas.

## Quick Start

```bash
git clone https://github.com/tuo-utente/CollectiPy.git
cd CollectiPy
chmod +x compile.sh run.sh
./compile.sh
./run.sh
```

Edit `run.sh` to point to the config you want to run; the DEFAULT is one of the demos in `config/`.

## Project Structure

- **config/**: Provides the methods to handle the json configuration file.
- **environment/**: Manages the parallel processing of the siumulations.
- **arena/**: Contains custom arenas where simulations take place. Users can create their own arenas by extending the base classes provided (rectangle/circle/square and the unbounded square preview).
- **entityManager/**: Manages the simulation of agents deployed in the arena.
- **entity/**: Houses the definitions for various entities such as agents, objects, and highlighted areas within the arena.
- **gui/**: Includes base classes for the graphical user interface. The GUI can be enabled or disabled based on usage.
- **dataHandling/**: Provides classes and methods for storing and managing simulation data in a predefined format. It can be enabled or disabled based on user preference.
- **models/movement/**: Built-in movement plugin implementations (random walk, random waypoint, spin model).
- **models/motion/**: Kinematic/motion models (DEFAULT unicycle integrator; extendable via plugins).
- **models/detection/**: Built-in perception/detection plugins (GPS plus placeholders for future visual processing).
- **plugin_base.py / plugin_registry.py**: Define the plugin protocols (movement, logic, detection) and runtime registries.
- **logging_utils.py**: Helper utilities to configure the logging system from the JSON config.
- **plugins/**: Top-level folder (sibling of `src/`) meant for external user plugins; modules placed here can be referenced from the config.
- **collision_detection**: Contains the logic to handle entity collision.
- **hierarchy_overlay**: Describe a hierarchy overlay that can be placed over the arena or flat objects(walkable).
- **message_server / message_proxy**: Structure allowing message exchange between agents.

## Usage

Give execution permission to `compile.sh` and `run.sh` (e.g., `chmod +x compile.sh run.sh`). Run `./compile.sh` to install the requirements and `./run.sh` to launch the selected config.

## GUI controls (current draft)

- Start/Stop: space or the Start/Stop buttons
- Step: `E` or the Step button
- Reset: `R` or the Reset button
- Graphs window: `G` or the dropdown in the header
- Zoom: `+` / `-` (also Ctrl+ variants); pan with `W/A/S/D`, arrows, or right mouse drag
- Restore view: `V` or the Restore button (also clears selection/locks)
- Centroid: `C` or the Centroid button; double-click to lock/unlock on the centroid
- Agent selection: click agents in arena or graph; double-click locks the camera on that agent
- Playback slider: a horizontal slider beside the header controls lets you slow the simulation without pausing; it now reports a multiplier between `1.0x` and `2.0x` with `0.05x` resolution (mapped to `("speed", value)` over `[1,2]`) so the arena can insert `tick_interval * (value - 1)` seconds between ticks while keeping the managers synchronized (`src/gui.py`, `src/arena.py`).

## Config.json Example

```json
{
"environment":{
    "collisions": bool, //DEFAULT:false,
    "ticks_per_second": int, //DEFAULT:3,
    "time_limit": int, //DEFAULT:0(inf),
    "num_runs": int, //DEFAULT:1,
    "snapshot_stride": int, //DEFAULT:1 when collisions are enabled (how many ticks to wait between collision snapshots; higher values reduce CPU but weaken obstacle enforcement),
    "results":{ //DEFAULT:{} empty dict -> no saving. If rendering is enabled -> no saving,
        "base_path": str, //DEFAULT:"../data/" (only used when this block is present; does not enable dumps by itself),
        "agent_specs": list(str) //DEFAULT:[] - enable per-agent exports:
            "base" // stream sampled [tick, x, y, z] positions for every agent (adds the current hierarchy node when a hierarchy is configured)
            "spin_model", // append spin-system payloads alongside the base rows.
        "group_specs": list(str) //DEFAULT:[] - enable aggregated exports:
            "graph_messages"|"graph_detection" // adjacency snapshots for the selected channel
            "graphs", // shorthand enabling both message/detection graphs
        "snapshots_per_second": int, //DEFAULT:1 (1 = end-of-second only, 2 = mid-second + end-second captures).
    },
    "logging":{ //DEFAULT:{} default logging
        "base_path": str, //DEFAULT:"../logs/" (only used when this block is present; does not enable dumps by itself),
        "level": str, //DEFAULT:"WARNING" - severity used for all active handlers,
        "to_file": bool, //DEFAULT:false - emit compressed ZIP logs,
        "to_console": bool, //DEFAULT:false - mirror logs on stdout/stderr,
    },
    "gui":{ //DEFAULT:{} empty dict -> no rendering
        "_id": str, //DEFAULT:"2D"
        "on_click": list(str) "messages"|"detection"|"spins", //DEFAULT:None shows nothing on click
        "view": list(str) "messages"|"detection", //DEFAULT:None //DEFAULT shows nothing in the side column
    },
    "arenas":{ //REQUIRED can define multiple arena to simulate sequentially
    "arena_0":{
        "random_seed": int, //DEFAULT:random
        "_id": str, //REQUIRED - SUPPORTED:"rectangle","square","circle","abstract","unbounded". Abstract arena is a special class where ranges and velocities do not apply.
        "dimensions": dict, //DEFAULT: standard dict with height width radius and diamter assigned to 1 if present depending on "_id". For "_id":"unbounded" apply dimeter and radius
        "color": "gray", //DEFAULT:white
        "hierarchy": { //OPTIONAL - define the reversed-tree partition applied to this arena
            "depth": int, //DEFAULT:0 - number of additional levels (root is level 0)
            "branches": int, //DEFAULT:1 - 1 disables the partitioning, 2 splits each cell in half along the widest axis, 4 creates a 2x2 grid per node,
            "information_scope": { //OPTIONAL - hierarchy-aware visibility rules
                "mode": "node"|"branch"|"tree", //DEFAULT: disabled. When set to "node" the agent can only exchange detection/messages with entities in the same node or branch or full tree.
                "direction": "up"|"down"|"both"|"flat", //DEFAULT:"both", only for "branch"|"tree" mode. "flat" allows the agent to interact with the current node plus nodes at same level at same branch or tree.
                "on":list(str) "messages"|"detection"|"move", //DEFAULT:[None] resctrinctions can apply simultaneously over different actions.
                }
            }
        }
    },
    "objects":{ //REQUIRED can define multiple objects to simulate in the same arena
        "static_0":{
            "number": list(int), //DEFAULT:[1] each list's entry will define a different simulation
            "distribute":{ //OPTIONAL - set spawning distribution
                "center":list(float), //DEFAULT [0,0]
                "radius":flaot, //DEFAULT auto - the arena radius if bounded, precomputed if unbounded.
                "distribution":"uniform"|"gaussian"|"exp", //DEFAULT "uniform"
                "parameters":{"name":float} //DEFAULT {}, "name" can be (default=0),"max"(default=1) for ranges or others. What missing if needed is set to default values
            },
            "_id": str, //REQUIRED - SUPPORTED:idle|interactive
            "shape": str, //REQUIRED - SUPPORTED:circle,square,rectangle,sphere,cube,cylinder,none flat geometry can be used to define walkable areas in the arena
            "dimensions": dict, //DEFAULT: standard dict with height width radius and diamter assigned to 1 if present depending on shape
            "color": str, //DEFAULT:"black"
            "strength": list(float), //DEFAULT:[10] one entry -> assign to all the objects the same value. Less entries tha objects -> missing values are equal to the last one
            "uncertainty": list(float), //DEFAULT:[0] one entry -> assign to all the objects the same value. Less entries tha objects -> missing values are equal to the last one
            "hierarchy_node": str, //OPTIONAL - bind the object to a specific arena hierarchy node (e.g. "0.1.0")
            "hierarchy": { //OPTIONAL - define the reversed-tree partition applied to this arena
                "depth": int, //DEFAULT:0 - number of additional levels (root is level 0)
                "branches": int, //DEFAULT:1 - 1 disables the partitioning, 2 splits each cell in half along the widest axis, 4 creates a 2x2 grid per node,
                "information_scope": { //OPTIONAL - hierarchy-aware visibility rules
                    "mode": "node"|"branch"|"tree", //DEFAULT: disabled. When set to "node" the agent can only exchange detection/messages with entities in the same node or branch or full tree.
                    "direction": "up"|"down"|"both"|"flat", //DEFAULT:"both", only for "branch"|"tree" mode. "flat" allows the agent to interact with the current node plus nodes at same level at same branch or tree.
                    "on":list(str) "messages"|"detection"|"move", //DEFAULT:[None] resctrinctions can apply simultaneously over different actions.
                    }
                }
            }
        }
    },
    "agents":{ //REQUIRED can define multiple agents to simulate in the same arena
        "movable_0":{
            "ticks_per_second": int, //DEFAULT:5
            "number": list(int), //DEFAULT:[1] each list's entry will define a different simulation
            "distribute":{ //OPTIONAL - set spawning distribution
                "center":float, //DEFAULT (0,0)
                "radius":flaot, //DEFAULT auto
                "distribution": str "uniform"|"gaussian"|"exp", //DEFAULT "uniform"
                "parameters":{"name":float} //DEFAULT {} can be "min"(default=0),"max"(default=1) for ranges or others like "avg","alpha",etc... What missing if needed is set to default values
            },
            "shape": str, //SUPPORTED:"sphere","cube","cylinder","none"
            "max_linear_velocity": float, //DEFAULT:0.01 m/s
            "max_angular_velocity": float, //DEFAULT:10 deg/s
            "height": float,
            "diameter": float,
            "color": str, //DEFAULT:"blue"
            "motion_model": str, //DEFAULT:"unicycle" - Kinematic model used to integrate motion commands (pluggable; see plugins section).
            "detection":{ //DEFAULT:{} - extendable object similar to `messages`
                "type": str, //DEFAULT:"GPS" - Detection plugin resolved via `models/detection` (custom modules supported).
                "range": float|"inf", //DEFAULT:0.1 - Limit how far perception gathers targets (alias: "distance").
                "acquisition_per_second": float, //DEFAULT:1 (= once per second) - Sampling frequency expressed as Hz; determines how often detection snapshots run relative to the agent tick rate. "inf" is used for max (once per tick)
            },
            "moving_behavior":str, //DEFAULT:"random_walk" - Any movement plugin registered in the system (`random_walk`, `random_way_point`, `spin_model`, or a custom module).
            "fallback_moving_behavior": str, //DEFAULT:"none" - Movement model used when the main plugin cannot produce an action (e.g., spin model without perception).
            "logic_behavior": str, //DEFAULT:None - //OPTIONAL logic plugin executed before the movement plugin (placeholder for future reasoning modules).
            "hierarchy_node": str, //OPTIONAL - desired hierarchy node for the agent (used by the hierarchy confinement plugin). //DEFAULTs to the root ("0") if omitted.
            "spin_model":{ //DEFAULT:{} empty dict -> //DEFAULT configuration
                "spin_per_tick": int, //DEFAULT:3
                "spin_pre_run_steps": int, //DEFAULT:0 //DEFAULT value avoid pre run steps
                "perception_width": float, //DEFAULT:0.5
                "num_groups": int, //DEFAULT:8
                "num_spins_per_group": int, //DEFAULT:5
                "perception_global_inhibition": int, //DEFAULT:0
                "T": float, //DEFAULT:0.5
                "J": float, //DEFAULT:1
                "nu": float, //DEFAULT:0
                "p_spin_up": float, //DEFAULT:0.5
                "time_delay": int, //DEFAULT:1
                "reference": str, //DEFAULT:"egocentric"
                "dynamics": str //DEFAULT:"metropolis"
            },
            "messages":{  //DEFAULT:{} empty dict -> no messaging
                "tx": int, //DEFAULT:2  send_per_seconds
                "comm_range": float|"inf", //DEFAULT:0.1
                "type": str "broadcast"|"rebroadcast"|"hand-shake", //DEFAULT:"broadcast"
                "kind": str "anonymous"|"id-aware", //DEFAULT:"anonymous"
                "channels": str "single"|"dual", //DEFAULT:"dual"
                "rx": int, //DEFAULT:4  receive_per_seconds
                "rebroadcast_steps": int|"inf", //DEFAULT:"inf". ONLY IF type is "rebroadcast" (agent-side limit on how many times a packet can be forwarded from the local buffer)
                "handshake_auto": bool, //DEFAULT:true. ONLY IF type is "hand-shake". broadcast discovery invitations whenever idle.
                "handshake_timeout": float, //DEFAULT:5 seconds before a silent partner is droppe.
                "timer": { //OPTIONAL - configure automatic message expiration inside each agent buffer - DEFAULT:{} messages do not expire
                    "distribution": str "fixed"|"uniform"|"exp", //DEFAULT:"fixed")
                    "parameters": dict {"name":float,...} //DEFAULT {}, "name" can be (default=0),"max"(default=1) for ranges or others like "avg","alpha",etc... What missing if needed is set to default values
                }
            }
        }
    }
}
```

### Arena, Objects and Agents ruleset

Arenas field must always be there, arena fileds inside it must always start with "arena_" and end with "_X" univocous.
Objects and Agents apply the same rule nut they must contain "agent_" in abstract arenas and "movable_" or "static_" otherwise.

### Agent spawning

- DEFAULT spawn center `c = [0, 0]` and radius `r` can be overridden per agent group via `spawn.center` / `spawn.radius` / `spawn.distribution` (`uniform` | `gaussian` | `exp`, DEFAULT `uniform`). Agents/sample logic can also mutate these at runtime.
- Bounded arenas: if `r` is not provided, it DEFAULTs to the inradius of the arena footprint. The sampled area is clamped to the arena; if the requested circle exceeds the bounds it is truncated to fit. Placement still respects non-overlap with walls, objects, and other agents.
- Unbounded arenas: if `r` is missing/invalid, a finite radius is inferred from agent count/size so that all requested agents fit in a reasonable square. Sampling uses the chosen distribution around `c` without wrap-around.
- Multiple groups sharing the same spawn center: the second (and subsequent) groups are shifted away by at least `0.25 * r`, repeated until a non-overlapping placement is found or attempts are exhausted. If spawn disks do not touch and placement still fails, the init aborts with an error (attempt limit unchanged).

### Data

Raw traces saved under `environment.results.base_path` obey the spec lists declared in `results.agent_specs` / `results.group_specs`. When an arena hierarchy is configured, each base row also includes the hierarchy node where the agent currently sits so downstream analysis can group by partition. Per-agent pickles (`<group>_<idx>.pkl`) are emitted only when `"base"` is present (sampled `[tick, pos x, pos y, pos z]` rows) and can //OPTIONALly append `"spin_model"` dumps (`<group>_<idx>_spins.pkl`). Snapshots are taken once per simulated second by DEFAULT (after the last tick in that second); setting `snapshots_per_second: 2` adds a mid-second capture. Tick `0` is always stored so consumers see the initial pose, and the very last tick is forced even if it does not align with the cadence. Group specs apply to global outputs: `"graph_messages"` / `"graph_detection"` write one pickle per tick under `graphs/<mode>/step_<tick>.pkl`, and the helper spec `"graphs"` enables both. Message edges require that the transmitter has range and a non-zero TX budget **and** the receiver advertises a non-zero RX budget; detection edges only appear when the sensing agent has a non-zero acquisition rate in addition to range. All per-step graph pickles are zipped into `{mode}_graphs.zip` at the end of the run, and finally the whole `run_<n>` folder is compressed so analysis scripts can ingest the pickles while storage stays compact.

### Config extensions

Plugins can extend or alter the default parsing rules in `src/config.py` by importing the helper functions and registering hooks before the main config is loaded. Available APIs include `register_environment_hook` (for mutating `environment` before validation), `register_entity_hook` (runs before each arena/object/agent validation), `register_arena_shape`, `register_object_shape`, `register_agent_shape` (to declare new allowable shape IDs and their dimension keys), and `register_message_type` / `register_message_timer_distribution` (to support custom message flows). Example:

```python
from src import config

@config.register_environment_hook
def enable_magic_logging(environment):
    environment.setdefault("logging", {}).setdefault("level", "DEBUG")

config.register_agent_shape("custom_prism", {"height", "width", "depth"})
```

The new entries run before `Config.parse_experiments` validates the JSON, so plugins can safely inject additional structures or override defaults while still benefiting from the built-in normalization.

Each pickle is structured for quick DataFrame ingestion: the first record is a header carrying a `columns` list, and all subsequent `{"type": "row"}` entries are dictionaries keyed by those columns. Base traces expose `tick`, `pos x`, `pos y`, `pos z` (plus `hierarchy_node` when enabled). Spin dumps include `tick` and the spin-model fields (`states`, `angles`, `external_field`, `avg_direction_of_activity`). Graph pickles ship `columns: ["source", "target"]` with rows using those keys. Example loader:

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
