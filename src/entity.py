# ------------------------------------------------------------------------------
#  CollectiPy
#  Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Entity and Agent classes for the simulator.

This module has been extended with a minimal plugin
system for movement models. The original behaviour is
preserved when no plugins are registered.
"""
import hashlib, math, logging
from typing import Optional
import numpy as np
from random import Random
from geometry_utils.vector3D import Vector3D
from bodies.shapes3D import Shape3DFactory
from plugin_registry import get_logic_model, get_movement_model, get_motion_model
from models.utils import normalize_angle
import models  # noqa: F401  # ensure built-in models register themselves

from logging_utils import get_logger, configure_logging

logger = get_logger("entity")

VALID_MESSAGE_CHANNELS = {"single", "dual"}
CHANNEL_TYPE_MATRIX = {
    "single": {"hand_shake", "rebroadcast"},
    "dual": {"broadcast", "rebroadcast", "hand_shake"}
}
DEFAULT_RX_RATE = 4.0

def splitmix32(x):
    x = (x + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
    x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9 & 0xFFFFFFFFFFFFFFFF
    x = (x ^ (x >> 27)) * 0x94D049BB133111EB & 0xFFFFFFFFFFFFFFFF
    x = x ^ (x >> 31)
    return x & 0xFFFFFFFF

def make_agent_seed(global_seed, entity_type, entity_id):
    base = f"{global_seed}|{entity_type}|{entity_id}"
    h1 = hashlib.sha256(base.encode()).digest()
    h2 = hashlib.blake2s(h1).digest()
    x = int.from_bytes(h2[:8], "little")
    return splitmix32(x)

class EntityFactory:
    
    """Entity factory."""
    @staticmethod
    def create_entity(entity_type:str,config_elem: dict,specs,_id:int=0):
        """Create entity."""
        configure_logging(
            settings = specs[0],
            config_path = specs[1],
            project_root = specs[2],
        )
        check_type = entity_type.split('_')[0]+'_'+entity_type.split('_')[1]
        if check_type == "agent_static":
            entity = StaticAgent(entity_type,config_elem,_id)
        elif check_type == "agent_movable":
            entity = MovableAgent(entity_type,config_elem,_id)
        elif check_type == "object_static":
            entity = StaticObject(entity_type,config_elem,_id)
        elif check_type == "object_movable":
            entity = MovableObject(entity_type,config_elem,_id)
        else:
            raise ValueError(f"Invalid agent type: {entity_type}")
        logger.info("Created entity %s (id=%s)", entity.get_name(), _id)
        return entity

class Entity:
    """Entity."""

    _class_registry: dict[str, dict] = {}
    _used_prefixes: set[tuple[str, str]] = set()
    def __init__(self,entity_type:str, config_elem: dict,_id:int=0):
        """Initialize the instance."""
        self.entity_type = entity_type
        self._id = _id
        self._entity_uid = self._build_entity_uid(entity_type, _id)
        self.position_from_dict = False
        self.orientation_from_dict = False
        self.color = config_elem.get("color","black")
        self.hierarchy_node = config_elem.get("hierarchy_node", "0")
        self.hierarchy_target = self.hierarchy_node
        self.hierarchy_level = None
        self.task = config_elem.get("task") if isinstance(config_elem, dict) else None
        self.spawn_params = None
    
    def get_name(self):
        """Return the name."""
        return self._entity_uid

    def get_position_from_dict(self):
        """Return the position from dict."""
        return self.position_from_dict
    
    def get_orientation_from_dict(self):
        """Return the orientation from dict."""
        return self.orientation_from_dict

    def reset(self):
        """Reset the component state."""
        self._reset_detection_scheduler()

    def entity(self) -> str:
        """Return the full entity type."""
        return self.entity_type

    def get_hierarchy_node(self):
        """Return the hierarchy node."""
        return self.hierarchy_node

    def set_hierarchy_node(self, node_id):
        """Set the hierarchy node."""
        self.hierarchy_node = node_id

    def get_hierarchy_target(self):
        """Return the hierarchy target."""
        return self.hierarchy_target

    def set_hierarchy_target(self, node_id):
        """Set the hierarchy target."""
        self.hierarchy_target = node_id

    def get_hierarchy_level(self):
        """Return the hierarchy level."""
        return self.hierarchy_level

    def set_hierarchy_level(self, level):
        """Set the hierarchy level."""
        self.hierarchy_level = level

    def get_task(self):
        """Return the configured task identifier."""
        return self.task

    def set_task(self, task: str | None):
        """Set the task identifier available to other subsystems."""
        self.task = task

    @classmethod
    def _normalize_class_label(cls, entity_type: str) -> str:
        """Return the base class label extracted from the entity type."""
        if not entity_type:
            return ""
        lowered = str(entity_type)
        if entity_type.startswith("agent_"):
            return lowered.split("agent_", 1)[1]
        if entity_type.startswith("object_"):
            return lowered.split("object_", 1)[1]
        return lowered

    @classmethod
    def _sanitize_token(cls, token: str, default: str = "x") -> str:
        """Sanitize a token so it does not contain separators used in the UID."""
        if not token:
            return default
        cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in str(token).strip())
        cleaned = cleaned.strip("._#")
        return cleaned or default

    @classmethod
    def _primary_char(cls, label: str) -> str:
        """Return the leading alphanumeric char for the y component."""
        for ch in label:
            if ch.isalnum():
                return ch
        return "x"

    @classmethod
    def _edge_chars(cls, label: str) -> str:
        """Return first+last alphanumeric characters of the label."""
        chars = [ch for ch in label if ch.isalnum()]
        if not chars:
            return "xx"
        if len(chars) == 1:
            return chars[0]
        return f"{chars[0]}{chars[-1]}"

    @classmethod
    def _claim_class_uid(cls, class_label: str, origin_kind: str) -> tuple[str, str]:
        """Resolve and reserve the (x, y) pair for a class, enforcing uniqueness."""
        label = cls._sanitize_token(class_label, "class")
        origin = cls._sanitize_token(origin_kind or "entity", "entity")
        existing = cls._class_registry.get(label)
        if existing:
            if existing["origin"] != origin:
                raise ValueError(f"Duplicate class name '{label}' used for both {existing['origin']} and {origin}")
            return existing["x"], existing["y"]
        base_x = cls._sanitize_token(label, "class")
        base_y = cls._primary_char(label)
        chosen_x, chosen_y = base_x, base_y
        if (chosen_x, chosen_y) in cls._used_prefixes:
            chosen_y = cls._edge_chars(label)
            if (chosen_x, chosen_y) in cls._used_prefixes:
                base_x = f"{base_x}{cls._edge_chars(label)}"
                chosen_x = base_x
                suffix = 1
                while (chosen_x, chosen_y) in cls._used_prefixes:
                    suffix += 1
                    chosen_x = f"{base_x}{suffix}"
        cls._class_registry[label] = {"x": chosen_x, "y": chosen_y, "origin": origin}
        cls._used_prefixes.add((chosen_x, chosen_y))
        return chosen_x, chosen_y

    def _build_entity_uid(self, entity_type: str, numeric_id: int | str) -> str:
        """Construct the stable UID in the form x.y#z."""
        class_label = self._normalize_class_label(entity_type)
        origin_kind = entity_type.split("_", 1)[0] if entity_type else "entity"
        x_token, y_token = self._claim_class_uid(class_label, origin_kind)
        z_token = self._sanitize_token(numeric_id, "0") if isinstance(numeric_id, str) else str(numeric_id)
        return f"{x_token}.{y_token}#{z_token}"
    
