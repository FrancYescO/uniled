"""UniLED BLE Devices - SP LED (BanlanX SP661E single colour / SP662E CCT PWM)

Protocol notes: see docs/SP661E_PROTOCOL.md. Frames are
`53 CMD 00 01 00 LEN DATA` on FFE1; most control payloads start with channel `01`
(CCT commands `0x60`/`0x61` carry `[cold, warm]` directly).
"""

from __future__ import annotations
from typing import Final

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from ..const import *  # I know!
from ..channel import UniledChannel
from ..features import (
    LightStripFeature,
    EffectTypeFeature,
    EffectSpeedFeature,
    OnOffSpeedFeature,
    OnPowerFeature,
)
from ..effects import (
    UNILED_EFFECT_TYPE_DYNAMIC,
    UNILED_EFFECT_TYPE_STATIC,
)
from .device import (
    UUID_BASE_FORMAT as BANLANX_UUID_FORMAT,
    BANLANX_MANUFACTURER,
    BANLANX_MANUFACTURER_ID,
    ParseNotificationError,
    UniledBleDevice,
    UniledBleModel,
)

import logging

_LOGGER = logging.getLogger(__name__)

BANLANX661_HEADER: Final = 0x53
BANLANX661_HEADER_LENGTH: Final = 6
BANLANX661_MSG_STATUS: Final = 0x02

# Command codes
BANLANX661_CMD_QUERY: Final = 0x02
BANLANX661_CMD_ONOFF_OPTIONS: Final = 0x08
BANLANX661_CMD_ON_POWER: Final = 0x0B
BANLANX661_CMD_MODE: Final = 0x53
BANLANX661_CMD_POWER: Final = 0x50
BANLANX661_CMD_LEVEL: Final = 0x51
BANLANX661_CMD_SPEED: Final = 0x54
BANLANX661_CMD_CCT_FX: Final = 0x60
BANLANX661_CMD_CCT_STATIC: Final = 0x61

# Offsets in the status notification (header included)
BANLANX661_OFS_ON_POWER: Final = 22
BANLANX661_OFS_ONOFF_EFFECT: Final = 23
BANLANX661_OFS_ONOFF_SPEED: Final = 24
BANLANX661_OFS_LIGHT_TYPE: Final = 42
BANLANX661_OFS_POWER: Final = 44
BANLANX661_OFS_MODE: Final = 47
BANLANX661_OFS_EFFECT: Final = 48
BANLANX661_OFS_LEVEL_FX: Final = 50
BANLANX661_OFS_LEVEL_SOLID: Final = 51
BANLANX661_OFS_CCT_COLD_SOLID: Final = 55
BANLANX661_OFS_CCT_WARM_SOLID: Final = 56
BANLANX661_OFS_SPEED: Final = 57
BANLANX661_OFS_CCT_COLD_FX: Final = 65
BANLANX661_OFS_CCT_WARM_FX: Final = 66
BANLANX661_MIN_STATUS_LENGTH: Final = 58

BANLANX661_LIGHT_TYPE_MONO: Final = 0x01
BANLANX661_LIGHT_TYPE_CCT: Final = 0x03

BANLANX661_MODE_SOLID: Final = 0x02
BANLANX661_MODE_DYNAMIC: Final = 0x04

BANLANX661_MAX_EFFECT_SPEED: Final = 10

# Effect id = (mode << 4) | effect number
BANLANX661_EFFECTS: Final = {
    0x21: "Solid Color",
    0x41: "Triangle",
    0x42: "Strobe",
    0x43: "Heart Beat",
}

BANLANX661_ON_POWER_STATES: Final = {
    0x00: "Light Off",
    0x01: "Light On",
    0x02: "Last state",
}

BANLANX661_ONOFF_SPEEDS: Final = {
    0x01: "Slow",
    0x02: "Medium",
    0x03: "Fast",
}


def _encode(cmd: int, data: list[int] | bytes) -> bytearray:
    """Encode a BanlanX SP661E message."""
    return bytearray(
        [BANLANX661_HEADER, cmd & 0xFF, 0x00, 0x01, 0x00, len(data) & 0xFF]
    ) + bytearray(data)


