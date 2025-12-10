# Decision Making Simulation Framework

CollectiPy is a minimal sandbox for decision-making experiments. It keeps the physics simple and focuses on agent reasoning, arenas, GUI helpers, and data exports. You can disable the GUI, extend movement/detection logic with plugins, or add custom arenas.

This page is for people running the simulator. Developer-oriented details live in `README_DEVELOPERS.md`.

## Quick Start

```bash
git clone https://github.com/Fabio930/CollectiPy.git
cd CollectiPy
chmod +x compile.sh run.sh
./compile.sh
./run.sh
```

Edit `run.sh` to point to the config you want to run; the default is one of the demos in `config/`.

Python 3.10-3.12 required. The codebase uses the `|` union type hints from PEP 604; the helper scripts refuse older 3.x interpreters. On Debian/Ubuntu install the matching `python3.x-venv` package.

## Requirements

### Install GUI minimum requirements

Required system libraries (Debian/Ubuntu). Run as root or prefix with sudo:

```bash
sudo apt update
sudo apt install -y \
    libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render0 libxcb-render-util0 \
    libxcb-shape0 libxcb-shm0 libxcb-xfixes0 libxcb-xinerama0 libxcb-xinput0 libxcb-randr0 \
    libx11-6 libxext6 libxrender1 libxi6 libxcomposite1 libxcursor1 libxdamage1 libxxf86vm1 \
    libxkbcommon-x11-0 libegl1-mesa libglib2.0-0 libfontconfig1 libfreetype6 libdbus-1-3 libasound2
```

These packages are the minimum native graphics/audio/windowing libs needed for the GUI on Debian-based systems.

## Run a scenario

- Ensure the virtual environment exists (`./compile.sh` sets it up; activate with `source .venv/bin/activate` if running commands manually).
- Select the JSON config under `config/` you want to run. `run.sh` ships with several commented options—uncomment one line or invoke directly: `python src/main.py -c config/random_wp_test_bounded.json`.
- To run headless, leave `environment.gui` empty in the config. Results saving is enabled only when `environment.results` is present **and** non-empty (e.g., include `base_path` or a specs key) **and** the GUI is disabled.
- Plugins can be declared via the top-level `plugins` list or `environment.plugins` list in the config (see the developer README for details).

## GUI controls (current draft)

- Start/Stop: space or the Start/Stop buttons
- Step: `E` or the Step button
- Reset: `R` or the Reset button
- Graphs window: `G` or the dropdown in the header
- Zoom: `+` / `-` (also Ctrl+ variants); pan with `W/A/S/D`, arrows, or right mouse drag
- Restore view: `V` or the Restore button (also clears selection/locks)
- Centroid: `C` or the Centroid button; double-click to lock/unlock on the centroid
- Agent selection: click agents in arena or graph; double-click locks the camera on that agent
- Playback slider: a horizontal slider beside the header controls lets you slow the simulation.

## Config.json Example

