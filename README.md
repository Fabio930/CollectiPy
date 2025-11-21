# Decision Making Simulation Framework

**CollectiPy** is not designed to offer physically realistic simulations. It does not include a physics engine, nor does it attempt to model complex physical dynamics. The environment is intentionally simplified to enable rapid experimentation with ideas, algorithms, and theoretical models, serving as an initial validation layer before moving to more accurate tools.

This framework is designed to implement simulations for both single and multi-agent systems. It includes base classes to create a working arena where physical agents and/or objects can be deployed. Custom arenas can be built. Additionally, there are base classes to provide a GUI, which can be switched off if not needed. Entities, which can be agents, objects, or highlighted areas in the arena. A data handling class is provided to store data in a predefined format.

## Quick Start

```bash
git clone https://github.com/tuo-utente/CollectiPy.git
cd CollectiPy
chmod +x ./compile.sh
./compile.sh
./run.sh
```

Uncomment the test you want to run in the bash file.

## Project Structure

- **config/**: Provides the methods to handle the json configuration file.
- **environment/**: Manages the parallel processing of the siumulations.
- **arena/**: Contains custom arenas where simulations take place. Users can create their own arenas by extending the base classes provided (including the new spherical arena projection).
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

After the first download the compile.sh file must be invoked. To give permissions open the terminal at the base folder level and type: sudo chmod +x *.sh. Then type ./compile.sh.
Now required packages from the requirements.txt file are installed in the virtual environment.

To run the simulations a run.sh file is provided.

## Config.json Example

```json
{
"environment":{
    "collisions": bool, DEFAULT:false
    "ticks_per_second": int, DEFAULT:1
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
        "enabled": bool, DEFAULT:false - turn detailed logging on/off (also enables log persistence)
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
            "_id": str, Required - SUPPORTED:"rectangle","square","circle","abstract","sphere"
            "diameter": float, Required only for "_id":"sphere" (defines the spherical surface)
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

Raw traces saved under `environment.results.base_path` now obey the spec lists declared in `results.agent_specs` / `results.group_specs`. When an arena hierarchy is configured, each base row also includes the hierarchy node where the agent currently sits so downstream analysis can group by partition. Per-agent pickles (`<group>_<idx>.pkl`) are emitted only when `"base"` is present (sampled `[tick, pos x, pos y, pos z]` rows) and can optionally append `"spin_model"` dumps (`<group>_<idx>_spins.pkl`). Snapshots are taken once per simulated second by default (after the last tick in that second); setting `snapshots_per_second: 2` adds a mid-second capture. Tick `0` is always stored so consumers see the initial pose, and the very last tick is forced even if it does not align with the cadence. Group specs apply to global outputs: `"graph_messages"` / `"graph_detection"` write one pickle per tick under `graphs/<mode>/step_<tick>.pkl`, and the helper spec `"graphs"` enables both. Message edges require that the transmitter has range and a non-zero TX budget **and** the receiver advertises a non-zero RX budget; detection edges only appear when the sensing agent has a non-zero acquisition rate in addition to range. All per-step graph pickles are zipped into `{mode}_graphs.zip` at the end of the run, and finally the whole `run_<n>` folder is compressed so analysis scripts can ingest the pickles while storage stays compact.

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
first" flow can live entirely inside plugins without changing the simulator
core.

**Messaging behaviour.** Message payloads must always be dictionaries; non-dict values are logged and discarded so plugins can safely extend them with custom fields. Received packets are archived inside each agent: `agent.message_archive` stores lists keyed by the identifiable sender (`source_agent`, `agent_id`, or `from`), and anonymous packets fall back to `agent.anonymous_message_buffer`. Both structures are cleared on every `reset()`.

### Minimal random-waypoint preset

Need a lightweight scenario for benchmarks or demos? `config/random_wp_minimal_gui.json`
spawns a handful of random-waypoint agents inside a small rectangular arena,
disables collisions/messages/results logging, and keeps the GUI to the bare
minimum (just the arena canvas). It is the fastest preset shipped with the
repository and a good starting point for stress tests when you do not need the
connection overlays or per-agent panels.

### Messaging policies, limits, and channels

`messages.channels` controls how many RF lanes an agent has:

- `"dual"` (default) matches the classic two-channel radio (TX and RX run in
  parallel).
- `"single"` emulates half-duplex hardware: the receive phase is skipped on ticks
  where the node transmitted.

`broadcast` packets can still be anonymous, but `hand_shake` and `rebroadcast`
require identifiable payloads (`kind` cannot be `"anonymous"`). Handshake radios
continuously broadcast discovery invites (unless `messages.handshake_auto` is
set to `false`); the first peer that replies with an `"accept"` lock takes the
channel until a `"dialogue_end"` signal is exchanged or the inactivity timer
(`messages.handshake_timeout`, defaults to 5 s) expires. Plugins can call
`Agent.request_handshake()`, `Agent.set_handshake_autostart(False)`, or
`Agent.set_handshake_acceptance(False)` to implement custom policies (see the
collision-triggered example below). `rebroadcast` is
strictly ID-aware: half of the time the agent sends its own payload, the rest of
the time it picks a random buffered message that has been forwarded fewer than
`rebroadcast_steps` (default infinity when `type="rebroadcast"`), increments the
`rebroadcast_count`, and propagates it again while annotating who relayed it
last. The 50/50 split is implemented via a simple random wheel: each tick the
simulator samples a uniform number in `[0, 1)` and uses `< 0.5` to emit fresh
telemetry, otherwise it forwards one of the eligible buffered packets. If the
buffer is empty or all packets exhausted their counters, the node
sends its own telemetry instead.

Send and receive quotas (`tx_per_second` and `rx_per_second`, legacy configs
still accept `messages_per_seconds`/`receive_per_seconds`; defaults are 1 Hz TX
and 4 Hz RX) are converted into per-tick token buckets so that agents
cannot inject or process more traffic than requested. When `timer` is configured,
each received packet gets a lifetime sampled from the requested distribution and
is automatically removed from the agent buffers once its timer (expressed in
seconds, converted into ticks) reaches zero.

Outgoing payloads always contain the standard metadata (`tick`, world `position`,
`agent_id`, and the full `entity` key). Plugins can append extra fields through
`Agent.set_outgoing_message_fields`, but the simulator re-injects the canonical
fields right before sending and stores every received packet in the agent’s
`messages` register for later inspection or re-broadcast.

## Plugins

The simulator exposes a lightweight plugin system so that movement, detection, motion/kinematics, and agent-logic routines can be extended without touching the core files. Key points:

- Built-in plugins live under `src/models/` and register themselves when imported.
- External plugins can be placed in the top-level `plugins/` directory (or any other importable package) and listed in the JSON config via the `"plugins": [...]` array; they will be imported before the simulation starts.
- Movement plugins must implement `plugin_base.MovementModel`, motion/kinematics plugins implement `MotionModel` (e.g., the default `unicycle`), detection plugins `DetectionModel`, and logic plugins `LogicModel`. Registration is done through `plugin_registry.register_*`.
- Message routing can also be customised. Pick a built-in bus by setting `messages.bus`
  in the config (`"auto"` falls back to spatial in solid arenas and to a global bus
  otherwise) or register a new bus with `plugin_registry.register_message_bus`.

Refer to `PLUGINS.md` for in-depth instructions and examples of custom modules.

## Logging

Set the `environment.logging` section in the config to enable structured logs describing agent/object creation, reasoning cycles, message exchanges, and collisions. Example:

```json
"logging": {
  "enabled": true,
  "level": "DEBUG",
  "file_level": "WARNING",
  "to_console": true
}
```

When enabled, the simulator records detailed traces through Python’s `logging` module; when disabled, only warnings/errors are emitted. Each run creates a timestamped archive under `logs/` (e.g. `logs/20240603-121030_ab12cd34.log.zip`) so that the inner `.log` stays human-readable but is shipped as a compressed blob rather than a machine-ingestible CSV. The config file is also copied under `logs/configs/`, and `logs/logs_configs_mapping.csv` maintains the correspondence between hashes and log paths starting from the project root.

## Unbounded arena

Set `_id: "sphere"` inside the `environment.arenas` entry to simulate agents inside an unbounded wrap-around arena (internally represented with a spherical projection). Provide the sphere `diameter` and the engine will:

- create a spherical geometry for reference and flatten it into an elliptical map (major axis = circumference, minor axis = half-circumference) using an equirectangular-style projection
- enable seamless wrap-around movement: entities exiting one edge immediately reappear on the opposite edge, preserving adjacency as on the sphere
- keep collision handling, perception and messaging identical to other arenas while avoiding hard borders

Example:

```json
"arena_0": {
  "_id": "sphere",
  "diameter": 2.0,
  "segments": 120,
  "random_seed": 13,
  "color": "lightblue"
}
```

The optional `segments` field controls how finely the ellipse is tessellated for rendering/collision checks (defaults to 96).

## Hierarchical arenas and confinement plugin

Every solid arena can now be partitioned into a reversed tree via the optional
`arena.hierarchy` block. Level 0 always represents the whole arena and each
additional level subdivides every node using either 2 or 4 adjacent branches.
When the GUI detects more than one level it renders the resulting grid to make
the spatial zoning explicit.

Agents and objects can opt into a specific node by adding the field
`"hierarchy_node": "0.1"` (dot-separated indices) to their configuration.
Agents can then activate the built-in `hierarchy_confinement` logic plugin:

```json
"logic_behavior": "hierarchy_confinement",
"hierarchy_node": "0.1.2"
```

The plugin clamps agent motion so that their shape always remains inside the
assigned node, making it easy to confine teams to predetermined quadrants or to
gate behaviours when they migrate to a different branch. When the field is
missing the plugin defaults to the root node, preserving backward compatibility.

Additional notes:

- Agents are always initialised as belonging to the root node ("0"). The optional
  `hierarchy_node` field is treated as a *target* that can be adopted later by
  calling `agent.set_hierarchy_node(...)`.
- The logic plugin keeps track of the current level through
  `agent.get_hierarchy_level()`, which uses the arena hierarchy metadata.
- `ArenaHierarchy` exposes helper methods such as `level_of(node_id)`,
  `neighbors(node_id)`, `path_between(start, end)`, and `locate_path(x, y)` so
  that future logic can enforce sequential transitions (e.g., an agent must pass
  through common ancestors instead of jumping directly between siblings).
- Each level receives a distinct, high-contrast colour derived from ColorBrewer-
  style palettes; the GUI overlays every zone with its level colour and prints
  the node number (child index). Agents render a secondary square attachment
  opposite to the default circular mark, tinted with the colour of the level
  they currently occupy so that their affiliation is always visible.

## Contributing

Contributions, bug reports, and suggestions are welcome!
If you use CollectiPy for your research, teaching, or project, please open an Issue or Discussion.
Your feedback helps validate and evolve the framework!

⭐ If you like the project, leave a **star**.
