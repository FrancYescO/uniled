"""Tests for host-driven BanlanX v2 audio spectrum support."""

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import voluptuous as vol

# Avoid executing the integration package setup while importing protocol modules.
package = ModuleType("custom_components.uniled")
package.__path__ = [str(Path(__file__).parents[1] / "custom_components" / "uniled")]
sys.modules["custom_components.uniled"] = package

from custom_components.uniled.const import DOMAIN  # noqa: E402
from custom_components.uniled.lib.ble.banlanx2 import (  # noqa: E402
    BANLANX2_AUDIO_SPECTRUM_BANDS,
    BANLANX2_AUDIO_SPECTRUM_COMMAND,
    SP611E,
    SP621E,
)
from custom_components.uniled.lib.channel import UniledChannel  # noqa: E402
from custom_components.uniled.lib.device import UniledDevice  # noqa: E402
from custom_components.uniled.light import (  # noqa: E402
    ATTR_UL_AUDIO_SPECTRUM,
    AUDIO_SPECTRUM_SCHEMA,
    SERVICE_SEND_AUDIO_SPECTRUM,
    async_register_services,
)


def test_audio_spectrum_command_clamps_and_pads() -> None:
    """Spectrum values are clamped to bytes and padded to sixteen bands."""
    command = SP611E.build_audio_spectrum_command(
        None,
        UniledChannel(0),
        [-1, 1, 255, 256, "3"],
    )

    assert command == bytearray(
        [
            0xA0,
            BANLANX2_AUDIO_SPECTRUM_COMMAND,
            BANLANX2_AUDIO_SPECTRUM_BANDS,
            0,
            1,
            255,
            255,
            3,
            *([0] * 11),
        ]
    )


def test_audio_spectrum_command_truncates_extra_bands() -> None:
    """Only the first sixteen frequency bands are sent."""
    command = SP611E.build_audio_spectrum_command(
        None,
        UniledChannel(0),
        list(range(20)),
    )

    assert command == bytearray([0xA0, 0x6D, 0x10, *range(16)])


def test_audio_spectrum_service_schema() -> None:
    """The entity action accepts one to sixteen byte values."""
    schema = vol.Schema(AUDIO_SPECTRUM_SCHEMA)

    assert schema({ATTR_UL_AUDIO_SPECTRUM: [0, 128, 255]}) == {
        ATTR_UL_AUDIO_SPECTRUM: [0, 128, 255]
    }

    with pytest.raises(vol.Invalid):
        schema({ATTR_UL_AUDIO_SPECTRUM: []})
    with pytest.raises(vol.Invalid):
        schema({ATTR_UL_AUDIO_SPECTRUM: list(range(17))})
    with pytest.raises(vol.Invalid):
        schema({ATTR_UL_AUDIO_SPECTRUM: [256]})


def test_audio_spectrum_action_is_registered(hass) -> None:
    """The action is available even before a config entry is loaded."""
    async_register_services(hass)

    assert hass.services.has_service(DOMAIN, SERVICE_SEND_AUDIO_SPECTRUM)


@pytest.mark.asyncio
async def test_device_sends_audio_spectrum_command() -> None:
    """The device bridge builds and sends the transient protocol command."""
    device = SimpleNamespace(
        _model=SP611E,
        supports_audio_spectrum=True,
        send=AsyncMock(return_value=True),
    )
    channel = UniledChannel(0)

    assert UniledDevice.supports_audio_spectrum.fget(device)
    assert await UniledDevice.async_send_audio_spectrum(device, channel, [10, 20, 30])
    device.send.assert_awaited_once_with(
        bytearray([0xA0, 0x6D, 0x10, 10, 20, 30, *([0] * 13)])
    )


@pytest.mark.asyncio
async def test_device_rejects_unsupported_audio_spectrum() -> None:
    """Models without a spectrum builder do not send arbitrary commands."""
    device = SimpleNamespace(
        _model=object(),
        supports_audio_spectrum=False,
        send=AsyncMock(return_value=True),
    )

    assert not UniledDevice.supports_audio_spectrum.fget(device)
    assert not await UniledDevice.async_send_audio_spectrum(
        device, UniledChannel(0), [10]
    )
    device.send.assert_not_awaited()

    non_music_device = SimpleNamespace(
        _model=SP621E,
        supports_audio_spectrum=False,
        send=AsyncMock(return_value=True),
    )
    assert not UniledDevice.supports_audio_spectrum.fget(non_music_device)
    assert not await UniledDevice.async_send_audio_spectrum(
        non_music_device, UniledChannel(0), [10]
    )
    non_music_device.send.assert_not_awaited()
