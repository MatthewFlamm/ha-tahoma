"""Parent class for every TaHoma device."""
import logging
from typing import Any, Dict, Optional

from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from pyhoma.models import Command, Device

from .const import DOMAIN
from .coordinator import TahomaDataUpdateCoordinator

ATTR_RSSI_LEVEL = "rssi_level"

CORE_AVAILABILITY_STATE = "core:AvailabilityState"
CORE_BATTERY_STATE = "core:BatteryState"
CORE_MANUFACTURER_NAME_STATE = "core:ManufacturerNameState"
CORE_MODEL_STATE = "core:ModelState"
CORE_RSSI_LEVEL_STATE = "core:RSSILevelState"
CORE_SENSOR_DEFECT_STATE = "core:SensorDefectState"
CORE_STATUS_STATE = "core:StatusState"

STATE_AVAILABLE = "available"
STATE_BATTERY_FULL = "full"
STATE_BATTERY_NORMAL = "normal"
STATE_BATTERY_LOW = "low"
STATE_BATTERY_VERY_LOW = "verylow"
STATE_DEAD = "dead"

_LOGGER = logging.getLogger(__name__)


class TahomaDevice(CoordinatorEntity, Entity):
    """Representation of a TaHoma device entity."""

    def __init__(self, device_url: str, coordinator: TahomaDataUpdateCoordinator):
        """Initialize the device."""
        super().__init__(coordinator)
        self.device_url = device_url

    @property
    def device(self) -> Device:
        """Return TaHoma device linked to this entity."""
        return self.coordinator.data[self.device_url]

    @property
    def name(self) -> str:
        """Return the name of the device."""
        return self.device.label

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.device.available

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self.device.deviceurl

    @property
    def assumed_state(self) -> bool:
        """Return True if unable to access real state of the entity."""
        return self.device.states is None or len(self.device.states) == 0

    @property
    def device_state_attributes(self) -> Dict[str, Any]:
        """Return the state attributes of the device."""
        attr = {
            "ui_class": self.device.ui_class,
            "widget": self.device.widget,
            "controllable_name": self.device.controllable_name,
        }

        if self.has_state(CORE_RSSI_LEVEL_STATE):
            attr[ATTR_RSSI_LEVEL] = self.select_state(CORE_RSSI_LEVEL_STATE)

        if self.device.attributes:
            for attribute in self.device.attributes:
                attr[attribute.name] = attribute.value

        if self.device.states:
            for state in self.device.states:
                if "State" in state.name:
                    attr[state.name] = state.value

        return attr

    @property
    def device_info(self) -> Dict[str, Any]:
        """Return device registry information for this entity."""
        manufacturer = self.select_state(CORE_MANUFACTURER_NAME_STATE) or "Somfy"
        model = self.select_state(CORE_MODEL_STATE) or self.device.widget

        name = self.name
        device_url = self.device_url
        # Some devices, such as the Smart Thermostat have several devices in one physical device,
        # with same device URL, terminated by '#' and a number.
        # We use the base url as a device unique id.
        if "#" in self.device_url:
            device_url, _ = self.device.deviceurl.split("#")
            entity_registry = self.hass.data["entity_registry"]
            name = next(
                (
                    entry.original_name
                    for entity_id, entry in entity_registry.entities.items()
                    if entry.unique_id == f"{device_url}#1"
                ),
                None,
            )

        return {
            "identifiers": {(DOMAIN, device_url)},
            "manufacturer": manufacturer,
            "name": name,
            "model": model,
            "sw_version": self.device.controllable_name,
        }

    def select_command(self, *commands: str) -> Optional[str]:
        """Select first existing command in a list of commands."""
        existing_commands = self.device.definition.commands
        return next((c for c in commands if c in existing_commands), None)

    def has_command(self, *commands: str) -> bool:
        """Return True if a command exists in a list of commands."""
        return self.select_command(*commands) is not None

    def select_state(self, *states) -> Optional[str]:
        """Select first existing active state in a list of states."""
        if self.device.states:
            return next(
                (
                    state.value
                    for state in self.device.states
                    if state.name in list(states)
                ),
                None,
            )
        return None

    def has_state(self, *states: str) -> bool:
        """Return True if a state exists in self."""
        return self.select_state(*states) is not None

    async def async_execute_command(self, command_name: str, *args: Any):
        """Execute device command in async context."""
        try:
            exec_id = await self.coordinator.client.execute_command(
                self.device.deviceurl,
                Command(command_name, list(args)),
                "Home Assistant",
            )
        except Exception as exception:  # pylint: disable=broad-except
            _LOGGER.error(exception)
            return

        # ExecutionRegisteredEvent doesn't contain the deviceurl, thus we need to register it here
        self.coordinator.executions[exec_id] = {
            "deviceurl": self.device.deviceurl,
            "command_name": command_name,
        }

        await self.coordinator.async_refresh()

    async def async_cancel_command(self, exec_id: str):
        """Cancel device command in async context."""
        await self.coordinator.client.cancel_command(exec_id)
