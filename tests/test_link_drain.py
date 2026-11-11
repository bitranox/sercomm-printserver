"""How long a print server needs to pass a job on: the rate of the link its printer hangs on."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from sercomm_printserver.domain.config_codec import parse_config, with_value
from sercomm_printserver.domain.config_model import SerialPort
from sercomm_printserver.domain.config_types import BaudRate, DataBits, Handshake, Parity, PortId, StopBits
from sercomm_printserver.domain.errors import DeviceResponseError
from sercomm_printserver.domain.link import DRAIN_MARGIN_SECONDS, LinkDrain, link_drain_for, serial_link

_CONFIG = (Path(__file__).resolve().parents[1] / "docs" / "device-dump" / "CONFIG.txt").read_text(encoding="ascii")


def _serial(*, baud: BaudRate, data: DataBits, parity: Parity, stop: StopBits) -> SerialPort:
    return SerialPort(baud_rate=baud, stop_bits=stop, parity=parity, data_bits=data, handshake=Handshake.BOTH)


@pytest.mark.parametrize(
    ("baud", "data", "parity", "stop", "frame_bits"),
    [
        (BaudRate.B9600, DataBits.EIGHT, Parity.NONE, StopBits.ONE, 10),
        (BaudRate.B9600, DataBits.SEVEN, Parity.EVEN, StopBits.ONE, 10),
        (BaudRate.B4800, DataBits.EIGHT, Parity.ODD, StopBits.TWO, 12),
        (BaudRate.B38400, DataBits.SEVEN, Parity.NONE, StopBits.TWO, 10),
        (BaudRate.B300, DataBits.EIGHT, Parity.EVEN, StopBits.ONE, 11),
    ],
)
def test_a_serial_frame_carries_one_byte_per_start_data_parity_and_stop_bits(
    baud: BaudRate, data: DataBits, parity: Parity, stop: StopBits, frame_bits: int
) -> None:
    link = serial_link(_serial(baud=baud, data=data, parity=parity, stop=stop))
    assert link.bytes_per_second == int(baud) / frame_bits
    assert link.margin == DRAIN_MARGIN_SECONDS


def test_9600_8n1_is_the_measured_960_bytes_per_second() -> None:
    link = serial_link(_serial(baud=BaudRate.B9600, data=DataBits.EIGHT, parity=Parity.NONE, stop=StopBits.ONE))
    assert link.bytes_per_second == 960.0


def test_a_printer_routed_to_the_serial_port_gets_that_ports_rate() -> None:
    config = with_value(parse_config(_CONFIG), "BAUDRATE", "4800")
    drain = link_drain_for(config, PortId.SP)
    assert drain is not None
    assert drain.bytes_per_second == 480.0


@pytest.mark.parametrize("port", [PortId.P1, PortId.P2, PortId.P3])
def test_a_printer_routed_to_a_parallel_or_usb_port_waits_for_nothing(port: PortId) -> None:
    assert link_drain_for(parse_config(_CONFIG), port) is None


def test_a_serial_route_on_a_device_without_serial_settings_is_refused() -> None:
    config = parse_config(_CONFIG).model_copy(update={"serial": None})
    with pytest.raises(DeviceResponseError, match="SP"):
        link_drain_for(config, PortId.SP)


def test_the_wait_counts_from_the_bytes_and_adds_the_margin() -> None:
    assert LinkDrain(bytes_per_second=960.0).seconds_for(1920) == pytest.approx(2.0 + DRAIN_MARGIN_SECONDS)


@pytest.mark.parametrize("rate", [0.0, -1.0])
def test_a_link_rate_must_be_positive(rate: float) -> None:
    with pytest.raises(ValidationError):
        LinkDrain(bytes_per_second=rate)


def test_a_negative_margin_is_refused() -> None:
    with pytest.raises(ValidationError):
        LinkDrain(bytes_per_second=960.0, margin=-0.1)
