"""Logic plugin that visualizes messaging/handshake activity via the agent LEDs."""

from typing import Any

from core.configuration.plugin_registry import register_logic_model


class LedStateLogic:
    """Keep the LED attachment color aligned with messaging activity."""

    DEFAULT_COLOR = "red"
    HANDSHAKE_COLOR = "yellow"
    CONNECTED_COLOR = "green"
    COMMUNICATION_COLOR = "white"
    COMMUNICATION_TICKS = 3
    HANDSHAKE_DISPLAY_DURATION = 2
    HANDSHAKE_SEQUENCE = tuple("abcdef")

    def __init__(self, agent: Any):
        self.agent = agent
        self._last_comm_tick: int | None = None
        self._handshake_visible_until: int | None = None
        self._conversation_partner: str | None = None
        self._conversation_index: int = 0
        self._conversation_initiator = False
        self._conversation_complete = True
        self._last_received_letter: str | None = None
        self._processed_messages: set[int] = set()

    def pre_run(self, objects: dict, agents: dict) -> None:
        """Ensure the LED starts from the default shade."""
        self.agent.reset_led_color()
        self._reset_conversation_state()

    def step(self, agent: Any, tick: int, arena_shape, objects: dict, agents: dict) -> None:
        """Update the LED color each tick based on the current messaging state."""
        self._process_handshake_conversation()
        color = self._resolve_color(tick)
        self.agent.set_led_color(color)

    def _resolve_color(self, tick: int) -> str:
        if self._has_active_handshake():
            return self.CONNECTED_COLOR
        if self._is_handshake_active(tick):
            return self.HANDSHAKE_COLOR
        if self._recent_communication(tick):
            return self.COMMUNICATION_COLOR
        return self.agent.get_default_led_color()

    def _has_active_handshake(self) -> bool:
        partner = getattr(self.agent, "handshake_partner", None)
        state = getattr(self.agent, "_handshake_state", "")
        return bool(partner and state == "connected")

    def _is_handshake_active(self, tick: int) -> bool:
        last_activity = getattr(self.agent, "_handshake_activity_tick", -1)
        if last_activity >= 0:
            if tick - last_activity <= self.HANDSHAKE_DISPLAY_DURATION:
                return True
        return False

    def _recent_communication(self, tick: int) -> bool:
        last_tx = getattr(self.agent, "_last_tx_tick", -1)
        last_rx = getattr(self.agent, "_last_rx_tick", -1)
        if last_tx == tick or last_rx == tick:
            self._last_comm_tick = tick
        if self._last_comm_tick is None:
            return False
        return tick - self._last_comm_tick < self.COMMUNICATION_TICKS

    def _process_handshake_conversation(self):
        partner = getattr(self.agent, "handshake_partner", None)
        state = str(getattr(self.agent, "_handshake_state", "") or "").strip().lower()
        if partner is None or state != "connected":
            self._reset_conversation_state()
            return
        if partner != self._conversation_partner:
            self._initialize_conversation(partner)
        self._consume_messages_for_partner(partner)
        if self._conversation_complete:
            return
        letter = self._next_letter_to_send()
        if not letter:
            return
        self.agent.set_outgoing_message_fields({"dialogue_payload": letter})
        if letter == self.HANDSHAKE_SEQUENCE[-1]:
            self._conversation_complete = True
            setattr(self.agent, "_handshake_end_requested", True)
        self._conversation_index += 2

    def _initialize_conversation(self, partner: str):
        self._conversation_partner = partner
        self._conversation_initiator = self.agent.get_name() < partner
        self._conversation_index = 0 if self._conversation_initiator else 1
        self._conversation_complete = False
        self._last_received_letter = None
        self._processed_messages.clear()

    def _reset_conversation_state(self):
        self._conversation_partner = None
        self._conversation_complete = True
        self._last_received_letter = None
        self._processed_messages.clear()
        self._conversation_index = 0
        self._conversation_initiator = False

    def _consume_messages_for_partner(self, partner: str):
        for msg in getattr(self.agent, "messages", []):
            msg_id = id(msg)
            if msg_id in self._processed_messages:
                continue
            self._processed_messages.add(msg_id)
            sender = self._extract_message_sender(msg)
            if sender != partner:
                continue
            payload = msg.get("dialogue_payload")
            if isinstance(payload, str) and payload:
                self._last_received_letter = payload.lower()

    @staticmethod
    def _extract_message_sender(msg: dict) -> str | None:
        block = msg.get("handshake") if isinstance(msg, dict) else None
        sender = None
        if block:
            sender = block.get("owner")
        if not sender:
            sender = msg.get("source_agent") or msg.get("agent_id") or msg.get("from")
        return sender

    def _next_letter_to_send(self) -> str | None:
        idx = self._conversation_index
        if idx >= len(self.HANDSHAKE_SEQUENCE):
            return None
        if idx == 0:
            return self.HANDSHAKE_SEQUENCE[0]
        expected = self.HANDSHAKE_SEQUENCE[idx - 1]
        if self._last_received_letter == expected:
            return self.HANDSHAKE_SEQUENCE[idx]
        return None


register_logic_model("led_state", lambda agent: LedStateLogic(agent))