class BanlanX661(UniledBleModel):
    """BanlanX SP661E/SP662E protocol implementation."""

    # Advertised name is unreliable ("LMB", truncated), name after the model
    use_model_name: bool = True
    # The controller ignores state queries written with response
    write_with_response: bool = False

    def __init__(self, id: int, name: str, info: str, data: bytes):
        super().__init__(
            model_code=id,
            model_name=name,
            model_info=info,
            manufacturer=BANLANX_MANUFACTURER,
            channels=1,
            ble_manufacturer_id=BANLANX_MANUFACTURER_ID,
            ble_manufacturer_data=data,
            ble_service_uuids=[BANLANX_UUID_FORMAT.format(part) for part in ["ffe0"]],
            ble_write_uuids=[BANLANX_UUID_FORMAT.format(part) for part in ["ffe1"]],
            ble_read_uuids=[],
            ble_notify_uuids=[],
        )

    def match_ble_device(
        self, device: BLEDevice, advertisement: AdvertisementData | None = None
    ) -> UniledBleModel | bool:
        """Identify SP662E by its model byte and keep SP661E matching ambiguous."""
        if not super().match_ble_device(device, advertisement):
            return False
        return self if self.model_name == "SP662E" else True

    def parse_notifications(
        self,
        device: UniledBleDevice,
        sender: int,
        data: bytearray,
    ) -> bool:
        """Parse notification message(s)"""
        if len(data) < BANLANX661_HEADER_LENGTH:
            raise ParseNotificationError("Packet is undersized")
        if data[0] != BANLANX661_HEADER:
            raise ParseNotificationError("Packet is invalid")
        if len(data) != data[5] + BANLANX661_HEADER_LENGTH:
            raise ParseNotificationError(
                f"Packet payload size mismatch: {len(data)} vs {data[5] + 6}"
            )
        if data[1] != BANLANX661_MSG_STATUS:
            _LOGGER.debug("%s: Ignoring non-status packet %s", device.name, data.hex())
            return False
        if len(data) < BANLANX661_MIN_STATUS_LENGTH:
            raise ParseNotificationError("Status packet too short")

        _LOGGER.debug("%s: Good Status Message: %s", device.name, data.hex())

        if not device.master.features:
            device.master.features = [
                LightStripFeature(extra=UNILED_CONTROL_ATTRIBUTES),
                EffectTypeFeature(),
                EffectSpeedFeature(BANLANX661_MAX_EFFECT_SPEED),
                OnOffSpeedFeature(),
                OnPowerFeature(),
            ]

        on_power = self.str_if_key_in(
            data[BANLANX661_OFS_ON_POWER], BANLANX661_ON_POWER_STATES, UNILED_UNKNOWN
        )
        onoff_effect = data[BANLANX661_OFS_ONOFF_EFFECT]
        onoff_speed = self.str_if_key_in(
            data[BANLANX661_OFS_ONOFF_SPEED], BANLANX661_ONOFF_SPEEDS, UNILED_UNKNOWN
        )
        light_type = data[BANLANX661_OFS_LIGHT_TYPE]
        is_cct = light_type == BANLANX661_LIGHT_TYPE_CCT
        mode = data[BANLANX661_OFS_MODE]
        effect = data[BANLANX661_OFS_EFFECT]
        speed = data[BANLANX661_OFS_SPEED]
        fx_id = (mode << 4) | (effect & 0x0F)
        is_solid = mode == BANLANX661_MODE_SOLID
        # Solid mode brightness lives in [51], effect brightness in [50]
        level = data[
            BANLANX661_OFS_LEVEL_SOLID if is_solid else BANLANX661_OFS_LEVEL_FX
        ]

        color_mode = COLOR_MODE_COLOR_TEMP if is_cct else COLOR_MODE_BRIGHTNESS
        status: dict[str, object] = {
            ATTR_UL_DEVICE_FORCE_REFRESH: True,
            ATTR_UL_POWER: data[BANLANX661_OFS_POWER] == 1,
            ATTR_UL_ON_POWER: on_power,
            ATTR_UL_ONOFF_EFFECT: onoff_effect,
            ATTR_UL_ONOFF_SPEED: onoff_speed,
            ATTR_UL_LIGHT_TYPE_NUMBER: light_type,
            ATTR_HA_SUPPORTED_COLOR_MODES: {color_mode},
            ATTR_HA_COLOR_MODE: color_mode,
            ATTR_HA_BRIGHTNESS: level,
            ATTR_UL_LIGHT_MODE_NUMBER: mode,
            ATTR_UL_EFFECT_NUMBER: fx_id,
            ATTR_HA_EFFECT: self.str_if_key_in(
                fx_id, BANLANX661_EFFECTS, UNILED_UNKNOWN
            ),
            ATTR_UL_EFFECT_TYPE: (
                UNILED_EFFECT_TYPE_STATIC if is_solid else UNILED_EFFECT_TYPE_DYNAMIC
            ),
        }
        if is_cct:
            if not is_solid and len(data) > BANLANX661_OFS_CCT_WARM_FX:
                cold = data[BANLANX661_OFS_CCT_COLD_FX]
                warm = data[BANLANX661_OFS_CCT_WARM_FX]
            else:
                cold = data[BANLANX661_OFS_CCT_COLD_SOLID]
                warm = data[BANLANX661_OFS_CCT_WARM_SOLID]
            status[ATTR_UL_CCT_COLOR] = (cold, warm, level, None)

        device.master.status.replace(status)
        if not is_solid:
            device.master.set(ATTR_UL_EFFECT_SPEED, speed)
        return True

    def build_on_connect(self, device: UniledBleDevice) -> list[bytearray] | None:
        """Build on connect message(s)"""
        return None

    def build_state_query(self, device: UniledBleDevice) -> bytearray:
        """Build a state query message"""
        return _encode(BANLANX661_CMD_QUERY, [0x01])

    def build_onoff_command(
        self, device: UniledBleDevice, channel: UniledChannel, state: bool
    ) -> bytearray:
        """Build power on/off state message(s)"""
        return _encode(BANLANX661_CMD_POWER, [0x01, 0x01 if state else 0x00])

    def build_brightness_command(
        self, device: UniledBleDevice, channel: UniledChannel, level: int
    ) -> bytearray:
        """The bytes to send for a brightness level change"""
        solid = channel.status.light_mode_number in (None, BANLANX661_MODE_SOLID)
        which = 0x80 if solid else 0x00
        return _encode(BANLANX661_CMD_LEVEL, [0x01, which, int(level) & 0xFF])

    def build_cct_color_command(
        self,
        device: UniledBleDevice,
        channel: UniledChannel,
        cct: tuple[int, int, int, int | None],
    ) -> bytearray:
        """The bytes to send for a color temperature change."""
        cold, warm, _level, _kelvin = cct
        total = cold + warm
        if total > 0:
            cold_norm = round(cold * 255 / total)
            warm_norm = 255 - cold_norm
        else:
            cold_norm, warm_norm = 0x7F, 0x80
        solid = channel.status.light_mode_number in (None, BANLANX661_MODE_SOLID)
        cmd = BANLANX661_CMD_CCT_STATIC if solid else BANLANX661_CMD_CCT_FX
        return _encode(cmd, [cold_norm & 0xFF, warm_norm & 0xFF])

    def build_effect_command(
        self, device: UniledBleDevice, channel: UniledChannel, value: str | int
    ) -> bytearray | None:
        """The bytes to send for an effect change"""
        if isinstance(value, str):
            fx_id = self.int_if_str_in(value, BANLANX661_EFFECTS, None)
        else:
            fx_id = int(value)
        if fx_id is None or fx_id not in BANLANX661_EFFECTS:
            return None
        return _encode(BANLANX661_CMD_MODE, [0x01, fx_id >> 4, fx_id & 0x0F])

    def fetch_effect_list(
        self, device: UniledBleDevice, channel: UniledChannel
    ) -> list | None:
        """Return list of effect names"""
        return list(BANLANX661_EFFECTS.values())

    def build_effect_speed_command(
        self, device: UniledBleDevice, channel: UniledChannel, value: int
    ) -> bytearray | None:
        """The bytes to send for an effect speed change."""
        speed = int(value)
        if not 0 <= speed <= BANLANX661_MAX_EFFECT_SPEED:
            return None
        return _encode(BANLANX661_CMD_SPEED, [0x01, speed])

    def build_on_power_command(
        self, device: UniledBleDevice, channel: UniledChannel, value: str | int
    ) -> bytearray | None:
        """Build power-on restore state command."""
        if isinstance(value, str):
            mode = self.int_if_str_in(value, BANLANX661_ON_POWER_STATES, None)
        else:
            mode = int(value)
        if mode is None or mode not in BANLANX661_ON_POWER_STATES:
            return None
        return _encode(BANLANX661_CMD_ON_POWER, [mode])

    def fetch_on_power_list(
        self, device: UniledBleDevice, channel: UniledChannel
    ) -> list[str]:
        """Return list of power-on restore states."""
        return list(BANLANX661_ON_POWER_STATES.values())

    def build_onoff_speed_command(
        self, device: UniledBleDevice, channel: UniledChannel, value: str | int
    ) -> bytearray | None:
        """Build on/off transition speed command."""
        if isinstance(value, str):
            speed = self.int_if_str_in(value, BANLANX661_ONOFF_SPEEDS, None)
        else:
            speed = int(value)
        if speed is None or speed not in BANLANX661_ONOFF_SPEEDS:
            return None
        effect = (
            channel.status.onoff_effect
            if channel is not None and channel.status.onoff_effect is not None
            else 0x03
        )
        return _encode(
            BANLANX661_CMD_ONOFF_OPTIONS, [0x00, int(effect) & 0xFF, speed, 0x00, 0x01]
        )

    def fetch_onoff_speed_list(
        self, device: UniledBleDevice, channel: UniledChannel
    ) -> list[str]:
        """Return list of on/off transition speeds."""
        return list(BANLANX661_ONOFF_SPEEDS.values())


##
## Device Signatures
##
# Manufacturer data starts with 01 00 (SP601E only checks the first byte)
SP661E = BanlanX661(
    id=0x661E,
    name="SP661E",
    info="Single Color PWM (Music) Controller",
    data=b"\x01\x00",
)

SP662E = BanlanX661(
    id=0x662E,
    name="SP662E",
    info="CCT PWM (Music) Controller",
    data=b"\x01\x00\x7b",
)
