"""Setting up a space from the UI.

A placeholder until the setup flow is built: it lets Home Assistant load
config entries made in tests, and aborts if started from the UI.
"""

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class SpotHeatingConfigFlow(ConfigFlow, domain=DOMAIN):
    """The setup flow; not built yet."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Not available yet."""
        del user_input
        return self.async_abort(reason="not_implemented")
