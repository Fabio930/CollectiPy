# ------------------------------------------------------------------------------
#  CollectiPy
# Copyright (c) 2025 Fabio Oddi
#
#  This file is part of CollectyPy, released under the BSD 3-Clause License.
#  You may use, modify, and redistribute this file according to the terms of the
#  license. Attribution is required if this code is used in other works.
# ------------------------------------------------------------------------------

"""Base entity definitions shared by agents and objects."""

from __future__ import annotations

from core.util.logging_util import get_logger

logger = get_logger("entity")


class Entity:
    """Base entity with hierarchy/task metadata and stable UID."""

    _class_registry: dict[str, dict] = {}
    _used_prefixes: set[tuple[str, str]] = set()

    def __init__(self, entity_type: str, config_elem: dict, _id: int = 0):
        """Initialize the instance."""
        self.entity_type = entity_type
        self._id = _id
        self._entity_uid = self._build_entity_uid(entity_type, _id)
        self.position_from_dict = False
        self.orientation_from_dict = False
        self.color = config_elem.get("color", "black")
        self.hierarchy_node = config_elem.get("hierarchy_node", "0")
        self.hierarchy_target = self.hierarchy_node
        self.hierarchy_level = None
        self.task = config_elem.get("task") if isinstance(config_elem, dict) else None
        self.spawn_params = None

    # ------------------------------------------------------------------
    # Identity / hierarchy helpers
    # ------------------------------------------------------------------
    def get_name(self):
        """Return the stable entity UID."""
        return self._entity_uid

    def entity(self) -> str:
        """Return the full entity type."""
        return self.entity_type

    def get_task(self):
        """Return the configured task identifier."""
        return self.task

    def set_task(self, task: str | None):
        """Set the task identifier available to other subsystems."""
        self.task = task

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

    # ------------------------------------------------------------------
    # Position/orientation defaults (overridden by subclasses)
    # ------------------------------------------------------------------
    def get_position_from_dict(self):
        """Return the position-from-config flag."""
        return self.position_from_dict

    def get_orientation_from_dict(self):
        """Return the orientation-from-config flag."""
        return self.orientation_from_dict

    def get_position(self):
        """Return the position (set by subclasses)."""
        return getattr(self, "position", None)

    def reset(self):
        """Reset the component state."""
        self._reset_detection_scheduler()

    def _reset_detection_scheduler(self):
        """Reset detection scheduler placeholder (overridden by agents)."""
        return None

    # ------------------------------------------------------------------
    # UID helpers
    # ------------------------------------------------------------------
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
        z_token = (
            self._sanitize_token(numeric_id, "0") if isinstance(numeric_id, str) else str(numeric_id)
        )
        return f"{x_token}.{y_token}#{z_token}"
