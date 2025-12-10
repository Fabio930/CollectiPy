"""Logic plugin that visualizes messaging/handshake activity via the agent LEDs."""

from typing import Any

from core.configuration.plugin_registry import register_logic_model


class LedStateLogic:
    """Keep the LED attachment color aligned with messaging activity."""

    DEFAULT_COLOR = "red"
    HANDSHAKE_COLOR = "yellow"
    COMMUNICATION_COLOR = "white"
    COMMUNICATION_TICKS = 3

    def __init__(self, agent: Any):
        self.agent = agent
        self._last_comm_tick: int | None = None

    def pre_run(self, objects: dict, agents: dict) -> None:
        """Ensure the LED starts from the default shade."""
        self.agent.reset_led_color()

    def step(self, agent: Any, tick: int, arena_shape, objects: dict, agents: dict) -> None:
        """Update the LED color each tick based on the current messaging state."""
        color = self._resolve_color(tick)
        self.agent.set_led_color(color)

    def _resolve_color(self, tick: int) -> str:
        if self._is_handshake_active():
            return self.HANDSHAKE_COLOR
        if self._recent_communication(tick):
            return self.COMMUNICATION_COLOR
        return self.agent.get_default_led_color()

    def _is_handshake_active(self) -> bool:
        state = getattr(self.agent, "_handshake_state", "idle") or "idle"
        pending = getattr(self.agent, "_handshake_pending_accept", None)
        closing = getattr(self.agent, "_handshake_end_requested", False)
        # Only highlight the LED during the handshake negotiation phases.
        return state == "awaiting_accept" or bool(pending) or bool(closing)

    def _recent_communication(self, tick: int) -> bool:
        last_tx = getattr(self.agent, "_last_tx_tick", -1)
        last_rx = getattr(self.agent, "_last_rx_tick", -1)
        if last_tx == tick or last_rx == tick:
            self._last_comm_tick = tick
        if self._last_comm_tick is None:
            return False
        return tick - self._last_comm_tick < self.COMMUNICATION_TICKS


register_logic_model("led_state", lambda agent: LedStateLogic(agent))
