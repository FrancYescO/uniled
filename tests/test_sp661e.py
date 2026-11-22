"""Offline tests for the SP661E model (no Home Assistant, no Bluetooth).
Run from the repo root:  python -m pytest tests/test_sp661e.py -v
"""

from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch
import sys
import unittest

package = ModuleType("custom_components.uniled")
package.__path__ = [str(Path(__file__).parents[1] / "custom_components" / "uniled")]
sys.modules["custom_components.uniled"] = package

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from custom_components.uniled.lib.const import *  # noqa
from custom_components.uniled.lib.ble.banlanx_661 import SP661E, SP662E
from custom_components.uniled.lib.ble.device import (
    UniledBleDevice,
    ParseNotificationError,
)
from custom_components.uniled.lib.ble.sp601e import SP601E
from custom_components.uniled.lib.effects import UNILED_EFFECT_TYPE_STATIC

# Real status notification from the controller (solid mode, 100%, power on)
STATUS = bytes.fromhex(
    "53 02 00 01 00 62 01 0a 00 1c 01 00 06 56 31 2e 30 2e 30 32 63 09 01 03 03 00 00 07 80 00 20 01"
    " 60 10 07 a1 00 00 03 00 2a 01 01 00 01 00 78 02 01 00 ff ff ff 00 00 ff 00 03 00 00 10 00 ff 00"
    " 00 ff 00 01 03 01 ff 00 00 01 00 ff 00 01 00 00 ff 01 00 0c 00 0c 01 0a 00 00 00 00 00 00 00 00"
    " ff 00 0d 00 03 01 00 00"
)

# Real status notification from an SP662E CCT controller (solid mode, 100%, mid-warmth 7f/80)
STATUS_SP662E = bytes.fromhex(
    "53 02 00 01 00 62 01 0a 00 1c 01 00 06 56 31 2e 30 2e 30 32 72 09 01 03 03 00 00 07 80 00 00 00"
    " 00 00 00 00 00 00 03 00 2a 01 03 00 01 00 78 02 01 00 ff ff ff 00 00 7f 80 0a 00 00 10 00 ff 00"
    " 00 7f 80 01 03 01 ff 00 00 01 00 ff 00 01 00 00 ff 01 00 0c 00 0c 01 0a 00 00 00 00 00 00 00 00"
    " ff 00 0d 00 03 01 00 00"
)


class FakeStatus(dict):
    def replace(self, d):
        self.clear()
        self.update(d)


class FakeMaster:
    def __init__(self):
        self.features = []
        self.status = FakeStatus()

    def set(self, k, v):
        self.status[k] = v


class FakeDevice:
    name = "LMB"

    def __init__(self):
        self.master = FakeMaster()


class FakeStatusView:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeChannel:
    def __init__(self, mode, onoff_effect=0x03):
        self.status = FakeStatusView(light_mode_number=mode, onoff_effect=onoff_effect)


def with_bytes(base: bytes, **offs):
    b = bytearray(base)
    for k, v in offs.items():
        b[int(k[1:])] = v
    return bytes(b)


