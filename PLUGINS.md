# Plugin-aware version of the decision-making simulator

This version of the project introduces a **minimal, backward-compatible
plugin system** focused on agent movement models.

## Directory layout (main additions)

- `src/plugin_base.py`:
  defines the `MovementModel`, `MotionModel`, `LogicModel`, and `DetectionModel`
  protocols plus a simple `PluginBase`.
- `src/plugin_registry.py`:
  central registry for movement, motion, logic, and detection models, plus a
  helper to load plugin modules from the JSON configuration.
- `src/models/movement/`:
  built-in random-walk, random-way-point, and spin movement plugins.
- `src/models/motion/`:
  built-in kinematic integrators (currently `unicycle`, used by default).
- `src/models/detection/`:
  built-in GPS (and placeholder visual) detection plugins.
- `plugins/` (top-level, sibling of `src/`):
  package for external plugins. It includes `plugins/examples/group_stats_plugin.py`
  as a ready-to-use example logic plugin.

## Agent routines

`MovableAgent` now orchestrates **three routines per tick**:

1. an optional *logic model* (`logic_behavior`) that can prepare internal state
2. a required *movement model* (`moving_behavior`) that produces motion commands
3. a *motion/kinematics model* (`motion_model`, defaults to `unicycle`) that
   integrates those commands into the agent pose.

Movement models now simply express their intent via `agent.linear_velocity_cmd`
and `agent.angular_velocity_cmd`, leaving the integration to whichever
`MotionModel` is selected. This allows swapping the unicycle integrator with
future bicycle/Ackermann/holonomic models without rewriting the behaviours.
Random walk, random way-point, and spin behaviours all live in
`src/models/movement/`, while the default kinematic integrator lives under
`src/models/motion/`.

Detection/perception is also handled through plugins. The spin model,
for instance, requests a detection plugin (`detection` config field)
from `src/models/detection/` (GPS by default). Additional detection
strategies can be implemented without touching `entity.py`.

## External plugins

An external plugin can register a new movement model as follows:

```python
# plugins/my_movement.py
from plugin_registry import register_movement_model

class MyMovement:
    def __init__(self, agent):
        self.agent = agent

    def step(self, agent, tick, arena_shape, objects, agents):
        # custom movement logic here
        ...

register_movement_model("my_movement", lambda agent: MyMovement(agent))
```

Then, in the JSON config, add:

```json
{
  "plugins": ["plugins.my_movement"],
  "environment": {
    ...
    "agents": {
      "movable_1": {
        ...
        "moving_behavior": "my_movement"
      }
    }
  }
}
```

The simulator will import `plugins.my_movement` and automatically use
the new behaviour for any agent whose `moving_behavior` is set to
`"my_movement"`. Modules listed under either the top-level `plugins`
key or `environment.plugins` are imported before the environment
starts.

Similarly, detection or logic models can be registered with
`register_detection_model` / `register_logic_model`. They become
available through the respective `*_behavior` fields in the config. The repo
ships with a simple example logic plugin (`heading_sampler`) in
`plugins/examples/group_stats_plugin.py`; add
`"plugins": ["plugins.examples.group_stats_plugin"]` to the config and set an
agent group's `"logic_behavior": "heading_sampler"` to enable it.

Motion/kinematics models follow the same registry pattern. To provide a custom
integrator (e.g., a bicycle model), implement `plugin_base.MotionModel` and
register it:

```python
from plugin_registry import register_motion_model

class BicycleMotion:
    def __init__(self, agent):
        self.agent = agent

    def step(self, agent, tick):
        # integrate agent.linear_velocity_cmd / agent.angular_velocity_cmd
        ...

register_motion_model("bicycle", lambda agent: BicycleMotion(agent))
```

Agents can opt in via `"motion_model": "bicycle"`. Omitting the field keeps the
default `unicycle` behaviour.

## Message buses

Communication semantics can be extended through plugins as well. The
`messages` section of each agent group accepts a `bus` field; it is set
to `"auto"` by default, which resolves to the built-in spatial bus when
the arena is geometric and to a global all-to-all bus when the arena is
abstract.

To provide a custom implementation, register a callable with
`register_message_bus`. The callable receives the list of participating
agents, the message configuration, and an optional context dictionary
(`arena_shape`, wrap metadata, etc.) and must return an object adhering
to `plugin_base.MessageBusModel`.

```python
from plugin_registry import register_message_bus
from plugin_base import MessageBusModel

class FullyConnectedBus(MessageBusModel):
    ...

register_message_bus("fully_connected", lambda agents, config, ctx: FullyConnectedBus(agents, config, ctx))
```

Agents can opt in via:

```json
"messages": {
  "bus": "fully_connected",
  "type": "broadcast"
}
```

Bus implementations can inspect the configured rate limits (`tx_per_second` /
`rx_per_second`, with `messages_per_seconds` / `receive_per_seconds` still
handled for backwards compatibility), channel mode, or the `rebroadcast_steps` hint inside the
`config` dictionary if they need to adjust their behaviour. `MessageBusModel`
now exposes `receive_messages(self, receiver, limit=None)` so that the simulator
can enforce per-node receive quotas. Agents expose a
`set_outgoing_message_fields` helper that plugins can use to append custom data
to the outgoing payload, but the simulator always injects the standard metadata
(`tick`, global position, full entity key, and the public identifier when the
message kind is `id`) before forwarding the packet to the bus.

### Policy summary

- `broadcast` is the only type that may remain anonymous.
- `rebroadcast` packets are always ID-aware: half the time the agent emits its
  own telemetry, half the time it replays a buffered message that has not
  exceeded the configured `rebroadcast_steps`, bumping the `rebroadcast_count`
  before forwarding. The simulator implements this 50/50 decision with a random
  wheel: a uniform draw below `0.5` emits a fresh payload, otherwise an eligible
  buffered packet is replayed.
- `hand_shake` radios broadcast discovery invites (unless
  `messages.handshake_auto=false`) and lock onto the first peer that replies
  with `"accept"`. The handshake metadata alternates between `"start"`,
  `"accept"`, and `"end"` phases (plus `dialogue_end=True` for the closing
  packet) so the private exchange remains explicit. Plugins can call
  `Agent.request_handshake()` / `Agent.set_handshake_autostart(False)` to
  implement custom discovery policies.

Plugins may alter the payload contents or even replace the bus entirely, but the
core routine that enforces the above policy is always executed before custom
logic runs.