class Object(Entity):    
    """Object."""
    def __init__(self,entity_type:str, config_elem: dict,_id:int=0):
        """Initialize the instance."""
        super().__init__(entity_type,config_elem,_id)
        if not config_elem.get("_id") in ("idle","interactive"):
            raise ValueError(f"Invalid object type: {self.entity_type}")

class Agent(Entity):
    """Agent."""
    def __init__(self, entity_type:str, config_elem:dict, _id:int=0):
        """Initialize the instance."""
        super().__init__(entity_type, config_elem, _id)
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
        self.msgs_per_sec = self._resolve_message_rate("tx_per_second", "messages_per_seconds", 1.0)
        self.msg_receive_per_sec = self._resolve_message_rate("rx_per_second", "receive_per_seconds", DEFAULT_RX_RATE)
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
        self._handshake_timeout_ticks = self._resolve_handshake_timeout(
            self.messages_config.get("handshake_timeout")
        )
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

    def should_send_message(self, tick):
        """Return True if the agent can transmit during this tick."""
        _ = tick
        if not self.msg_enable or self._msg_send_quanta <= 0:
            return False
        self._msg_send_budget = min(self._msg_send_budget + self._msg_send_quanta, self._msg_send_budget_cap)
        if self._msg_send_budget >= 1.0:
            self._msg_send_budget -= 1.0
            return True
        return False

    def send_message(self,tick):
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
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("%s sent message at tick %s: %s", self.get_name(), tick, payload)

    def receive_messages(self, tick):
        """Receive messages."""
        if not self.msg_enable or not self.message_bus or self._msg_receive_quanta <= 0:
            return []
        if self.msg_channel_mode == "single" and self._last_tx_tick == tick:
            return []
        self._msg_receive_budget = min(self._msg_receive_budget + self._msg_receive_quanta, self._msg_receive_budget_cap)
        allowed = int(self._msg_receive_budget)
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
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("%s received %d messages", self.get_name(), len(messages))
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

    def _compose_message_payload(self, tick: int) -> dict:
        """Return the standard payload enriched with custom fields."""
        payload = dict(self._message_custom_fields)
        position = self.get_position()
        payload.update({
            "tick": tick,
            "position": (
                getattr(position, "x", 0.0),
                getattr(position, "y", 0.0),
                getattr(position, "z", 0.0)
            ),
            "agent_id": self.get_name(),
            "entity": self.entity(),
            "rebroadcast_count": 0,
            "source_agent": self.get_name(),
            "last_forward_by": self.get_name()
        })
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
        return {
            "state": state,
            "owner": self.get_name(),
            "partner": partner,
            "token": token
        }

    def _handle_handshake_messages(self, messages: list[dict], tick: int) -> None:
        """Update the local state machine based on received handshake payloads."""
        for msg in messages:
            block = msg.get("handshake")
            if not block:
                continue
            state = block.get("state") or msg.get("dialogue_state")
            peer = (
                block.get("owner")
                or msg.get("source_agent")
                or msg.get("agent_id")
                or msg.get("from")
            )
            token = block.get("token")
            if not peer or not state:
                continue
            if state == "invite":
                if self.handshake_partner or not self._handshake_accept_enabled:
                    continue
                self._handshake_pending_accept = {"partner": peer, "token": token}
                self._handshake_last_seen_tick = tick
            elif state == "accept":
                if self._handshake_state == "awaiting_accept" and token == self._handshake_token:
                    self.handshake_partner = peer
                    self._handshake_state = "connected"
                    self._handshake_last_seen_tick = tick
            elif state == "end":
                if self.handshake_partner == peer:
                    self._reset_handshake_state()
            else:
                if self.handshake_partner == peer:
                    self._handshake_last_seen_tick = tick

    def _handshake_check_timeout(self, tick: int) -> None:
        """Schedule a termination when the peer stops responding."""
        if (
            self.handshake_partner
            and self._handshake_timeout_ticks > 0
            and self._handshake_last_seen_tick >= 0
            and tick - self._handshake_last_seen_tick > self._handshake_timeout_ticks
        ):
            self._handshake_end_requested = True

    def _reset_handshake_state(self) -> None:
        """Return the handshake controller to its idle state."""
        self.handshake_partner = None
        self._handshake_state = "idle"
        self._handshake_token = None
        self._handshake_pending_accept = None
        self._handshake_manual_request = False
        self._handshake_end_requested = False
        self._handshake_request_tick = -1
        self._handshake_last_seen_tick = -1

    def _resolve_handshake_timeout(self, timeout_value) -> int:
        """Convert the configured timeout (seconds) into ticks."""
        if timeout_value in (None, "auto"):
            seconds = 5.0
        else:
            try:
                seconds = float(timeout_value)
            except (TypeError, ValueError):
                seconds = 5.0
        if seconds <= 0:
            return 0
        ticks = int(round(seconds * max(1, int(self.ticks_per_second))))
        return max(0, ticks)

    def request_handshake(self) -> bool:
        """Request a new handshake broadcast (used by plugins)."""
        if self.msg_type != "hand_shake":
            return False
        if self.handshake_partner:
            return False
        self._handshake_manual_request = True
        return True

    def terminate_handshake(self) -> bool:
        """Schedule a graceful termination of the active handshake."""
        if self.msg_type != "hand_shake":
            return False
        if not self.handshake_partner:
            return False
        self._handshake_end_requested = True
        return True

    def set_handshake_autostart(self, enabled: bool) -> None:
        """Enable/disable automatic discovery broadcasts."""
        self._handshake_auto_request = bool(enabled)

    def set_handshake_acceptance(self, enabled: bool) -> None:
        """Enable/disable automatic acceptance of incoming invites."""
        self._handshake_accept_enabled = bool(enabled)

    def handshake_active(self) -> bool:
        """Return True when the agent is currently paired."""
        return bool(self.handshake_partner)

    def _prepare_rebroadcast_payload(self, tick: int) -> dict:
        """Decide whether to send own data or forward someone else's message."""
        eligible = self._eligible_rebroadcast_messages()
        should_forward = bool(eligible and self.random_generator.random() < 0.5)
        if should_forward:
            original = dict(self.random_generator.choice(eligible))
            original_count = int(original.get("rebroadcast_count", original.get("relay_level", 0)) or 0)
            original["rebroadcast_count"] = original_count + 1
            original.setdefault("source_agent", original.get("agent_id"))
            original["last_forward_by"] = self.get_name()
            original["tick_relayed"] = tick
            return original
        payload = self._compose_message_payload(tick)
        payload["rebroadcast_count"] = 0
        payload["source_agent"] = self.get_name()
        payload["last_forward_by"] = self.get_name()
        payload["tick_emitted"] = tick
        return payload

    def _eligible_rebroadcast_messages(self):
        """Return buffered messages that can still be relayed."""
        if not self.messages or self.rebroadcast_limit <= 0:
            return []
        eligible = []
        limit = self.rebroadcast_limit
        for msg in self.messages:
            if not isinstance(msg, dict):
                continue
            try:
                count = int(msg.get("rebroadcast_count", msg.get("relay_level", 0)) or 0)
            except (TypeError, ValueError):
                count = 0
            if math.isinf(limit) or count < limit:
                eligible.append(msg)
        return eligible

    def get_messages_by_sender(self) -> dict:
        """Return messages grouped by sender identifier (lazy-built)."""
        if self._messages_by_sender is None:
            self._build_message_indexes()
        return self._messages_by_sender

    def get_messages_by_entity(self) -> dict:
        """Return messages grouped by entity/class (lazy-built)."""
        if self._messages_by_entity is None:
            self._build_message_indexes()
        return self._messages_by_entity

    def _invalidate_message_indexes(self) -> None:
        """Reset cached message groupings to keep a single authoritative list."""
        self._messages_by_sender = None
        self._messages_by_entity = None

    def _build_message_indexes(self) -> None:
        """Rebuild grouping maps using the unified message list."""
        by_sender: dict[str, list[dict]] = {}
        by_entity: dict[str, list[dict]] = {}
        for msg in self.messages:
            if not isinstance(msg, dict):
                continue
            sender = (
                msg.get("source_agent")
                or msg.get("agent_id")
                or msg.get("from")
            )
            if sender:
                by_sender.setdefault(str(sender), []).append(msg)
            entity = msg.get("entity")
            if entity:
                by_entity.setdefault(str(entity), []).append(msg)
        self._messages_by_sender = by_sender
        self._messages_by_entity = by_entity

    def _compute_rate_quanta(self, rate_per_second: float) -> float:
        """Convert a messages-per-second value into the tokens added per tick."""
        ticks = max(1.0, float(self.ticks_per_second))
        rate = max(0.0, float(rate_per_second))
        return rate / ticks
    
    def _resolve_message_rate(self, preferred_key: str, legacy_key: str, default_value: float) -> float:
        """Resolve TX/RX quotas supporting both the new and legacy config keys."""
        value = self.messages_config.get(preferred_key)
        if value is None:
            # Backwards compatibility with legacy config names.
            value = self.messages_config.get(legacy_key, default_value)
        if value is None:
            value = default_value
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid message rate '%s' for %s (%s), falling back to %.2f",
                value,
                self.get_name(),
                preferred_key,
                default_value
            )
            numeric = float(default_value)
        return max(0.0, numeric)

    @staticmethod
    def _resolve_channel_mode(value) -> str:
        """Normalise the channel mode."""
        mode = str(value or "dual").strip().lower()
        if mode not in VALID_MESSAGE_CHANNELS:
            return "dual"
        return mode

    @staticmethod
    def _resolve_message_type(msg_type, channel_mode) -> str:
        """Validate that the requested message type is compatible with the channel mode."""
        resolved = str(msg_type or "broadcast").strip().lower()
        allowed = CHANNEL_TYPE_MATRIX.get(channel_mode, CHANNEL_TYPE_MATRIX["dual"])
        if resolved not in allowed:
            raise ValueError(
                f"Message type '{resolved}' is not allowed for channel mode '{channel_mode}'. "
                f"Allowed: {', '.join(sorted(allowed))}"
            )
        return resolved
    
    def _resolve_rebroadcast_limit(self) -> float:
        """Resolve how many times a message can be rebroadcast by this agent."""
        if self.msg_type != "rebroadcast":
            return 0.0
        limit_value = self.messages_config.get("rebroadcast_steps")
        if limit_value is None:
            hops = self.messages_config.get("rebroadcast_hops")
            if hops is not None:
                logger.warning(
                    "%s uses legacy 'rebroadcast_hops'; please switch to 'rebroadcast_steps'",
                    self.get_name()
                )
                limit_value = hops
        if limit_value is None:
            return math.inf
        if isinstance(limit_value, str):
            limit_value = limit_value.strip().lower()
            if limit_value in ("inf", "infinite", "none"):
                return math.inf
        try:
            numeric = float(limit_value)
        except (TypeError, ValueError):
            return math.inf
        if numeric <= 0:
            return math.inf
        return numeric

    def _normalize_message_timer(self, value):
        """Normalize the optional message timer configuration."""
        if value is None:
            return None
        if not isinstance(value, dict):
            logger.warning("%s invalid timer config '%s'; expected object", self.get_name(), value)
            return None
        if not value:
            return None
        raw_distribution = value.get("distribution", None)
        distribution = None if raw_distribution is None else str(raw_distribution).strip().lower()
        if distribution == "normal":
            distribution = "gaussian"
        if distribution in {"", "none"}:
            distribution = None
        supported = {"gaussian", "uniform", "exponential", "fixed"}
        if distribution and distribution not in supported:
            logger.warning(
                "%s timer distribution '%s' unsupported; using fixed delay",
                self.get_name(),
                distribution
            )
            distribution = None
        average = value.get("average", None)
        if average is None:
            return None
        try:
            average = float(average)
        except (TypeError, ValueError):
            logger.warning("%s timer average '%s' invalid; timer disabled", self.get_name(), average)
            return None
        if average < 0:
            logger.warning("%s timer average must be >=0, got %s; clamping to 0", self.get_name(), average)
            average = 0.0
        return {"distribution": distribution, "average": average, "reset_each_cycle": average == 0.0}

    def _apply_message_timers(self, messages):
        """Attach TTL metadata to newly received messages."""
        if not self.msg_timer_config or not messages:
            return
        if self.msg_timer_config.get("reset_each_cycle"):
            for msg in messages:
                msg.pop("_ttl_ticks", None)
            return
        for msg in messages:
            ttl = self._next_message_timer_ticks()
            if ttl is None:
                msg.pop("_ttl_ticks", None)
                continue
            msg["_ttl_ticks"] = ttl

    def _next_message_timer_ticks(self):
        """Return the timer duration in ticks."""
        if not self.msg_timer_config:
            return None
        if self.msg_timer_config.get("reset_each_cycle"):
            return None
        seconds = self._sample_message_timer_seconds()
        if seconds is None:
            return None
        if math.isinf(seconds):
            return math.inf
        ticks = max(1, int(round(seconds * max(1.0, float(self.ticks_per_second)))))
        return ticks

    def _sample_message_timer_seconds(self):
        """Sample a duration from the configured distribution."""
        cfg = self.msg_timer_config
        if not cfg:
            return None
        if cfg.get("reset_each_cycle"):
            return None
        average = cfg["average"]
        dist = cfg["distribution"] or "fixed"
        rng = self.random_generator
        if dist == "exponential":
            try:
                return rng.expovariate(1.0 / average)
            except ZeroDivisionError:
                return average
        if dist == "uniform":
            return rng.uniform(0.0, average)
        if dist == "gaussian":
            stddev = max(average / 3.0, 1e-6)
            return max(0.0, rng.gauss(average, stddev))
        # fixed/default
        return average

    def _refresh_message_timers(self):
        """Decrement TTL metadata and purge expired messages."""
        if not self.msg_timer_config:
            return
        if self.msg_timer_config.get("reset_each_cycle"):
            if self.messages:
                self.messages = []
                self._invalidate_message_indexes()
            return
        before = len(self.messages)
        self.messages = self._tick_message_collection(self.messages)
        if len(self.messages) != before:
            self._invalidate_message_indexes()

    def _tick_message_collection(self, collection):
        """Return a filtered list after decrementing TTLs."""
        if not collection:
            return []
        filtered = []
        for msg in collection:
            if not isinstance(msg, dict):
                continue
            ttl = msg.get("_ttl_ticks")
            if ttl is None or math.isinf(ttl):
                filtered.append(msg)
                continue
            ttl -= 1
            if ttl > 0:
                msg["_ttl_ticks"] = ttl
                filtered.append(msg)
            else:
                msg.pop("_ttl_ticks", None)
        return filtered

    def _parse_information_restrictions(self, config):
        """Normalize hierarchy-based restrictions for detection/messages/movement."""
        restrictions = {}
        if not config:
            return restrictions

        # Local, per-entity restrictions; overlay-level information_scope is handled
        # separately via the hierarchy context.
        channels = ("messages", "detection", "movement")

        has_explicit = isinstance(config, dict) and any(key in config for key in channels)
        if has_explicit:
            for channel in channels:
                normalized = self._normalize_scope_value(config.get(channel))
                if normalized:
                    restrictions[channel] = normalized
        else:
            normalized = self._normalize_scope_value(config)
            if normalized:
                for channel in channels:
                    restrictions[channel] = normalized
        return restrictions


    def _normalize_scope_value(self, value):
        """Normalize textual/dict scope descriptors."""
        if value in (None, False):
            return None
        if value is True:
            value = "node"
        mode = None
        direction = "both"
        if isinstance(value, str):
            token = value.strip().lower()
            if not token or token in {"none", "all", "any", "off"}:
                return None
            if ":" in token:
                token, direction = token.split(":", 1)
                direction = direction.strip() or "both"
            mode = token
        elif isinstance(value, dict):
            mode = str(value.get("mode", "")).strip().lower()
            direction = str(value.get("direction", "both")).strip().lower() or "both"
        else:
            logger.warning("%s invalid information_scope value '%s'; ignoring", self.get_name(), value)
            return None
        if mode not in {"node", "branch"}:
            logger.warning("%s information_scope mode '%s' is not supported", self.get_name(), mode)
            return None
        if mode == "node":
            direction = "both"
        elif direction not in {"up", "down", "both", "flat"}:
            logger.warning(
                "%s information_scope direction '%s' invalid; defaulting to 'both'",
                self.get_name(),
                direction
            )
            direction = "both"
        return {"mode": mode, "direction": direction}

    def _invalidate_info_scope_cache(self):
        """Clear cached hierarchy computations."""
        self._info_scope_cache = {}

    def _allowed_nodes_for_channel(self, channel: str, hierarchy, scope: dict | None = None):
        """Return cached set of allowed nodes for the provided channel.

        The returned set reflects:
        - overlay-level information_scope (if defined on the hierarchy), and
        - per-entity information_restrictions (if defined for this channel).

        If neither is present, None is returned to signal "no restriction".
        """
        if not self.hierarchy_node:
            return None

        hierarchy = hierarchy or self.hierarchy_context
        if hierarchy is None:
            return None

        # ------------------------------------------------------------------
        # Overlay-level scope (hierarchy.information_scope).
        # ------------------------------------------------------------------
        overlay_scope = None
        overlay_info = getattr(hierarchy, "information_scope", None)
        if isinstance(overlay_info, dict):
            overlay_channels = overlay_info.get("over")
            # overlay_info["over"] is usually a set in HierarchyOverlay, but
            # we treat it generically as an iterable of channel names.
            if overlay_channels and channel in overlay_channels:
                overlay_scope = {
                    "mode": overlay_info.get("mode"),
                    "direction": overlay_info.get("direction", "both"),
                }

        # ------------------------------------------------------------------
        # Per-entity local scope (self.information_restrictions).
        # ------------------------------------------------------------------
        if scope is None:
            scope = self.information_restrictions.get(channel)

        # If neither overlay nor local scope exists, the channel is unrestricted.
        if overlay_scope is None and not scope:
            return None

        cache = self._info_scope_cache.setdefault(channel, {})
        cache_key = (
            self.hierarchy_node,
            # overlay-level
            overlay_scope.get("mode") if overlay_scope else None,
            overlay_scope.get("direction") if overlay_scope else None,
            # local, per-entity
            scope.get("mode") if scope else None,
            scope.get("direction") if scope else None,
        )

        if cache.get("key") == cache_key:
            return cache.get("nodes")

        allowed_sets = []

        if overlay_scope:
            allowed_sets.append(self._compute_scope_nodes(overlay_scope, hierarchy))
        if scope:
            allowed_sets.append(self._compute_scope_nodes(scope, hierarchy))

        if not allowed_sets:
            allowed = None
        else:
            allowed = allowed_sets[0]
            for subset in allowed_sets[1:]:
                allowed = allowed & subset

        cache["key"] = cache_key
        cache["nodes"] = allowed
        return allowed


    def _compute_scope_nodes(self, scope: dict, hierarchy) -> set[str]:
        """Compute which hierarchy nodes are visible for the provided scope."""
        current = self.hierarchy_node
        if not current:
            return set()
        if scope.get("mode") == "node":
            return {current}
        allowed = {current}
        direction = scope.get("direction", "both")
        if direction in {"both", "up"}:
            allowed.update(hierarchy.path_to_root(current))
        if direction in {"both", "down"}:
            allowed.update(hierarchy.descendants_of(current))
        if direction == "flat":
            parent = hierarchy.parent_of(current)
            siblings = hierarchy.children_of(parent) if parent is not None else []
            allowed.update(siblings)
        return set(allowed)

    def _sync_shape_hierarchy_metadata(self):
        """Store the latest hierarchy info in the underlying shape metadata."""
        shape = getattr(self, "shape", None)
        if not shape or not hasattr(shape, "metadata"):
            return
        shape.metadata["hierarchy_node"] = self.hierarchy_node
        shape.metadata["entity_name"] = self.get_name()

    def _normalize_detection_config(self, config_value):
        """Return detection settings as a mutable dict."""
        if isinstance(config_value, dict):
            cfg = dict(config_value)
        elif config_value is None:
            cfg = {}
        else:
            cfg = {"type": config_value}
        raw_type = cfg.get("type")
        if raw_type is None:
            cfg["type"] = "GPS"
        else:
            type_str = str(raw_type).strip()
            cfg["type"] = type_str if type_str else "GPS"
        return cfg

    def _resolve_detection_frequency(self) -> float:
        """Resolve how often detection snapshots can be acquired."""
        cfg = self.detection_config or {}
        candidate = None
        for key in ("acquisition_per_second", "acquisition_frequency", "frequency", "acquisition_rate"):
            if cfg.get(key) is not None:
                candidate = cfg.get(key)
                break
        if candidate is None:
            return 1
        if isinstance(candidate, str):
            normalized = candidate.strip().lower()
            if normalized in ("inf", "infinite", "none", "max"):
                return math.inf
        try:
            numeric = float(candidate)
        except (TypeError, ValueError):
            logger.warning(
                "%s invalid detection acquisition '%s'; defaulting to infinite rate",
                self.get_name(),
                candidate
            )
            return 1
        if numeric <= 0:
            return 0.0
        return numeric

    def _configure_detection_scheduler(self):
        """Precompute helper values for throttling detection sampling."""
        rate = self.detection_rate_per_sec
        if math.isinf(rate):
            self._detection_quanta = math.inf
            self._detection_budget_cap = math.inf
        elif rate <= 0:
            self._detection_quanta = 0.0
            self._detection_budget_cap = 0.0
        else:
            self._detection_quanta = self._compute_rate_quanta(rate)
            self._detection_budget_cap = max(1.0, rate * 2.0)
        self._reset_detection_scheduler()

    def _reset_detection_scheduler(self):
        """Reset detection throttling state."""
        self._detection_budget = 0.0
        self._last_detection_tick = -1

    def should_sample_detection(self, tick: int | None = None) -> bool:
        """Return True if the agent can run detection during this tick."""
        if tick is None or self._detection_quanta is None:
            return True
        if tick == self._last_detection_tick:
            return False
        if self._detection_quanta == 0.0:
            return False
        if math.isinf(self._detection_quanta):
            self._last_detection_tick = tick
            return True
        self._detection_budget = min(
            self._detection_budget + self._detection_quanta,
            self._detection_budget_cap
        )
        if self._detection_budget >= 1.0:
            self._detection_budget -= 1.0
            self._last_detection_tick = tick
            return True
        return False
    
    def ticks(self):
        """Return the configured tick rate."""
        return self.ticks_per_second
    
    def set_random_generator(self,random_seed):
        """Set the random generator."""
        seed = make_agent_seed(random_seed, self.entity_type, int(self._id))
        self.random_generator.seed(seed)
        logger.debug("%s seeded RNG with %s", self.get_name(), seed)

    def get_random_generator(self):
        """Return the random generator."""
        return self.random_generator
    
    def get_detection_range(self):
        """Return the configured detection range."""
        return getattr(self, "detection_range", 0.1)

    def allows_hierarchical_link(self, target_node: str | None, channel: str, hierarchy=None) -> bool:
        """Return True if hierarchy/overlay constraints allow interacting with `target_node`."""
        hierarchy = hierarchy or self.hierarchy_context
        if hierarchy is None or not self.hierarchy_node:
            return True

        allowed = self._allowed_nodes_for_channel(channel, hierarchy)
        if allowed is None:
            # No restriction for this channel (no overlay and no local scope).
            return True
        if target_node is None:
            # When restrictions exist but the target has no known node, treat it
            # as not allowed by default.
            return False
        return target_node in allowed


    def run(self,tick,arena_shape,objects,agents):
        """Run the simulation routine."""
        pass

    def prepare_for_run(self, objects: dict, agents: dict):
        """Hook called before the simulation starts."""
        pass