class ParseTests(unittest.TestCase):
    def test_packet_length_is_consistent(self):
        self.assertEqual(len(STATUS), STATUS[5] + 6)

    def test_parse_solid_full(self):
        dev = FakeDevice()
        self.assertTrue(SP661E.parse_notifications(dev, 0, bytearray(STATUS)))
        st = dev.master.status
        self.assertTrue(st[ATTR_UL_POWER])
        self.assertEqual(st[ATTR_HA_COLOR_MODE], COLOR_MODE_BRIGHTNESS)
        self.assertEqual(st[ATTR_HA_SUPPORTED_COLOR_MODES], {COLOR_MODE_BRIGHTNESS})
        self.assertNotIn(ATTR_UL_CCT_COLOR, st)
        self.assertEqual(st[ATTR_HA_BRIGHTNESS], 0xFF)
        self.assertEqual(st[ATTR_UL_LIGHT_MODE_NUMBER], 2)
        self.assertEqual(st[ATTR_HA_EFFECT], "Solid Color")
        self.assertEqual(st[ATTR_UL_EFFECT_TYPE], UNILED_EFFECT_TYPE_STATIC)
        self.assertEqual(st[ATTR_UL_ON_POWER], "Light On")
        self.assertEqual(st[ATTR_UL_ONOFF_SPEED], "Fast")
        self.assertEqual(len(dev.master.features), 5)

    def test_parse_on_power_and_onoff_speed(self):
        dev = FakeDevice()
        pkt = with_bytes(STATUS_SP662E, o22=2, o24=1)
        self.assertTrue(SP662E.parse_notifications(dev, 0, bytearray(pkt)))
        st = dev.master.status
        self.assertEqual(st[ATTR_UL_ON_POWER], "Last state")
        self.assertEqual(st[ATTR_UL_ONOFF_SPEED], "Slow")

    def test_parse_cct_solid(self):
        dev = FakeDevice()
        self.assertTrue(SP662E.parse_notifications(dev, 0, bytearray(STATUS_SP662E)))
        st = dev.master.status
        self.assertTrue(st[ATTR_UL_POWER])
        self.assertEqual(st[ATTR_HA_COLOR_MODE], COLOR_MODE_COLOR_TEMP)
        self.assertEqual(st[ATTR_HA_SUPPORTED_COLOR_MODES], {COLOR_MODE_COLOR_TEMP})
        self.assertEqual(st[ATTR_UL_CCT_COLOR], (0x7F, 0x80, 0xFF, None))
        self.assertEqual(st[ATTR_HA_BRIGHTNESS], 0xFF)
        self.assertEqual(st[ATTR_UL_LIGHT_TYPE_NUMBER], 0x03)

    def test_parse_cct_dynamic_uses_fx_cct_bytes(self):
        dev = FakeDevice()
        pkt = with_bytes(STATUS_SP662E, o47=4, o48=1, o50=0x60, o65=0x20, o66=0xDF)
        self.assertTrue(SP662E.parse_notifications(dev, 0, bytearray(pkt)))
        st = dev.master.status
        self.assertEqual(st[ATTR_HA_COLOR_MODE], COLOR_MODE_COLOR_TEMP)
        self.assertEqual(st[ATTR_UL_CCT_COLOR], (0x20, 0xDF, 0x60, None))
        self.assertEqual(st[ATTR_HA_BRIGHTNESS], 0x60)

    def test_parse_power_off_and_brightness(self):
        dev = FakeDevice()
        pkt = with_bytes(STATUS, o44=0, o51=0x33)
        SP661E.parse_notifications(dev, 0, bytearray(pkt))
        self.assertFalse(dev.master.status[ATTR_UL_POWER])
        self.assertEqual(dev.master.status[ATTR_HA_BRIGHTNESS], 0x33)

    def test_parse_dynamic_uses_fx_level_and_speed(self):
        dev = FakeDevice()
        pkt = with_bytes(STATUS, o47=4, o48=2, o50=0x80, o51=0x1A, o57=8)
        SP661E.parse_notifications(dev, 0, bytearray(pkt))
        st = dev.master.status
        self.assertEqual(st[ATTR_HA_EFFECT], "Strobe")
        self.assertEqual(st[ATTR_HA_BRIGHTNESS], 0x80)
        self.assertEqual(st[ATTR_UL_EFFECT_SPEED], 8)

    def test_rejects_bad_packets(self):
        dev = FakeDevice()
        with self.assertRaises(ParseNotificationError):
            SP661E.parse_notifications(dev, 0, bytearray(STATUS[:-1]))
        with self.assertRaises(ParseNotificationError):
            SP661E.parse_notifications(dev, 0, bytearray(b"\x00" + STATUS[1:]))