```json
{
"environment":{
    "collisions": bool, //DEFAULT:false,
    "ticks_per_second": int, //DEFAULT:3,
    "time_limit": int, //DEFAULT:0(inf),
    "num_runs": int, //DEFAULT:1,
    "snapshot_stride": int, //DEFAULT:1 (ticks between collision snapshots; higher values reduce CPU but weaken obstacle enforcement),
    "results":{ //DEFAULT:{} omit the block to disable saving (GUI on also disables saving),
        "base_path": str, //DEFAULT:"./data/" (only used when this block is present; does not enable dumps by itself),
        "agent_specs": list(str) //DEFAULT:[] - enable per-agent exports (when this block is present but specs are omitted, "base" is applied by default):
            "base" // stream sampled [tick, x, y, z] positions for every agent (adds the current hierarchy node when a hierarchy is configured)
            "spin_model" // append spin-system payloads alongside the base rows.
        "group_specs": list(str) //DEFAULT:[] - enable aggregated exports:
            "graph_messages"|"graph_detection" // adjacency snapshots for the selected channel
            "graphs" // shorthand enabling both message/detection graphs
            "heading", // append agent orientation.
        "snapshots_per_second": int, //DEFAULT:1 (1 = end-of-second only, 2 = mid-second + end-second captures).
    },
    "logging":{ //DEFAULT:{} omit the block to disable logging
        "base_path": str, //DEFAULT:"./data/logs/"
        "level": str, //DEFAULT:"WARNING" - severity used for all active handlers,
        "to_file": bool, //DEFAULT:false when the block is present - emit compressed ZIP logs,
        "to_console": bool, //DEFAULT:true - mirror logs on stdout/stderr,
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
        "dimensions": dict, //DEFAULT: standard dict with height width radius and diameter assigned to 1 if present depending on "_id". For "_id":"unbounded" apply diameter and radius
        "color": "gray", //DEFAULT:gray
        "hierarchy": { //OPTIONAL - define the reversed-tree partition applied to this arena
            "depth": int, //DEFAULT:0 - number of additional levels (root is level 0)
            "branches": int, //DEFAULT:1 - 1 disables the partitioning, 2 splits each cell in half along the widest axis, 4 creates a 2x2 grid per node,
            "information_scope": { //OPTIONAL - hierarchy-aware visibility rules
                "mode": "node"|"branch"|"tree", //DEFAULT: disabled. When set to "node" the agent can only exchange detection/messages with entities in the same node or branch or full tree.
                "direction": "up"|"down"|"both"|"flat", //DEFAULT:"both", only for "branch"|"tree" mode. "flat" allows the agent to interact with the current node plus nodes at same level at same branch or tree.
                "on":list(str) "messages"|"detection"|"move", //DEFAULT:[None] restrictions can apply simultaneously over different actions.
                }
            }
        }
    },
    "objects":{ //REQUIRED can define multiple objects to simulate in the same arena
        "static_0":{
            "number": list(int), //DEFAULT:[1] each list entry can drive batch expansion (see Batch runs)
            "spawn":{ //OPTIONAL - set spawning distribution for objects too
                "center":list(float), //DEFAULT [0,0]
                "radius":float, //DEFAULT auto - the arena radius if bounded, heuristically estimated if unbounded
                "distribution":"uniform"|"gaussian"|"exp", //DEFAULT "uniform"
                "parameters":{"name":float} //DEFAULT {} e.g. {"max":1} for uniform radius, {"std":0.1} for gaussian
            },
            "_id": str, //REQUIRED - SUPPORTED:idle|interactive
            "shape": str, //REQUIRED - SUPPORTED:circle,square,rectangle,sphere,cube,cylinder,none flat geometry can be used to define walkable areas in the arena
            "dimensions": dict, //DEFAULT: standard dict with height width radius and diameter assigned to 1 if present depending on shape
            "color": str, //DEFAULT:"black"
            "strength": list(float), //DEFAULT:[10] one entry -> assign to all the objects the same value. Fewer entries than objects -> missing values reuse the last one
            "uncertainty": list(float), //DEFAULT:[0] one entry -> assign to all the objects the same value. Fewer entries than objects -> missing values reuse the last one
            "hierarchy_node": str, //OPTIONAL - bind the object to a specific arena hierarchy node (e.g. "0.1.0")
            "hierarchy": { //OPTIONAL - define the reversed-tree partition applied to this arena
                "depth": int, //DEFAULT:0 - number of additional levels (root is level 0)
                "branches": int, //DEFAULT:1 - 1 disables the partitioning, 2 splits each cell in half along the widest axis, 4 creates a 2x2 grid per node,
                "information_scope": { //OPTIONAL - hierarchy-aware visibility rules
                    "mode": "node"|"branch"|"tree", //DEFAULT: disabled. When set to "node" the agent can only exchange detection/messages with entities in the same node or branch or full tree.
                    "direction": "up"|"down"|"both"|"flat", //DEFAULT:"both", only for "branch"|"tree" mode. "flat" allows the agent to interact with the current node plus nodes at same level at same branch or tree.
                    "on":list(str) "messages"|"detection"|"move", //DEFAULT:[None] restrictions can apply simultaneously over different actions.
                    }
                }
            }
        }
    },
    "agents":{ //REQUIRED can define multiple agents to simulate in the same arena
        "movable_0":{
            "ticks_per_second": int, //DEFAULT:5
            "number": list(int), //DEFAULT:[1] each list entry can drive batch expansion (see Batch runs)
            "spawn":{ //OPTIONAL - set spawning distribution used at init
                "center":list(float), //DEFAULT [0,0]
                "radius":float, //DEFAULT auto (inradius if bounded, heuristically estimated if unbounded)
                "distribution": str "uniform"|"gaussian"|"exp", //DEFAULT "uniform"
                "parameters":{"name":float} //DEFAULT {} e.g. {"max":1} for uniform radius, {"std":0.1} for gaussian
            },
            "shape": str, //SUPPORTED:"sphere","cube","cylinder","none"
            "max_linear_velocity": float, //DEFAULT:0.01 m/s
            "max_angular_velocity": float, //DEFAULT:10 deg/s
            "height": float,
            "diameter": float,
            "color": str, //DEFAULT:"blue"
            "motion_model": str, //DEFAULT:"unicycle" - Kinematic model used to integrate motion commands (pluggable; see plugins section).
            "detection":{ //DEFAULT:{} - extendable object similar to `messages`
                "type": str, //DEFAULT:"GPS" - Range-filtered positional detector; resolved via `models/detection` (custom modules supported).
                "range": float|"inf", //DEFAULT:0.1 - Limit how far perception gathers targets (alias: "distance").
                "acquisition_per_second": float, //DEFAULT:1 (= once per second) - Sampling frequency expressed as Hz; determines how often detection snapshots run relative to the agent tick rate. "inf" is used for max (once per tick)
            },
            "moving_behavior":str, //DEFAULT:"random_walk" - Any movement plugin registered in the system (`random_walk`, `random_way_point`, `spin_model`, or a custom module).
            "fallback_moving_behavior": str, //DEFAULT:"none" - Movement model used when the main plugin cannot produce an action (e.g., spin model without perception).
            "logic_behavior": str, //DEFAULT:None
            "hierarchy_node": str, //OPTIONAL - desired hierarchy node for the agent (defaults to the root "0" when hierarchy overlays are used).
            "spin_model":{ //DEFAULT:{} empty dict -> //DEFAULT configuration
                "spin_per_tick": int, //DEFAULT:3
                "spin_pre_run_steps": int, //DEFAULT:0 //DEFAULT value avoid pre run steps
                "perception_width": float, //DEFAULT:0.3
                "num_groups": int, //DEFAULT:8
                "num_spins_per_group": int, //DEFAULT:5
                "perception_global_inhibition": int, //DEFAULT:0
                "T": float, //DEFAULT:0.5
                "J": float, //DEFAULT:1
                "nu": float, //DEFAULT:0
                "p_spin_up": float, //DEFAULT:0.5
                "time_delay": int, //DEFAULT:1
                "reference": str, //DEFAULT:"egocentric"
                "dynamics": str, //DEFAULT:"metropolis"
            },
            "messages":{  //DEFAULT:{} empty dict -> no messaging
                "send_message_per_seconds": float, //DEFAULT:1 messages sent per second
                "receive_message_per_seconds": float, //DEFAULT:4 messages pulled per second
                "comm_range": float|"inf", //DEFAULT:0.1
                "type": str "broadcast"|"rebroadcast"|"hand_shake", //DEFAULT:"broadcast"
                "kind": str "anonymous"|"id-aware", //DEFAULT:"anonymous"
                "channels": str "single"|"dual", //DEFAULT:"dual"
                "bus": str, //DEFAULT:"auto" (spatial for geometric arenas, global all-to-all for abstract; pluggable via register_message_bus)
                "rebroadcast_steps": int|"inf", //DEFAULT:"inf". ONLY IF type is "rebroadcast" (agent-side limit on how many times a packet can be forwarded from the local buffer)
                "handshake_auto": bool, //DEFAULT:true. ONLY IF type is "hand_shake". Broadcast discovery invitations whenever idle.
                "handshake_timeout": float, //DEFAULT:5 seconds before a silent partner is dropped.
                "timer": { //OPTIONAL - configure automatic message expiration inside each agent buffer - DEFAULT:{} messages do not expire
                    "distribution": str "fixed"|"uniform"|"gaussian"|"exp"|"exponential", //DEFAULT:"fixed"
                    "parameters": dict {"name":float,...} //DEFAULT {} e.g. {"average":1} or {"max":1} (uniform) or {"lambda":2} (exp)
                }
            }
        }
    }
}
```