class StaticObject(Object):
    """Static object."""
    def __init__(self,entity_type:str, config_elem:dict,_id:int=0):
        """Initialize the instance."""
        super().__init__(entity_type,config_elem,_id)
        if config_elem.get("shape") in ("circle","square","rectangle"):
            self.shape_type = "flat"
        elif config_elem.get("shape") in ("sphere","cube","cuboid","cylinder"):
            self.shape_type = "dense"
        else: raise ValueError(f"Invalid object type: {self.entity_type}")
        self.shape = Shape3DFactory.create_shape("object",config_elem.get("shape","point"), {key:val for key,val in config_elem.items()})
        self.position = Vector3D()
        self.orientation = Vector3D()
        self.start_position = Vector3D()
        self.start_orientation = Vector3D()
        temp_strength = config_elem.get("strength", [10])
        if temp_strength != None:
            try:
                self.strength = temp_strength[_id]
            except:
                self.strength = temp_strength[-1]
        temp_uncertainty = config_elem.get("uncertainty", [0])
        if temp_uncertainty != None:
            try:
                self.uncertainty = temp_uncertainty[_id]
            except:
                self.uncertainty = temp_uncertainty[-1]
        temp_position = config_elem.get("position", None)
        if temp_position != None:
            self.position_from_dict = True
            try:
                self.start_position = Vector3D(temp_position[_id][0],temp_position[_id][1],temp_position[_id][2])
            except:
                self.start_position = Vector3D(temp_position[-1][0],temp_position[-1][1],temp_position[-1][2])
        temp_orientation = config_elem.get("orientation", None)
        if temp_orientation != None:
            self.orientation_from_dict = True
            try:
                self.start_orientation = Vector3D(temp_orientation[_id][0],temp_orientation[_id][1],temp_orientation[_id][2])
            except:
                self.start_orientation = Vector3D(temp_orientation[-1][0],temp_orientation[-1][1],temp_orientation[-1][2])
            self.orientation = self.start_orientation

    def to_origin(self):
        """To origin."""
        self.position = Vector3D()
        self.orientation = Vector3D()
        self.shape.center = self.position
        self.shape.set_vertices()

    def set_start_position(self,new_position:Vector3D,_translate:bool = True):
        """Set the start position."""
        self.start_position = new_position
        self.set_position(new_position,_translate)

    def set_position(self,new_position:Vector3D,_translate:bool = True):
        """Set the position."""
        self.position = new_position
        if _translate: self.shape.translate(self.position)

    def set_start_orientation(self,new_orientation:Vector3D):
        """Set the start orientation."""
        self.start_orientation = new_orientation
        self.set_orientation(new_orientation)

    def set_orientation(self,new_orientation:Vector3D):
        """Set the orientation."""
        self.orientation = new_orientation
        self.shape.rotate(self.start_orientation.z)

    def get_start_position(self):
        """Return the start position."""
        return self.start_position
    
    def get_start_orientation(self):
        """Return the start orientation."""
        return self.start_orientation
    
    def get_position(self):
        """Return the position."""
        return self.position

    def get_orientation(self):
        """Return the orientation."""
        return self.orientation
    
    def get_strength(self):
        """Return the strength."""
        return self.strength

    def get_uncertainty(self):
        """Return the uncertainty."""
        return self.uncertainty
        
    def close(self):
        """Close the component resources."""
        del self.shape

    def get_shape(self):
        """Return the shape."""
        return self.shape

    def get_shape_type(self):
        """Return the shape type."""
        return self.shape_type
    