class CommandTests(unittest.TestCase):
    def test_query(self):
        self.assertEqual(
            SP661E.build_state_query(None).hex(" "), "53 02 00 01 00 01 01"
        )

    def test_power(self):
        self.assertEqual(
            SP661E.build_onoff_command(None, None, True).hex(" "),
            "53 50 00 01 00 02 01 01",
        )
        self.assertEqual(
            SP661E.build_onoff_command(None, None, False).hex(" "),
            "53 50 00 01 00 02 01 00",
        )

    def test_brightness_solid_and_fx(self):
        self.assertEqual(
            SP661E.build_brightness_command(None, FakeChannel(2), 255).hex(" "),
            "53 51 00 01 00 03 01 80 ff",
        )
        self.assertEqual(
            SP661E.build_brightness_command(None, FakeChannel(4), 0x40).hex(" "),
            "53 51 00 01 00 03 01 00 40",
        )

    def test_cct_static_and_fx(self):
        # Full warm / full cold / mid-warmth in solid mode
        self.assertEqual(
            SP662E.build_cct_color_command(
                None, FakeChannel(2), (0, 255, 255, 2000)
            ).hex(" "),
            "53 61 00 01 00 02 00 ff",
        )
        self.assertEqual(
            SP662E.build_cct_color_command(
                None, FakeChannel(2), (255, 0, 255, 6500)
            ).hex(" "),
            "53 61 00 01 00 02 ff 00",
        )
        # Dimmed HA rgbww values must normalize so cold + warm == 255
        self.assertEqual(
            SP662E.build_cct_color_command(
                None, FakeChannel(2), (0, 128, 128, 2000)
            ).hex(" "),
            "53 61 00 01 00 02 00 ff",
        )
        self.assertEqual(
            SP662E.build_cct_color_command(
                None, FakeChannel(2), (64, 64, 128, 4250)
            ).hex(" "),
            "53 61 00 01 00 02 80 7f",
        )
        # Dynamic mode uses EFFECT_CCT (0x60)
        self.assertEqual(
            SP662E.build_cct_color_command(
                None, FakeChannel(4), (65, 190, 255, 3100)
            ).hex(" "),
            "53 60 00 01 00 02 41 be",
        )

    def test_effects(self):
        exp = {
            "Solid Color": "53 53 00 01 00 03 01 02 01",
            "Triangle": "53 53 00 01 00 03 01 04 01",
            "Strobe": "53 53 00 01 00 03 01 04 02",
            "Heart Beat": "53 53 00 01 00 03 01 04 03",
        }
        for name, frame in exp.items():
            self.assertEqual(
                SP661E.build_effect_command(None, None, name).hex(" "), frame
            )
        self.assertIsNone(SP661E.build_effect_command(None, None, "Nope"))

    def test_speed(self):
        self.assertEqual(
            SP661E.build_effect_speed_command(None, None, 8).hex(" "),
            "53 54 00 01 00 02 01 08",
        )
        for invalid in (-1, 11, 128, 256, 266):
            self.assertIsNone(SP661E.build_effect_speed_command(None, None, invalid))

    def test_on_power(self):
        self.assertEqual(
            SP662E.fetch_on_power_list(None, None),
            ["Light Off", "Light On", "Last state"],
        )
        self.assertEqual(
            SP662E.build_on_power_command(None, None, "Light Off").hex(" "),
            "53 0b 00 01 00 01 00",
        )
        self.assertEqual(
            SP662E.build_on_power_command(None, None, "Light On").hex(" "),
            "53 0b 00 01 00 01 01",
        )
        self.assertEqual(
            SP662E.build_on_power_command(None, None, "Last state").hex(" "),
            "53 0b 00 01 00 01 02",
        )
        self.assertIsNone(SP662E.build_on_power_command(None, None, "Invalid"))
        self.assertIsNone(SP662E.build_on_power_command(None, None, 99))

    def test_onoff_speed(self):
        self.assertEqual(
            SP662E.fetch_onoff_speed_list(None, None),
            ["Slow", "Medium", "Fast"],
        )
        self.assertEqual(
            SP662E.build_onoff_speed_command(None, FakeChannel(2), "Slow").hex(" "),
            "53 08 00 01 00 05 00 03 01 00 01",
        )
        self.assertEqual(
            SP662E.build_onoff_speed_command(None, FakeChannel(2), "Medium").hex(" "),
            "53 08 00 01 00 05 00 03 02 00 01",
        )
        self.assertEqual(
            SP662E.build_onoff_speed_command(None, FakeChannel(2), "Fast").hex(" "),
            "53 08 00 01 00 05 00 03 03 00 01",
        )
        self.assertIsNone(
            SP662E.build_onoff_speed_command(None, FakeChannel(2), "Invalid")
        )


class MatchTests(unittest.TestCase):
    @staticmethod
    def adv(data: bytes):
        return AdvertisementData(
            local_name="LMB",
            manufacturer_data={0x5053: data},
            service_data={},
            service_uuids=["0000e0ff-0000-1000-8000-00805f9b34fb"],
            tx_power=None,
            rssi=-60,
            platform_data=(),
        )

    @staticmethod
    def dev():
        return BLEDevice(
            "AA:BB:CC:DD:D3:EA",
            "LMB",
            {},
        )

    def test_shared_signature_requires_protocol_resolution(self):
        m = UniledBleDevice.match_known_device(
            self.dev(), self.adv(bytes.fromhex("01007a5c123062d3ea000000"))
        )
        self.assertIs(m, True)

    def test_sp662e_model_byte_matches_even_with_generic_name(self):
        adv = self.adv(bytes.fromhex("01007bb4201d321b0a000000"))
        for name in ("SP662E", "LMB"):
            with self.subTest(name=name):
                dev = BLEDevice("B4:20:1D:32:1B:0A", name, {})
                self.assertIs(UniledBleDevice.match_known_device(dev, adv), SP662E)

    def test_named_sp601e_with_shared_signature_keeps_model(self):
        dev = BLEDevice("AA:BB:CC:DD:D3:EA", "SP601E", {})
        self.assertIs(
            UniledBleDevice.match_known_device(
                dev, self.adv(bytes.fromhex("01007a5c123062d3ea000000"))
            ),
            SP601E,
        )

    def test_other_01_prefix_still_sp601e(self):
        m = UniledBleDevice.match_known_device(
            self.dev(), self.adv(bytes.fromhex("01027a5c123062d3ea000000"))
        )
        self.assertIs(m, SP601E)


