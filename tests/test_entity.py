"""Tests for UniLED entity discovery."""

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

from homeassistant.const import Platform

# Import the entity module without executing the integration's package setup,
# which imports hardware-specific Bluetooth dependencies not needed here.
package = ModuleType("custom_components.uniled")
package.__path__ = [
    str(Path(__file__).parents[1] / "custom_components" / "uniled")
]
sys.modules["custom_components.uniled"] = package

from custom_components.uniled.entity import async_uniled_entity_update  # noqa: E402
from custom_components.uniled.lib.attributes import UniledAttribute  # noqa: E402
from custom_components.uniled.lib.channel import UniledChannel  # noqa: E402


def test_entities_are_added_after_device_recovers() -> None:
    """Entities discovered after an unavailable setup are added once."""
    channel = UniledChannel(0)
    coordinator = SimpleNamespace(
        device=SimpleNamespace(channel_list=[channel]),
    )
    async_add_entities = Mock()
    entity = object()

    def async_add_entity(_coordinator, _channel, feature):
        return entity if feature is not None else None

    current_ids = set()

    async_uniled_entity_update(
        coordinator,
        async_add_entities,
        async_add_entity,
        Platform.LIGHT,
        current_ids,
    )
    async_add_entities.assert_not_called()

    channel.features = [
        UniledAttribute(
            platform=Platform.LIGHT,
            attr="power",
            name="Light",
            icon=None,
            key="strip",
        )
    ]
    async_uniled_entity_update(
        coordinator,
        async_add_entities,
        async_add_entity,
        Platform.LIGHT,
        current_ids,
    )
    async_add_entities.assert_called_once_with([entity])

    async_uniled_entity_update(
        coordinator,
        async_add_entities,
        async_add_entity,
        Platform.LIGHT,
        current_ids,
    )
    async_add_entities.assert_called_once()

    channel.features.append(
        UniledAttribute(
            platform=Platform.LIGHT,
            attr="effect",
            name="Effect",
            icon=None,
            key="effect",
        )
    )
    async_uniled_entity_update(
        coordinator,
        async_add_entities,
        async_add_entity,
        Platform.LIGHT,
        current_ids,
    )
    assert async_add_entities.call_count == 2
    async_add_entities.assert_called_with([entity])
