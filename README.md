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

Edit `run.sh` to point to the config you want to run; the default is one of the demos in `config/`.

## Project Structure

- **config/**: Provides the methods to handle the json configuration file.
- **environment/**: Manages the parallel processing of the siumulations.
- **arena/**: Contains custom arenas where simulations take place. Users can create their own arenas by extending the base classes provided (rectangle/circle/square and the unbounded square preview).
- **entityManager/**: Manages the simulation of agents deployed in the arena.
- **entity/**: Houses the definitions for various entities such as agents, objects, and highlighted areas within the arena.
- **gui/**: Includes base classes for the graphical user interface. The GUI can be enabled or disabled based on user preference.
- **dataHandling/**: Provides classes and methods for storing and managing simulation data in a predefined format. It can be enabled or disabled based on user preference.
- **models/movement/**: Built-in movement plugin implementations (random walk, random waypoint, spin model).
- **models/motion/**: Kinematic/motion models (default unicycle integrator; extendable via plugins).
- **models/detection/**: Built-in perception/detection plugins (GPS plus placeholders for future visual processing).
- **plugin_base.py / plugin_registry.py**: Define the plugin protocols (movement, logic, detection) and runtime registries.
- **logging_utils.py**: Helper utilities to configure the logging system from the JSON config.
- **plugins/**: Top-level folder (sibling of `src/`) meant for external user plugins; modules placed here can be referenced from the config.

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

## Config.json Example

```json
{
"environment":{
    "collisions": bool, DEFAULT:false
    "ticks_per_second": int, DEFAULT:3
    "time_limit": int, DEFAULT:0(inf)
    "num_runs": int, DEFAULT:1
    "results":{ DEFAULT:{} empty dict -> no saving. If rendering is enabled -> no saving
        "base_path": str, DEFAULT:"../data/" (only used when this block is present; does not enable dumps by itself)
        "agent_specs": list(str) DEFAULT:[] - enable per-agent exports:
            "base" -> stream sampled [tick, x, y, z] positions for every agent (adds the current hierarchy node when a hierarchy is configured),
            "spin_model" -> append spin-system payloads alongside the base rows.
        "group_specs": list(str) DEFAULT:[] - enable aggregated exports:
            "graph_messages" / "graph_detection" -> adjacency snapshots for the selected channel,
            "graphs" -> shorthand enabling both message/detection graphs.
        "snapshots_per_second": int, DEFAULT:1 (1 = end-of-second only, 2 = mid-second + end-second captures).
    },
    "logging":{ DEFAULT:{} empty dict -> logging disabled
        "level": str, DEFAULT:"INFO" - console level (set DEBUG to track interactions/collisions)
        "file_level": str, DEFAULT:"WARNING" - severity written to disk (WARNING/ERROR by default)
        "to_console": bool, DEFAULT:true - echo logs to stdout
    },
    "gui":{ DEFAULT:{} empty dict -> no rendering
        "_id": "2D", Required
        "on_click": list(str) DEFAULT:None default shows nothing on click (leave empty for lowest load)
        "view": list(str) DEFAULT:None default shows nothing in the side column
        "view_mode": str DEFAULT:"dynamic" - SUPPORTED:"static","dynamic" (initial state for the View dropdown)
    },
        "arenas":{ Required can define multiple arena to simulate sequentially
        "arena_0":{
            "random_seed": int, DEFAULT:random
            "width": int, DEFAULT:1
            "depth": int, DEFAULT:1
            "_id": str, Required - SUPPORTED:"rectangle","square","circle","abstract","unbounded"
            "diameter": float, OPTIONAL for "_id":"unbounded" (initial side of the preview square; defaults to 10 if omitted or <=0)
            "color": "gray" DEFAULT:white
            "hierarchy": { OPTIONAL - define the reversed-tree partition applied to this arena
                "depth": int, DEFAULT:0 - number of additional levels (root is level 0)
                "branches": int, DEFAULT:1 - 1 disables the partitioning, 2 splits each cell in half along the widest axis, 4 creates a 2x2 grid per node
            }
        }
    },
        "objects":{ Required can define multiple objects to simulate in the same arena
        "static_0":{
            "number": list(int), DEFAULT:[1] each list's entry will define a different simulation
            "position": list(3Dvec), DEFAULT:None default assings random not-overlapping initial positions
            "orientation": list(3Dvec), DEFAULT:None default assings random initial orientations
            "_id": "str", Required - SUPPORTED:"idle","interactive"
            "shape": "str", Required - SUPPORTED:"circle","square","rectangle","sphere","cube","cylinder","none" flat geometry can be used to define walkable areas in the arena
            "height": float, DEFAULT:1 width and depth used for not-round objects
            "diameter": float, DEFAULT:1 used for round objects
            "color": "str", DEFAULT:"black"
            "strength": list(float), DEFAULT:[10] one entry -> assign to all the objects the same value. Less entries tha objects -> missing values are equal to the last one
            "uncertainty": list(float), DEFAULT:[0] one entry -> assign to all the objects the same value. Less entries tha objects -> missing values are equal to the last one
            "hierarchy_node": str, OPTIONAL - bind the object to a specific hierarchy node (e.g. "0.1.0")
        }
    },
        "agents":{ Required can define multiple agents to simulate in the same arena
        "movable_0":{
            "ticks_per_second": int, DEFAULT:5
            "number": list(int), DEFAULT:[1] each list's entry will define a different simulation
            "position": list(3Dvec), DEFAULT:None default assings random not-overlapping initial positions
            "orientation": list(3Dvec), DEFAULT:None default assings random initial orientations
            "shape": str, - SUPPORTED:"sphere","cube","cylinder","none"
            "linear_velocity": float, DEFAULT:0.01 m/s
            "angular_velocity": float, DEFAULT:10 deg/s
            "height": float,
            "diameter": float,
            "color": str, DEFAULT:"blue"
            "motion_model": str, DEFAULT:"unicycle" - Kinematic model used to integrate motion commands (pluggable; see plugins section).
            "detection":{ DEFAULT:{} - extendable object similar to `messages`
                "type": str, DEFAULT:"GPS" - Detection plugin resolved via `models/detection` (custom modules supported).
                "range": float|"inf", DEFAULT:"inf" - Limit how far perception gathers targets (alias: "distance").
                "acquisition_per_second": float|1, DEFAULT:1 (= once per second) - Sampling frequency expressed as Hz; determines how often detection snapshots run relative to the agent tick rate. "inf" is used for max (once per tick)
            },
            "detection_settings":{ DEFAULT:{} legacy optional overrides for range },
            "moving_behavior":str, DEFAULT:"random_walk" - Any movement plugin registered in the system (`random_walk`, `random_way_point`, `spin_model`, or a custom module).
            "fallback_moving_behavior": str, DEFAULT:"none" - Movement model used when the main plugin cannot produce an action (e.g., spin model without perception).
            "logic_behavior": str, DEFAULT:None - Optional logic plugin executed before the movement plugin (placeholder for future reasoning modules).
            "hierarchy_node": str, OPTIONAL - desired hierarchy node for the agent (used by the hierarchy confinement plugin). Defaults to the root ("0") if omitted.
            "spin_model":{ DEFAULT:{} empty dict -> default configuration
                "spin_per_tick": int, DEFAULT:10
                "spin_pre_run_steps": int, DEFAULT:0 default value avoid pre run steps
                "perception_width": float, DEFAULT:0.5
                "num_groups": int, DEFAULT:16
                "num_spins_per_group": int, DEFAULT:8
                "perception_global_inhibition": int, DEFAULT:0
                "T": float, DEFAULT:0.5
                "J": float, DEFAULT:1
                "nu": float, DEFAULT:0
                "p_spin_up": float, DEFAULT:0.5
                "time_delay": int, DEFAULT:1
                "reference": str, DEFAULT:"egocentric"
                "dynamics": str DEFAULT:"metropolis"
            },
            "messages":{  DEFAULT:{} empty dict -> no messaging
                "tx_per_second": int, DEFAULT:1  (legacy: messages_per_seconds)
                "bus": str, DEFAULT:"auto" (spatial in solid arenas, global otherwise)
                "comm_range": float, DEFAULT:0.1 m
                "type": str, DEFAULT:"broadcast"
                "kind": str DEFAULT:"anonymous"
                "channels": str DEFAULT:"dual" - SUPPORTED:"single","dual"
                "rx_per_second": int DEFAULT:4  (legacy: receive_per_seconds)
                "rebroadcast_steps": int DEFAULT:inf (agent-side limit on how many times a packet can be forwarded from the local buffer)
                "handshake_auto": bool, DEFAULT:true (broadcast discovery invitations whenever idle)
                "handshake_timeout": float|str, DEFAULT:5 (seconds before a silent partner is dropped; accepts "auto")
                "timer": { OPTIONAL - configure automatic message expiration inside each agent
                    "distribution": "fixed"|"uniform"|"exponential" (DEFAULT:"fixed")
                    "average": float, REQUIRED - mean duration in seconds.
                }
            },
            "information_scope": { OPTIONAL - hierarchy-aware visibility rules
                "mode": "node"|"branch" (DEFAULT: disabled). When set to "node" the agent can only exchange detection/messages with entities in the same hierarchy node.
                "direction": "up"|"down"|"both"|"flat" (DEFAULT:"both", only for "branch" mode). "flat" allows the agent to interact with the current node plus siblings that share the same parent branch.
                "messages" / "detection": channel-specific overrides; if omitted the same settings apply to both (shorthand strings like `"branch:up"` are accepted). Invalid entries are logged with a warning and the restriction falls back to the unrestricted default.
            },
            "hierarchy_node": str, OPTIONAL - preferred hierarchy target. Agents always spawn in level-0 ("0") and can later request transitions along the tree.
        }
    }
}
}
```

### Agent spawning (bounded vs unbounded)

- Default spawn center `c = [0, 0]` and radius `r` can be overridden per agent group via `spawn.center` / `spawn.radius` / `spawn.distribution` (`uniform` | `gaussian` | `ring`, default `uniform`). Agents/sample logic can also mutate these at runtime.
- Bounded arenas: if `r` is not provided, it defaults to the inradius of the arena footprint. The sampled area is clamped to the arena; if the requested circle exceeds the bounds it is truncated to fit. Placement still respects non-overlap with walls, objects, and other agents.
- Unbounded arenas: if `r` is missing/invalid, a finite radius is inferred from agent count/size so that all requested agents fit in a reasonable square. Sampling uses the chosen distribution around `c` without wrap-around.
- Multiple groups sharing the same spawn center: the second (and subsequent) groups are shifted away by at least `0.25 * r`, repeated until a non-overlapping placement is found or attempts are exhausted. If spawn disks do not touch and placement still fails, the init aborts with an error (attempt limit unchanged).

Raw traces saved under `environment.results.base_path` obey the spec lists declared in `results.agent_specs` / `results.group_specs`. When an arena hierarchy is configured, each base row also includes the hierarchy node where the agent currently sits so downstream analysis can group by partition. Per-agent pickles (`<group>_<idx>.pkl`) are emitted only when `"base"` is present (sampled `[tick, pos x, pos y, pos z]` rows) and can optionally append `"spin_model"` dumps (`<group>_<idx>_spins.pkl`). Snapshots are taken once per simulated second by default (after the last tick in that second); setting `snapshots_per_second: 2` adds a mid-second capture. Tick `0` is always stored so consumers see the initial pose, and the very last tick is forced even if it does not align with the cadence. Group specs apply to global outputs: `"graph_messages"` / `"graph_detection"` write one pickle per tick under `graphs/<mode>/step_<tick>.pkl`, and the helper spec `"graphs"` enables both. Message edges require that the transmitter has range and a non-zero TX budget **and** the receiver advertises a non-zero RX budget; detection edges only appear when the sensing agent has a non-zero acquisition rate in addition to range. All per-step graph pickles are zipped into `{mode}_graphs.zip` at the end of the run, and finally the whole `run_<n>` folder is compressed so analysis scripts can ingest the pickles while storage stays compact.

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

### Plugin example: heading sampler

The repository ships a tiny plugin under `plugins/examples/group_stats_plugin.py` that showcases how to tag agents with custom metrics every time a tick completes. Import it from the config (add `"plugins.examples.group_stats_plugin"` to the top-level `"plugins"` list) and set `logic_behavior: "heading_sampler"` for the agents that should track their rolling heading. The plugin keeps the last 32 headings, stores the instantaneous and averaged values in `agent.snapshot_metrics`, and logs a debug line every ~200 ticks. Those metrics can then be post-processed alongside the streamed snapshots enabled via `results.agent_specs` / `results.group_specs` (e.g., `snapshots_per_second: 2`, `group_specs: ["graphs"]`) without having to dump every intermediate tick.

*(All bundled configs keep the `gui` section minimal—only `_id` is provided—so that optional views/on-click overlays remain disabled unless explicitly enabled.)*

### Plugin example: collision-triggered handshakes

`plugins/examples/collision_handshake_plugin.py` demonstrates how to drive the
handshake controller from custom logic. Once loaded
(`"plugins.examples.collision_handshake_plugin"` in the config) you can attach
it by setting `logic_behavior: "collision_handshake"` on agents that already use
`messages.type: "hand_shake"`. The plugin disables automatic discovery, watches
the live shape snapshot provided by the entity manager, and only enables
handshakes for a short time window after the local body overlaps with another
agent. If contact stops while a session is active it calls
`Agent.terminate_handshake()` so the radio frees the channel. This illustrates
how policies more elaborate than the default "auto discover whoever replies
first" flow can live entirely inside plugins without changing the simulator.