class StaticAgent(Agent):
    """Static agent."""
    def __init__(self,entity_type:str, config_elem:dict,_id:int=0):
        """Initialize the instance."""
        super().__init__(entity_type,config_elem,_id)
        if config_elem.get("shape") in ("sphere","cube","cuboid","cylinder"):
            self.shape_type = "dense"
        self.shape = Shape3DFactory.create_shape("agent",config_elem.get("shape","point"), {key:val for key,val in config_elem.items()})
        self.shape.add_attachment(Shape3DFactory.create_shape("mark","circle", {"_id":"led", "color":"red", "diameter":0.01}))
        self._level_attachment = None
        self._sync_shape_hierarchy_metadata()
        self.position = Vector3D()
        self.orientation = Vector3D()
        self.start_position = Vector3D()
        self.start_orientation = Vector3D()
        temp_position = config_elem.get("position", None)
        self.perception_distance = config_elem.get("perception_distance",0.1)
        if temp_position != None:
            self.position_from_dict = True
            try:
                self.start_position = Vector3D(temp_position[0],temp_position[1],temp_position[2])
            except:
                self.start_position = Vector3D(temp_position[-1][0],temp_position[-1][1],temp_position[-1][2])
        temp_orientation = config_elem.get("orientation", None)
        if temp_orientation != None:
            self.orientation_from_dict = True
            try:
                self.start_orientation = Vector3D(temp_orientation[0],temp_orientation[1],temp_orientation[2])
            except:
                self.start_orientation = Vector3D(temp_orientation[-1][0],temp_orientation[-1][1],temp_orientation[-1][2])
            self.orientation = self.start_orientation

    def to_origin(self):
        """To origin."""
        self.position = Vector3D()
        self.shape.center = self.position
        self.shape.set_vertices()

    def set_start_position(self,new_position:Vector3D,_translate:bool = True):
        """Set the start position."""
        self.start_position = new_position
        self.set_position(new_position,_translate)

    def set_position(self,new_position:Vector3D,_translate:bool = True):
        """Set the position."""
        self.position = new_position
        if _translate:
            self.shape.translate(self.position)

    def set_start_orientation(self,new_orientation:Vector3D):
        """Set the start orientation."""
        self.start_orientation = new_orientation
        self.set_orientation(new_orientation)

    def set_orientation(self,new_orientation:Vector3D):
        """Set the orientation."""
        self.orientation = new_orientation
        self.shape.rotate(self.start_orientation.z)

    def get_start_position(self):
        """Return the start position."""
        return self.start_position
    
    def get_start_orientation(self):
        """Return the start orientation."""
        return self.start_orientation
    
    def get_position(self):
        """Return the position."""
        return self.position

    def get_orientation(self):
        """Return the orientation."""
        return self.orientation

    def close(self):
        """Close the component resources."""
        del self.shape

    def get_shape(self):
        """Return the shape."""
        return self.shape

    def get_shape_type(self):
        """Return the shape type."""
        return self.shape_type
    