### Batch runs / parameter sweeps

- Multiple `arena_*` entries generate one experiment per arena.
- Any list-valued scalar field (except `position`, `orientation`, `strength`, `uncertainty`) under an agent/object group is expanded via Cartesian product. Example: `movable_0.ticks_per_second: [3, 6]` and `movable_0.motion_model: ["unicycle", "random_walk"]` yield four experiments for that arena. `number` can also be a list to sweep population sizes.
- The combinations are built per arena, objects, and agent groups, then executed sequentially. `environment.num_runs` repeats each expanded experiment deterministically.
- Keep the GUI disabled for batch sweeps; when `environment.results` exists (and is non-empty) and `gui` is empty, exports are written for every expanded experiment/run.

### Arena, Objects and Agents ruleset

Arenas field must always be present, and arena entries must start with "arena_" (unique keys).
Object and agent entries must start with "static_" or "movable_" regardless of arena type.

### Agent spawning

- DEFAULT spawn center `c = [0, 0]` and radius `r` can be overridden per agent group via `spawn.center` / `spawn.radius` / `spawn.distribution` (`uniform` | `gaussian` | `exp`, DEFAULT `uniform`). Agents/sample logic can also mutate these at runtime.
- Bounded arenas: if `r` is not provided, it DEFAULTs to the inradius of the arena footprint. The sampled area is clamped to the arena; if the requested circle exceeds the bounds it is truncated to fit. Placement still respects non-overlap with walls, objects, and other agents.
- Unbounded arenas: if `r` is missing/invalid, a finite radius is inferred from agent count/size so that all requested agents fit in a reasonable square. Sampling uses the chosen distribution around `c` without wrap-around.
- Multiple groups sharing the same spawn center: the second (and subsequent) groups are nudged away when their spawn disks overlap (iterated up to 16 attempts with a small margin). If overlap remains, the system falls back to per-entity collision checks and logs a warning.

For parser notes, data exports, and plugin hooks, see `README_DEVELOPERS.md`.
