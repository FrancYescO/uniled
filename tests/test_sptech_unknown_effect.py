"""Light discovery with unrecognized SPTech firmware effects (issue #19)."""

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

package = ModuleType("custom_components.uniled")
package.__path__ = [str(Path(__file__).parents[1] / "custom_components" / "uniled")]
sys.modules["custom_components.uniled"] = package

from custom_components.uniled.lib.ble.sp63x_64xe import SP6XXE  # noqa: E402
from custom_components.uniled.lib.channel import UniledChannel  # noqa: E402
from custom_components.uniled.lib.const import (  # noqa: E402
    ATTR_HA_BRIGHTNESS,
    ATTR_HA_COLOR_MODE,
    ATTR_HA_SUPPORTED_COLOR_MODES,
    ATTR_UL_CCT_COLOR,
    ATTR_UL_EFFECT,
    ATTR_UL_EFFECT_NUMBER,
    ATTR_UL_LIGHT_MODE_NUMBER,
    ATTR_UL_POWER,
    COLOR_MODE_COLOR_TEMP,
    UNILED_UNKNOWN,
)


def _status_packet():
    """The complete notification attached to issue #19, without log metadata."""
    return bytearray.fromhex(
        (Path(__file__).parent / "fixtures" / "sp637e_v4_0_27.hex").read_text()
    )


def test_sp637e_static_white_from_issue_19(caplog) -> None:
    """Firmware V4.0.27's static effect 7 must expose CCT light controls."""
    model = SP6XXE().match_model_name("SP637E")
    channel = UniledChannel(0)
    device = SimpleNamespace(name="SP637E", master=channel)

    assert model.parse_notifications(device, 0, _status_packet()) is True
    assert "Exception decoding" not in caplog.text
    assert channel.get(ATTR_UL_LIGHT_MODE_NUMBER) == model.MODE_STATIC_WHITE
    assert channel.get(ATTR_UL_EFFECT_NUMBER) == 7
    assert channel.get(ATTR_UL_EFFECT) == UNILED_UNKNOWN
    assert channel.get(ATTR_UL_POWER) is False
    assert channel.get(ATTR_HA_BRIGHTNESS) == 247
    assert channel.get(ATTR_UL_CCT_COLOR) == (20, 235, 247, None)
    assert channel.get(ATTR_HA_SUPPORTED_COLOR_MODES) == {COLOR_MODE_COLOR_TEMP}
    assert channel.get(ATTR_HA_COLOR_MODE) == COLOR_MODE_COLOR_TEMP
    assert any(feature.platform == "light" for feature in channel.features)


@pytest.mark.parametrize("mode", [2, 4, 6, 0xFF])
def test_unknown_effect_keeps_light_controls(mode, caplog) -> None:
    """Unrecognized effects or modes must not remove the light entity."""
    model = SP6XXE().match_model_name("SP637E")
    channel = UniledChannel(0)
    device = SimpleNamespace(name="SP637E", master=channel)
    packet = _status_packet()
    # Header (6), length format (1), settings chunk (19), status tag/size (2).
    status_start = 28
    packet[status_start + 4] = mode
    packet[status_start + 5] = 0xFF

    assert model.parse_notifications(device, 0, packet) is True
    assert "Exception decoding" not in caplog.text
    assert channel.get(ATTR_UL_EFFECT_NUMBER) == 0xFF
    assert channel.get(ATTR_UL_EFFECT) == UNILED_UNKNOWN
    assert any(feature.platform == "light" for feature in channel.features)


def test_switching_between_known_and_unknown_effects(caplog) -> None:
    """Refreshing an unfamiliar effect must not lose an existing light."""
    model = SP6XXE().match_model_name("SP637E")
    channel = UniledChannel(0)
    device = SimpleNamespace(name="SP637E", master=channel)

    for effect in (1, 7, 1):
        packet = _status_packet()
        packet[33] = effect
        assert model.parse_notifications(device, 0, packet) is True
        assert channel.get(ATTR_UL_EFFECT_NUMBER) == effect
        assert (channel.get(ATTR_UL_EFFECT) == UNILED_UNKNOWN) == (effect == 7)
        assert channel.get(ATTR_HA_BRIGHTNESS) == 247
        assert channel.get(ATTR_HA_COLOR_MODE) == COLOR_MODE_COLOR_TEMP
        assert sum(feature.platform == "light" for feature in channel.features) == 1

    assert "Exception decoding" not in caplog.text