class RestoreTests(unittest.TestCase):
    def test_model_found_by_stored_name(self):
        """A saved config entry only stores the model name; it must resolve to SP661E/SP662E."""
        self.assertIs(UniledBleDevice.match_model_name("SP661E"), SP661E)
        self.assertIs(UniledBleDevice.match_model_name("SP662E"), SP662E)
        self.assertIs(UniledBleDevice.match_model_name("SP601E"), SP601E)

    def test_unknown_name_is_none(self):
        self.assertIsNone(UniledBleDevice.match_model_name("LMB"))


class NamingTests(unittest.TestCase):
    def test_named_after_model_not_advertised_name(self):
        self.assertTrue(SP661E.use_model_name)
        # advertised name may be junk such as "3" or "LMB"
        self.assertEqual(
            UniledBleDevice.human_readable_name(
                SP661E.model_name, "", "AA:BB:CC:DD:D3:EA"
            ),
            "SP661E (D3EA)",
        )

    def test_other_models_keep_advertised_name(self):
        self.assertFalse(getattr(SP601E, "use_model_name", False))


class WriteModeTests(unittest.TestCase):
    def test_sp661e_writes_without_response(self):
        self.assertFalse(SP661E.write_with_response)

    def test_other_models_keep_default(self):
        self.assertTrue(getattr(SP601E, "write_with_response", True))


class DeviceConstructionTests(unittest.IsolatedAsyncioTestCase):
    """Regression: building the device must not touch attributes before __init__ sets them."""

    @staticmethod
    def make(ble_name, model_name):
        ble = BLEDevice("AA:BB:CC:DD:D3:EA", ble_name, {})
        adv = MatchTests.adv(bytes.fromhex("01007a5c123062d3ea000000"))
        return UniledBleDevice({}, ble, adv, model_name)

    async def test_name_with_junk_advertised_name(self):
        for advertised_name in ("3", "LMB", ""):
            dev = self.make(advertised_name, "SP661E")
            self.assertIs(dev.model, SP661E)
            self.assertEqual(dev.name, "SP661E (D3EA)")

    async def test_ambiguous_advertisement_defers_model_selection(self):
        dev = self.make("3", None)
        self.assertIsNone(dev.model)

    async def test_shared_signature_resolves_by_response(self):
        # The same advertisement can belong to either model. Only a successful
        # protocol query may decide which one to persist in the config entry.
        for responding_model in (SP661E, SP601E):
            dev = self.make("LMB", None)
            queried = []

            async def query(retry):
                queried.append(dev.model)
                if dev.model is responding_model:
                    if responding_model is SP661E:
                        return dev.model.parse_notifications(dev, 0, bytearray(STATUS))
                    return True
                return False

            with (
                patch(
                    "custom_components.uniled.lib.ble.models.UNILED_BLE_MODELS",
                    [SP661E, SP601E],
                ),
                patch.object(dev, "update", side_effect=query),
                patch.object(dev, "stop", new_callable=AsyncMock),
            ):
                self.assertIs(await dev.resolve_model(), responding_model)
            self.assertIs(dev.model, responding_model)
            self.assertEqual(
                queried, [SP661E] if responding_model is SP661E else [SP661E, SP601E]
            )

    async def test_transport_uses_model_write_mode(self):
        for model, response in ((SP661E, False), (SP601E, True)):
            dev = self.make("LMB", model.model_name)
            dev._client = SimpleNamespace(
                is_connected=True, write_gatt_char=AsyncMock()
            )
            dev._write_char = object()
            command = model.build_state_query(dev)
            self.assertTrue(await dev._execute_commands_locked([command]))
            dev._client.write_gatt_char.assert_awaited_once_with(
                dev._write_char, command, response
            )

    async def test_other_model_keeps_advertised_name(self):
        ble = BLEDevice("AA:BB:CC:DD:D3:EA", "SP601E-test", {})
        adv = MatchTests.adv(bytes.fromhex("01027a5c123062d3ea000000"))
        dev = UniledBleDevice({}, ble, adv, None)
        self.assertEqual(dev.name, "SP601E-test")

    def test_del_survives_failed_init(self):
        from custom_components.uniled.lib.device import UniledDevice

        broken = UniledDevice.__new__(UniledDevice)  # __init__ never ran
        broken._ble_device = None
        UniledDevice.__del__(broken)  # must not raise


if __name__ == "__main__":
    unittest.main()
