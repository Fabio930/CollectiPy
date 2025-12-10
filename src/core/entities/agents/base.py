# ------------------------------------------------------------------------------
#  CollectiPy
# Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Agent base class handling messaging/detection plumbing."""

from __future__ import annotations

import hashlib
import math
from random import Random
from typing import Any, Optional

from core.configuration.plugin_registry import get_motion_model
from core.entities.base import Entity, logger as _base_logger
from core.util.geometry_utils.vector3D import Vector3D
from core.util.logging_util import get_logger
import models  # noqa: F401  # ensure built-in models register themselves


logger = _base_logger

VALID_MESSAGE_CHANNELS = {"single", "dual"}
CHANNEL_TYPE_MATRIX = {
    "single": {"hand_shake", "rebroadcast"},
    "dual": {"broadcast", "rebroadcast", "hand_shake"},
}
DEFAULT_RX_RATE = 4.0


def splitmix32(x):
    """Lightweight mixing function used for deterministic per-agent seeds."""
    x = (x + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
    x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9 & 0xFFFFFFFFFFFFFFFF
    x = (x ^ (x >> 27)) * 0x94D049BB133111EB & 0xFFFFFFFFFFFFFFFF
    x = x ^ (x >> 31)
    return x & 0xFFFFFFFF


def make_agent_seed(global_seed, entity_type, entity_id):
    """Derive a deterministic per-agent seed from the global seed and identity."""
    base = f"{global_seed}|{entity_type}|{entity_id}"
    h1 = hashlib.sha256(base.encode()).digest()
    h2 = hashlib.blake2s(h1).digest()
    x = int.from_bytes(h2[:8], "little")
    return splitmix32(x)


class Agent(Entity):
    """Agent base class handling messaging/detection plumbing."""

    def __init__(self, entity_type: str, config_elem: dict, _id: int = 0):
        """Initialize the instance."""
        super().__init__(entity_type, config_elem, _id)
        # Movement/logic plugins are dynamically supplied; keep them untyped to satisfy optional hooks.
        self._movement_plugin: Any = None
        self._logic_plugin: Any = None
        self.random_generator = Random()
        self.ticks_per_second = config_elem.get("ticks_per_second", 5)
        self.color = config_elem.get("color", "blue")
        self.detection_range = 0.1
        self.linear_velocity_cmd = 0.0
        self.angular_velocity_cmd = 0.0
        self.motion_model_name = config_elem.get("motion_model", "unicycle")
        self._motion_model = get_motion_model(self.motion_model_name, self)
        if self._motion_model is None:
            self._motion_model = get_motion_model("unicycle", self)
        # --- messaging ---
        self.messages_config = dict(config_elem.get("messages", {}) or {})
        self.msg_enable = bool(self.messages_config)
        self.msg_comm_range = float(self.messages_config.get("comm_range", 0.1))
        self.msg_channel_mode = self._resolve_channel_mode(self.messages_config.get("channels", "dual"))
        self.msg_type = self._resolve_message_type(self.messages_config.get("type", "broadcast"), self.msg_channel_mode)
        self.msg_kind = str(self.messages_config.get("kind", "anonymous")).strip().lower()
        self.msg_bus_kind = self.messages_config.get("bus", "auto")
        self.msg_delete_trigger = self.messages_config.get("delete_trigger")
        self.msgs_per_sec = self._resolve_message_rate(
            (
                "send_message_per_seconds",
                "send_message_per_second",
            ),
            1.0,
        )
        self.msg_receive_per_sec = self._resolve_message_rate(
            (
                "receive_message_per_seconds",
                "receive_message_per_second",
            ),
            DEFAULT_RX_RATE,
        )
        if self.msg_type in {"hand_shake", "rebroadcast"} and self.msg_kind == "anonymous":
            raise ValueError(f"{self.entity()} cannot use kind='anonymous' with message type '{self.msg_type}'.")
        self.message_bus = None
        self.own_message = {}
        self.messages: list[dict] = []
        self._messages_by_sender: dict[str, list[dict]] | None = None
        self._messages_by_entity: dict[str, list[dict]] | None = None
        self._message_custom_fields = {}
        self._msg_send_budget = 0.0
        self._msg_receive_budget = 0.0
        self._msg_send_quanta = self._compute_rate_quanta(self.msgs_per_sec)
        self._msg_receive_quanta = self._compute_rate_quanta(self.msg_receive_per_sec)
        self._msg_send_budget_cap = max(1.0, self.msgs_per_sec * 2.0)
        self._msg_receive_budget_cap = max(1.0, self.msg_receive_per_sec * 2.0)
        self._last_tx_tick = -1
        self._last_rx_tick = -1
        self.rebroadcast_limit = self._resolve_rebroadcast_limit()
        self.handshake_partner = None
        self._handshake_state = "idle"
        self._handshake_token = None
        self._handshake_pending_accept = None
        self._handshake_manual_request = False
        self._handshake_end_requested = False
        self._handshake_request_tick = -1
        self._handshake_last_seen_tick = -1
        self._handshake_accept_enabled = True
        self._handshake_auto_request = bool(self.messages_config.get("handshake_auto", True))
        self._handshake_timeout_ticks = self._resolve_handshake_timeout(self.messages_config.get("handshake_timeout"))
        self.msg_timer_config = self._normalize_message_timer(self.messages_config.get("timer"))
        # --- detection ---
        self.detection_config = self._normalize_detection_config(config_elem.get("detection"))
        self.detection = self.detection_config.get("type", "GPS")
        self.detection_rate_per_sec = self._resolve_detection_frequency()
        self._detection_quanta = None
        self._detection_budget = 0.0
        self._detection_budget_cap = math.inf
        self._last_detection_tick = -1
        self._configure_detection_scheduler()
        # --- hierarchy-aware information scope ---
        scope_config = config_elem.get("information_scope") or config_elem.get("info_restrictions")
        self.information_restrictions = self._parse_information_restrictions(scope_config)
        self._info_scope_cache = {}
        self.hierarchy_context = None
        # Legacy helpers expected by managers.
        self.make_agent_seed = make_agent_seed

    # Messaging/detection/hierarchy wiring
    def set_message_bus(self, backend):
        """
        Attach the messaging backend used by this entity.

        In the current core this is typically a MessageProxy instance
        provided by the EntityManager, but any object exposing
        `send_message` and `receive_messages` is accepted.
        """
        self.message_bus = backend
        logger.info("%s attached to messaging backend %s", self.get_name(), type(backend).__name__)

    def set_hierarchy_context(self, hierarchy):
        """Attach the arena hierarchy reference."""
        self.hierarchy_context = hierarchy
        self._invalidate_info_scope_cache()

    def set_hierarchy_node(self, node_id):
        """Set the hierarchy node and refresh cached metadata."""
        super().set_hierarchy_node(node_id)
        self._invalidate_info_scope_cache()
        self._sync_shape_hierarchy_metadata()

    # Legacy API used by EntityManager
    def ticks(self) -> int:
        """Return ticks per second for this agent."""
        try:
            return int(self.ticks_per_second)
        except Exception:
            return 1

    def set_random_generator(self, seed: int | None):
        """Seed the internal random generator."""
        if seed is None:
            return
        try:
            self.random_generator.seed(seed)
        except Exception:
            pass

    def get_random_generator(self):
        """Return the internal random generator."""
        return self.random_generator

    def get_spin_system_data(self):
        """Return spin-system payload (None for agents without spin model)."""
        return None

    def get_max_absolute_velocity(self):
        """Return the max absolute velocity used by the collision detector."""
        try:
            return float(self.max_absolute_velocity)
        except Exception:
            return 0.0

    def get_forward_vector(self):
        """Return the current forward vector used for detector packaging."""
        try:
            return self.forward_vector
        except Exception:
            return Vector3D()

    def _sync_shape_hierarchy_metadata(self):
        """Attach hierarchy metadata to the main shape/attachments for GUI and detection."""
        try:
            shape = self.get_shape()
        except Exception:
            shape = None
        if shape is None:
            return
        try:
            if hasattr(shape, "metadata"):
                shape.metadata["hierarchy_node"] = getattr(self, "hierarchy_node", None)
                shape.metadata["entity_name"] = self.get_name()
        except Exception:
            pass
        try:
            attachments = getattr(shape, "attachments", None)
            if attachments:
                for att in attachments:
                    if hasattr(att, "metadata"):
                        att.metadata["hierarchy_node"] = getattr(self, "hierarchy_node", None)
                        att.metadata["entity_name"] = self.get_name()
        except Exception:
            pass

    # Messaging ---------------------------------------------------------
    def should_send_message(self, tick):
        """Return True if the agent can transmit during this tick."""
        _ = tick
        if not self.msg_enable or self._msg_send_quanta <= 0:
            return False
        if self.msg_channel_mode == "single" and self._last_rx_tick == tick:
            return False
        self._msg_send_budget = min(self._msg_send_budget + self._msg_send_quanta, self._msg_send_budget_cap)
        if self._msg_send_budget >= 1.0:
            self._msg_send_budget -= 1.0
            return True
        return False

    def send_message(self, tick):
        """Send message."""
        if not self.message_bus or not self.msg_enable:
            return
        if not self.should_send_message(tick):
            return
        if self.msg_type == "rebroadcast":
            payload = self._prepare_rebroadcast_payload(tick)
        elif self.msg_type == "hand_shake":
            payload = self._compose_handshake_payload(tick)
        else:
            payload = self._compose_message_payload(tick)
        if payload is None:
            return
        self.own_message = payload
        self.message_bus.send_message(self, payload)
        self._message_custom_fields.clear()
        self._last_tx_tick = tick
        logger.debug("%s sent message at tick %s: %s", self.get_name(), tick, payload)

    def receive_messages(self, tick):
        """Receive messages."""
        if not self.msg_enable or not self.message_bus or self._msg_receive_quanta <= 0:
            return []
        if self.msg_channel_mode == "single" and self._last_tx_tick == tick:
            return []
        self._msg_receive_budget = min(self._msg_receive_budget + self._msg_receive_quanta, self._msg_receive_budget_cap)
        allowed = int(self._msg_receive_budget)
        allowed = min(allowed, 1)
        if allowed <= 0:
            return []
        raw_messages = self.message_bus.receive_messages(self, limit=allowed)
        messages = []
        for msg in raw_messages:
            if not isinstance(msg, dict):
                logger.warning("%s received malformed message '%s'; skipping", self.get_name(), msg)
                continue
            messages.append(msg)
        if not messages:
            return []
        self._apply_message_timers(messages)
        if self.msg_type == "hand_shake":
            self._handle_handshake_messages(messages, tick)
        self._msg_receive_budget = max(0.0, self._msg_receive_budget - len(messages))
        self.messages.extend(messages)
        self._invalidate_message_indexes()
        logger.debug("%s received %d messages", self.get_name(), len(messages))
        if messages:
            self._last_rx_tick = tick
        return messages

    def clear_message_buffers(self) -> None:
        """Drop buffered messages and archives for this agent."""
        self.messages = []
        self._invalidate_message_indexes()

    def set_outgoing_message_fields(self, fields: Optional[dict]) -> None:
        """Register custom payload data to be merged into the next transmission."""
        if not isinstance(fields, dict):
            return
        self._message_custom_fields.update(fields)

    # Detection ---------------------------------------------------------
    def get_detection_range(self) -> float:
        """Return the configured detection range."""
        return float(self.detection_range)

    def _reset_detection_scheduler(self):
        """Reset detection scheduler state."""
        self._detection_budget = 0.0
        self._last_detection_tick = -1

    def _configure_detection_scheduler(self):
        """Prepare quanta for detection scheduler."""
        rate = self.detection_rate_per_sec
        if rate is None or rate <= 0:
            self._detection_quanta = None
            self._detection_budget_cap = 0.0
            self._detection_budget = 0.0
            return
        self._detection_quanta = rate / float(self.ticks_per_second or 1)
        self._detection_budget_cap = max(1.0, rate * 2.0)
        self._detection_budget = 0.0

    def should_detect(self, tick: int) -> bool:
        """Return True when the detection subsystem should sample this tick."""
        if self._detection_quanta is None:
            return False
        self._detection_budget = min(self._detection_budget + self._detection_quanta, self._detection_budget_cap)
        if self._detection_budget >= 1.0:
            self._detection_budget -= 1.0
            self._last_detection_tick = tick
            return True
        return False

    # Info scope --------------------------------------------------------
    def _invalidate_info_scope_cache(self):
        """Clear cached scope decisions."""
        self._info_scope_cache = {}

    def _parse_information_restrictions(self, cfg):
        """Parse hierarchy-aware scope rules."""
        if not cfg or not isinstance(cfg, dict):
            return None
        raw_mode = cfg.get("mode")
        if raw_mode is None:
            raw_mode = cfg.get("on") or cfg.get("over")
        if isinstance(raw_mode, str):
            mode = raw_mode.strip().lower()
        else:
            return None
        direction = str(cfg.get("direction", "both")).strip().lower()
        if direction not in {"up", "down", "both", "flat"}:
            direction = "both"
        over_raw = cfg.get("on") or cfg.get("over")
        if isinstance(over_raw, (list, tuple, set)):
            targets = {str(v).strip().lower() for v in over_raw}
        elif isinstance(over_raw, str):
            targets = {over_raw.strip().lower()}
        else:
            targets = set()
        valid_targets = {"messages", "detection", "movement", "move"}
        filtered = targets & valid_targets
        if not filtered:
            return None
        return {"mode": mode, "direction": direction, "targets": filtered}

    def _invalidate_message_indexes(self):
        """Reset cached message lookup maps."""
        self._messages_by_sender = None
        self._messages_by_entity = None

    # ------------------------------------------------------------------
    # Helpers for messaging/detection (private)
    # ------------------------------------------------------------------
    def _compose_message_payload(self, tick: int) -> dict:
        """Return the standard payload enriched with custom fields."""
        payload = dict(self._message_custom_fields)
        position = self.get_position()
        payload.update(
            {
                "tick": tick,
                "position": (
                    getattr(position, "x", 0.0),
                    getattr(position, "y", 0.0),
                    getattr(position, "z", 0.0),
                ),
                "agent_id": self.get_name(),
                "entity": self.entity(),
                "rebroadcast_count": 0,
                "source_agent": self.get_name(),
                "last_forward_by": self.get_name(),
            }
        )
        return payload

    def _compose_handshake_payload(self, tick: int) -> dict | None:
        """Compose a broadcast handshake payload following the built-in state machine."""
        self._handshake_check_timeout(tick)
        if self._handshake_end_requested and self.handshake_partner:
            partner = self.handshake_partner
            payload = self._compose_message_payload(tick)
            payload["to"] = partner
            payload["handshake"] = self._build_handshake_block("end", partner, self._handshake_token)
            payload["dialogue_state"] = "end"
            payload["dialogue_end"] = True
            self._reset_handshake_state()
            return payload
        if self._handshake_pending_accept:
            info = self._handshake_pending_accept
            payload = self._compose_message_payload(tick)
            payload["to"] = info["partner"]
            payload["handshake"] = self._build_handshake_block("accept", info["partner"], info["token"])
            payload["dialogue_state"] = "accept"
            payload["dialogue_end"] = False
            self.handshake_partner = info["partner"]
            self._handshake_token = info["token"]
            self._handshake_state = "connected"
            self._handshake_pending_accept = None
            self._handshake_last_seen_tick = tick
            return payload
        if self.handshake_partner and self._handshake_state == "connected":
            # No keepalive payload is needed until a plugin requests it.
            return None
        if self._handshake_state == "awaiting_accept":
            if (
                self._handshake_timeout_ticks > 0
                and self._handshake_request_tick >= 0
                and tick - self._handshake_request_tick > self._handshake_timeout_ticks
            ):
                self._reset_handshake_state()
            return None
        if (
            self.handshake_partner is None
            and self._handshake_state == "idle"
            and self._handshake_auto_request
            and not self._handshake_manual_request
        ):
            self._handshake_manual_request = True
        if not self._handshake_manual_request or self.handshake_partner is not None:
            return None
        payload = self._compose_message_payload(tick)
        token = f"{self.get_name()}#{tick}#{self.random_generator.random():.6f}"
        payload["handshake"] = self._build_handshake_block("invite", None, token)
        payload["dialogue_state"] = "start"
        payload["dialogue_end"] = False
        self._handshake_state = "awaiting_accept"
        self._handshake_token = token
        self._handshake_request_tick = tick
        self._handshake_manual_request = False
        return payload

    def _build_handshake_block(self, state: str, partner: str | None, token: str | None) -> dict:
        """Return the metadata describing the current handshake transition."""
        return {"state": state, "owner": self.get_name(), "partner": partner, "token": token}

    def _handle_handshake_messages(self, messages: list[dict], tick: int) -> None:
        """Update the local state machine based on received handshake payloads."""
        for msg in messages:
            block = msg.get("handshake")
            if not block:
                continue
            state = block.get("state") or msg.get("dialogue_state")
            peer = block.get("owner") or msg.get("source_agent") or msg.get("agent_id") or msg.get("from")
            token = block.get("token")
            if not peer or not state:
                continue
            if state == "invite":
                if self.handshake_partner or not self._handshake_accept_enabled:
                    continue
                self._handshake_pending_accept = {"partner": peer, "token": token}
                self._handshake_last_seen_tick = tick
            elif state == "accept":
                if self._handshake_state == "awaiting_accept" and self._handshake_token == token:
                    self.handshake_partner = peer
                    self._handshake_state = "connected"
                    self._handshake_last_seen_tick = tick
            elif state == "end":
                if self.handshake_partner == peer:
                    self._reset_handshake_state()
        self._handshake_manual_request = False

    def _reset_handshake_state(self):
        """Reset handshake state machine."""
        self.handshake_partner = None
        self._handshake_state = "idle"
        self._handshake_token = None
        self._handshake_pending_accept = None
        self._handshake_manual_request = False
        self._handshake_end_requested = False
        self._handshake_request_tick = -1
        self._handshake_last_seen_tick = -1

    def _handshake_check_timeout(self, tick: int):
        """Check handshake timeout."""
        if (
            self._handshake_state == "connected"
            and self._handshake_timeout_ticks > 0
            and self._handshake_last_seen_tick >= 0
            and tick - self._handshake_last_seen_tick > self._handshake_timeout_ticks
        ):
            self._reset_handshake_state()

    def _prepare_rebroadcast_payload(self, tick: int) -> dict | None:
        """Prepare a rebroadcast payload if present."""
        if not self.messages:
            return None
        msg = self.messages[-1]
        if msg is None:
            return None
        count = int(msg.get("rebroadcast_count", 0) or 0)
        if self.rebroadcast_limit is not None and count >= self.rebroadcast_limit:
            return None
        payload = dict(msg)
        payload["rebroadcast_count"] = count + 1
        payload["last_forward_by"] = self.get_name()
        payload["source_agent"] = msg.get("source_agent") or msg.get("agent_id") or self.get_name()
        payload["tick"] = tick
        return payload

    def _resolve_message_rate(self, keys, default):
        """Resolve a messaging rate from the config."""
        for key in keys:
            if key in self.messages_config:
                try:
                    value = float(self.messages_config[key])
                    return max(0.0, value)
                except (TypeError, ValueError):
                    logger.warning("%s invalid message rate '%s'", self.get_name(), self.messages_config[key])
        return default

    def _compute_rate_quanta(self, rate_per_second: float) -> float:
        """Return the budget increment per tick for a given rate."""
        if rate_per_second is None:
            return 0.0
        return rate_per_second / float(self.ticks_per_second or 1)

    def _resolve_handshake_timeout(self, value) -> float:
        """Return timeout in ticks for the handshake FSM."""
        if value is None:
            return 5.0 * self.ticks_per_second
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            return 5.0 * self.ticks_per_second
        if seconds <= 0:
            return 0.0
        return seconds * self.ticks_per_second

    def _resolve_rebroadcast_limit(self) -> Optional[int]:
        """Return the max rebroadcast count for rebroadcast mode."""
        if self.msg_type != "rebroadcast":
            return None
        raw = self.messages_config.get("rebroadcast_steps")
        if raw is None:
            return None if self.msg_kind == "anonymous" else math.inf
        if isinstance(raw, str) and raw.strip().lower() in {"inf", "infinite", "none"}:
            return math.inf
        try:
            value = int(raw)
            return value if value > 0 else None
        except (TypeError, ValueError):
            return None

    def _normalize_message_timer(self, cfg):
        """Normalize message timer configuration."""
        if not cfg or not isinstance(cfg, dict):
            return {"distribution": "fixed", "parameters": {}}
        distribution = str(cfg.get("distribution", "fixed")).strip().lower() or "fixed"
        params = cfg.get("parameters") or {}
        if not isinstance(params, dict):
            params = {}
        return {"distribution": distribution, "parameters": params}

    def _refresh_message_timers(self):
        """Prune expired messages based on timer configuration."""
        if not self.messages or not self.msg_enable:
            return
        dist = (self.msg_timer_config or {}).get("distribution", "fixed")
        params = (self.msg_timer_config or {}).get("parameters", {})
        if dist not in {"fixed", "uniform", "gaussian", "exp", "exponential"}:
            return
        # Current behaviour: no-op unless a timer model is implemented elsewhere.
        return

    def _apply_message_timers(self, messages: list[dict]) -> None:
        """Placeholder for per-message expiration logic."""
        _ = messages
        return

    def _resolve_channel_mode(self, channels: str) -> str:
        """Return a valid channel mode."""
        normalized = str(channels or "dual").strip().lower()
        if normalized not in VALID_MESSAGE_CHANNELS:
            logger.warning("%s invalid channels '%s'; defaulting to 'dual'", self.get_name(), channels)
            return "dual"
        return normalized

    def _resolve_message_type(self, msg_type: str, channel_mode: str) -> str:
        """Return a valid message type given the channel mode."""
        normalized = str(msg_type or "broadcast").strip().lower()
        allowed = CHANNEL_TYPE_MATRIX.get(channel_mode, CHANNEL_TYPE_MATRIX["dual"])
        if normalized not in allowed:
            fallback = next(iter(allowed))
            logger.warning(
                "%s invalid message type '%s' for channel '%s'; defaulting to '%s'",
                self.get_name(),
                msg_type,
                channel_mode,
                fallback,
            )
            return fallback
        return normalized

    def _normalize_detection_config(self, cfg: Optional[dict]) -> dict:
        """Normalize detection configuration."""
        if not cfg or not isinstance(cfg, dict):
            return {}
        out = dict(cfg)
        if "distance" in out and "range" not in out:
            out["range"] = out["distance"]
        if "range" in out and "distance" not in out:
            out["distance"] = out["range"]
        return out

    def _resolve_detection_frequency(self) -> Optional[float]:
        """Return detection frequency in Hz."""
        cfg = self.detection_config
        if not cfg:
            return 1.0
        keys = ("acquisition_per_second", "acquisition_frequency", "frequency", "rate", "per_second")
        for key in keys:
            if key in cfg:
                try:
                    value = float(cfg[key])
                    if value <= 0:
                        return None
                    return value
                except (TypeError, ValueError):
                    logger.warning("%s invalid detection frequency '%s'", self.get_name(), cfg[key])
        return 1.0

    def _resolve_detection_range(self):
        """Resolve the detection range configured for this agent."""
        config_range = None
        if isinstance(getattr(self, "detection_config", None), dict):
            config_range = self.detection_config.get("range", self.detection_config.get("distance"))
        legacy_settings = self.config_elem.get("detection_settings", {}) or {}
        candidate = (
            config_range if config_range is not None else legacy_settings.get("range", legacy_settings.get("distance"))
        )
        if candidate is None:
            candidate = self.config_elem.get("perception_distance")
        if candidate is None:
            candidate = getattr(self, "perception_distance", None)
        if candidate is None:
            return 0.1
        if isinstance(candidate, str):
            normalized = candidate.strip().lower()
            if normalized in ("inf", "infinite", "none", "max"):
                return math.inf
            candidate = normalized
        try:
            value = float(candidate)
        except (TypeError, ValueError):
            logger.warning("%s invalid detection range '%s'; using default 0.1", self.get_name(), candidate)
            return 0.1
        if value <= 0:
            return 0.1
        return value

    def _allowed_nodes_for_channel(self, channel: str, hierarchy) -> Optional[set[str]]:
        """Return allowed hierarchy nodes for a given channel according to restrictions."""
        if not self.information_restrictions or channel not in (self.information_restrictions.get("targets") or {}):
            return None
        if hierarchy is None:
            return None
        mode = self.information_restrictions.get("mode")
        direction = self.information_restrictions.get("direction", "both")
        my_node = getattr(self, "hierarchy_node", None)
        if my_node is None:
            return None
        if mode == "node":
            return {my_node}
        if mode not in {"branch", "tree"}:
            return None
        allowed = {my_node}
        if direction in {"down", "both", "flat"}:
            allowed.update(hierarchy.descendants_of(my_node))
        if direction in {"up", "both"}:
            path = hierarchy.path_to_root(my_node)
            allowed.update(path)
            if direction == "both":
                for ancestor in path:
                    allowed.update(hierarchy.children_of(ancestor))
        if direction == "flat":
            parent = hierarchy.parent_of(my_node)
            if parent is not None:
                allowed.update(hierarchy.children_of(parent))
        return allowed

    def is_allowed_by_scope(self, target_node, channel: str, hierarchy) -> bool:
        """Return True if scope restrictions allow interacting with target_node."""
        if target_node == self.hierarchy_node:
            return True
        allowed = self._allowed_nodes_for_channel(channel, hierarchy)
        if allowed is None:
            return True
        if target_node is None:
            return False
        return target_node in allowed

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------
    def run(self, tick, arena_shape, objects, agents):
        """Run the simulation routine (implemented by MovableAgent)."""
        pass

    def prepare_for_run(self, objects: dict, agents: dict):
        """Hook called before the simulation starts."""
        pass
