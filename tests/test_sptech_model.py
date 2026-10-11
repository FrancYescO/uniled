"""Tests for SPTech status decoding."""

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

# Avoid executing the integration package setup while importing protocol modules.
package = ModuleType("custom_components.uniled")
package.__path__ = [str(Path(__file__).parents[1] / "custom_components" / "uniled")]
sys.modules["custom_components.uniled"] = package

from custom_components.uniled.lib.channel import UniledChannel  # noqa: E402
from custom_components.uniled.lib.const import (  # noqa: E402
    ATTR_HA_COLOR_MODE,
    ATTR_HA_SUPPORTED_COLOR_MODES,
    COLOR_MODE_BRIGHTNESS,
    COLOR_MODE_RGB,
)
from custom_components.uniled.lib.net.sp53x_54xe import SP5XXE  # noqa: E402
from custom_components.uniled.lib.sptech_conf import CFG_82, CFG_86  # noqa: E402
from custom_components.uniled.lib.sptech_model import SPTechModel  # noqa: E402


def _decode_static_status(config) -> UniledChannel:
    """Decode a representative static-mode status for a light config."""
    # Chip ordering is unrelated to color-mode decoding and is implemented by
    # the transport model mixed into SPTechModel on real devices.
    config.order = None
    channel = UniledChannel(0)
    channel.context = config
    device = SimpleNamespace(name="SP630E", master=channel)
    mode = (
        SPTechModel.MODE_STATIC_COLOR
        if config.hue
        else SPTechModel.MODE_STATIC_WHITE
    )
    payload = bytearray(
        [
            0,  # Unknown
            1,  # Power
            0,  # Effect loop
            0,  # Chip order
            mode,
            1,  # Solid effect
            1,  # Effect play
            128,  # Color brightness
            96,  # White brightness
            255,
            0,
            0,  # Static RGB
            0,
            0,  # Static CCT
            1,  # Speed
            1,  # Length
            0,  # Direction
            1,  # Audio sensitivity
            0,  # Audio input
            255,
            0,
            0,  # Effect RGB
            0,
            0,  # Effect CCT
            0,  # DIY solid mode
            0,  # DIY solid slot count
        ]
    )

    SPTechModel().decode_chunk_2(device, 2, payload)
    return channel


def test_spi_rgb_static_mode_only_advertises_rgb() -> None:
    """SPI RGB must not combine RGB with HA's brightness-only color mode."""
    channel = _decode_static_status(CFG_86())

    assert channel.get(ATTR_HA_SUPPORTED_COLOR_MODES) == {COLOR_MODE_RGB}
    assert channel.get(ATTR_HA_COLOR_MODE) == COLOR_MODE_RGB


def test_spi_single_color_static_mode_advertises_brightness() -> None:
    """Brightness-only SPI strips retain their supported color mode."""
    channel = _decode_static_status(CFG_82())

    assert channel.get(ATTR_HA_SUPPORTED_COLOR_MODES) == {COLOR_MODE_BRIGHTNESS}
    assert channel.get(ATTR_HA_COLOR_MODE) == COLOR_MODE_BRIGHTNESS


def test_sp541e_network_model_signature() -> None:
    """SP541E resolves to its single-color PWM configuration."""
    proxy = SP5XXE()

    model = proxy.match_model_code(0x5C)
    named_model = proxy.match_model_name("SP541E")

    assert model is not None
    assert named_model is not None
    assert model.model_name == "SP541E"
    assert named_model.model_code == 0x5C
    assert set(model.configs) == {0x01}
    assert model.match_light_type_config(0x01) is model.configs[0x01]
    assert model.configs[0x01].name == "1 CH PWM - Single Color"


def test_sp54ae_network_model_signature() -> None:
    """SP54AE is identified by its network model code and RGBCCT configs."""
    proxy = SP5XXE()

    model = proxy.match_model_code(0x65)
    named_model = proxy.match_model_name("SP54AE")

    assert model is not None
    assert named_model is not None
    assert model.model_name == "SP54AE"
    assert named_model.model_code == 0x65
    assert set(model.configs) == {0x0B, 0x0E}
    assert all(
        config.spi and config.hue and config.cct
        for config in model.configs.values()
    )
    assert all(
        len(config.effects[model.MODE_SOUND_COLOR]) == 5
        and model.MODE_CUSTOM_GRADIENT in config.effects
        for config in model.configs.values()
    )