class MovableObject(StaticObject):
    """Movable object."""
    def __init__(self,entity_type:str, config_elem:dict,_id:int=0):
        """Initialize the instance."""
        super().__init__(entity_type,config_elem,_id)


class MovableAgent(StaticAgent):

    """Movable agent."""
    STOP    = 0
    FORWARD = 1
    LEFT    = 2
    RIGHT   = 3

    def __init__(self,entity_type:str, config_elem:dict,_id:int=0):
        """Initialize the instance."""
        super().__init__(entity_type,config_elem,_id)
        self.config_elem = config_elem
        self.max_absolute_velocity = float(config_elem.get("linear_velocity",0.01)) / self.ticks_per_second
        self.max_angular_velocity = int(config_elem.get("angular_velocity",10)) / self.ticks_per_second
        self.forward_vector = Vector3D()
        self.delta_orientation = Vector3D()
        self.goal_position = None
        self.prev_orientation = Vector3D()
        self.position = Vector3D()
        self.prev_position = Vector3D()
        self.prev_goal_distance = 0
        self.moving_behavior = config_elem.get("moving_behavior","random_walk")
        self.fallback_moving_behavior = config_elem.get("fallback_moving_behavior","none")
        self.logic_behavior = config_elem.get("logic_behavior")
        self.spin_model_params = config_elem.get("spin_model", {})
        # Resolve detection range before movement plugin creation so it propagates into detection models.
        self.detection_range = self._resolve_detection_range()
        self.wrap_config = None
        self.hierarchy_target = self.hierarchy_target or "0"
        self.hierarchy_node = "0"
        self.hierarchy_level = 0
        self._level_color_map = {}
        self._level_attachment = None
        self.max_turning_ticks = 160
        self.standard_motion_steps = 5*16
        self.crw_exponent = config_elem.get("crw_exponent",1)
        self.levy_exponent = config_elem.get("levy_exponent",1.75)
        self._movement_plugin = self._init_movement_model()
        self._logic_plugin = self._init_logic_model()

    def _init_movement_model(self):
        """Init movement model."""
        model = get_movement_model(self.moving_behavior, self)
        if model is None and self.moving_behavior != "random_walk":
            model = get_movement_model("random_walk", self)
        return model

    def _init_logic_model(self):
        """Init logic model."""
        return get_logic_model(self.logic_behavior, self)
    
    def _resolve_detection_range(self):
        """Resolve the detection range configured for this agent."""
        config_range = None
        if isinstance(getattr(self, "detection_config", None), dict):
            config_range = self.detection_config.get("range", self.detection_config.get("distance"))
        legacy_settings = self.config_elem.get("detection_settings", {}) or {}
        candidate = (
            config_range
            if config_range is not None
            else legacy_settings.get("range", legacy_settings.get("distance"))
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

    def reset(self):
        """Reset the component state."""
        if self._movement_plugin and hasattr(self._movement_plugin, "reset"):
            self._movement_plugin.reset()
        if self._logic_plugin and hasattr(self._logic_plugin, "reset"):
            self._logic_plugin.reset()
        self.turning_ticks = 0
        self.forward_ticks = 0
        self.motion = MovableAgent.STOP
        self.last_motion_tick = 0
        self.forward_vector = Vector3D()
        self.delta_orientation = Vector3D()
        self.goal_position = None
        self.prev_goal_distance = 0
        self._reset_detection_scheduler()
        self.clear_message_buffers()
        logger.info("%s reset with behavior %s", self.get_name(), self.moving_behavior)

    def get_spin_system_data(self):
        """Return the spin system data."""
        if self._movement_plugin and hasattr(self._movement_plugin, "get_spin_system_data"):
            return self._movement_plugin.get_spin_system_data()
        return None
    
    def get_max_absolute_velocity(self):
        """Return the max absolute velocity."""
        return self.max_absolute_velocity
    
    def get_prev_position(self):
        """Return the prev position."""
        return self.prev_position
    
    def get_prev_orientation(self):
        """Return the prev orientation."""
        return self.prev_orientation
    
    def get_position(self):
        """Return the position."""
        return self.position
    
    def get_orientation(self):
        """Return the orientation."""
        return self.orientation
    
    def get_forward_vector(self):
        """Return the forward vector."""
        return self.forward_vector

    def set_start_orientation(self,new_orientation:Vector3D):
        """Set the start orientation."""
        super().set_start_orientation(new_orientation)
        
    def set_orientation(self,new_orientation:Vector3D):
        """Set the orientation."""
        super().set_orientation(new_orientation)

    def prepare_for_run(self, objects:dict, agents:dict):
        """Prepare for run."""
        if self._movement_plugin and hasattr(self._movement_plugin, "pre_run"):
            self._movement_plugin.pre_run(objects, agents)
            logger.debug("%s performed pre-run hook via %s", self.get_name(), type(self._movement_plugin).__name__)
        if self._logic_plugin and hasattr(self._logic_plugin, "pre_run"):
            self._logic_plugin.pre_run(objects, agents)
            logger.debug("%s performed logic pre-run hook via %s", self.get_name(), type(self._logic_plugin).__name__)

    def post_step(self, position_correction: Vector3D):
        """Post step: apply collision correction as a delta, not as an absolute position."""
        if position_correction is not None:
            # Apply correction as displacement
            self.position = self.position + position_correction

            # Keep geometry in sync with the updated pose
            self.shape.translate(self.position)
            self.shape.translate_attachments(self.orientation.z)

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "%s position corrected by detector with delta %s -> new pos %s",
                    self.get_name(),
                    position_correction,
                    (self.position.x, self.position.y, self.position.z),
                )

    def run(self,tick:int,arena_shape:Shape3DFactory,objects:dict,agents:dict):
        """Run the simulation routine."""
        self.prev_position = self.position
        self.prev_orientation = self.orientation
        self._refresh_message_timers()
        self.linear_velocity_cmd = 0.0
        self.angular_velocity_cmd = 0.0
        if hasattr(self, "forward_vector"):
            self.forward_vector = Vector3D()
        if hasattr(self, "delta_orientation"):
            self.delta_orientation = Vector3D()
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("%s starting run tick=%s behavior=%s", self.get_name(), tick, self.moving_behavior)
        if self._logic_plugin:
            self._logic_plugin.step(self, tick, arena_shape, objects, agents)
        if not self._movement_plugin:
            raise ValueError("No movement model configured for agent")
        self._movement_plugin.step(self, tick, arena_shape, objects, agents)
        if self._logic_plugin and hasattr(self._logic_plugin, "after_movement"):
            self._logic_plugin.after_movement(self, tick, arena_shape, objects, agents)
        self._apply_motion(tick)
        # Keep the shape geometry in sync with the updated pose for collision checks.
        self.shape.translate(self.position)
        self.shape.translate_attachments(self.orientation.z)

    def _apply_motion(self, tick:int):
        """Apply the motion using the configured kinematic model."""
        if self._motion_model is not None:
            self._motion_model.step(self, tick)
        else:
            self._legacy_motion_step()
        self.shape.rotate(self.delta_orientation.z)
        self.shape.translate(self.position)
        self.shape.translate_attachments(self.orientation.z)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "%s applied motion -> position=%s orientation=%s delta=%s",
                self.get_name(),
                (self.position.x, self.position.y, self.position.z),
                self.orientation.z,
                (self.delta_orientation.x, self.delta_orientation.y, self.delta_orientation.z)
            )

    def _legacy_motion_step(self):
        """Fallback kinematic update preserving legacy behaviour."""
        self.position = self.position + getattr(self, "forward_vector", Vector3D())
        self.orientation = self.orientation + getattr(self, "delta_orientation", Vector3D())
        self.orientation.z = normalize_angle(self.orientation.z)
    
    def close(self):
        """Close the component resources."""
        return super().close()

    def enable_hierarchy_marker(self, level_colors: dict):
        """Enable the hierarchy marker."""
        if not level_colors:
            return
        self._level_color_map = dict(level_colors or {})
        if self._level_attachment is None:
            marker = Shape3DFactory.create_shape(
                "mark",
                "square",
                {"_id": "idle", "color": self._get_level_color(), "width": 0.012, "depth": 0.012}
            )
            marker.metadata["placement"] = "opposite"
            self.shape.add_attachment(marker)
            self._level_attachment = marker
        self._update_level_attachment_color()
        self.shape.translate_attachments(self.orientation.z)

    def _get_level_color(self, level: Optional[int] = None) -> str:
        """Return the level color."""
        if level is None:
            level = self.hierarchy_level if self.hierarchy_level is not None else 0
        if not self._level_color_map:
            return "black"
        return self._level_color_map.get(level, next(iter(self._level_color_map.values()), "black"))

    def _update_level_attachment_color(self):
        """Update level attachment color."""
        if not self._level_attachment:
            return
        self._level_attachment.set_color(self._get_level_color())

    def set_hierarchy_level(self, level):
        """Set the hierarchy level."""
        super().set_hierarchy_level(level)
        self._update_level_attachment_color()
    
