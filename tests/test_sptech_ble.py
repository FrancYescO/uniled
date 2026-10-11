"""BLE notification framing for SPTech controllers."""

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

package = ModuleType("custom_components.uniled")
package.__path__ = [str(Path(__file__).parents[1] / "custom_components" / "uniled")]
sys.modules["custom_components.uniled"] = package

from custom_components.uniled.lib.ble.device import ParseNotificationError  # noqa: E402
from custom_components.uniled.lib.ble.sp63x_64xe import SPTechBleModel  # noqa: E402
from custom_components.uniled.lib.sptech_model import SPTechModel  # noqa: E402


class CapturingModel:
    cmd = SPTechModel.cmd
    parse_notifications = SPTechBleModel.parse_notifications

    def __init__(self):
        self.payloads = []

    def decode_response_payload(self, device, command, header, data):
        self.payloads.append(bytes(data))
        return True


def packet(total, index, payload):
    return bytearray([0x53, 0x02, 0, total, index, len(payload)]) + bytearray(payload)


def test_reassembles_multi_packet_status():
    model = CapturingModel()
    device = SimpleNamespace()

    assert model.parse_notifications(device, 0, packet(2, 0, [0, 1])) is None
    assert model.payloads == []
    assert model.parse_notifications(device, 0, packet(2, 1, [2, 3])) is True
    assert model.payloads == [bytes([0, 1, 2, 3])]
    assert not hasattr(device, "_sptech_buffer")


def test_discards_out_of_order_and_expired_status():
    model = CapturingModel()
    device = SimpleNamespace()

    model.parse_notifications(device, 0, packet(3, 0, [0]))
    assert model.parse_notifications(device, 0, packet(3, 2, [2])) is None
    assert not hasattr(device, "_sptech_buffer")
    assert model.parse_notifications(device, 0, packet(3, 1, [1])) is None

    model.parse_notifications(device, 0, packet(2, 0, [0]))
    device._sptech_buffer["started"] -= 6
    assert model.parse_notifications(device, 0, packet(2, 1, [1])) is None
    assert not hasattr(device, "_sptech_buffer")
    assert model.payloads == []


def test_single_packet_clears_old_buffer_and_rejects_empty_payload():
    model = CapturingModel()
    device = SimpleNamespace()

    model.parse_notifications(device, 0, packet(2, 0, [0]))
    assert model.parse_notifications(device, 0, packet(1, 0, [0, 1])) is True
    assert model.payloads == [bytes([0, 1])]
    assert not hasattr(device, "_sptech_buffer")

    with pytest.raises(ParseNotificationError, match="empty"):
        model.parse_notifications(device, 0, packet(1, 0, []))
