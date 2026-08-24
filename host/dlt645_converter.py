#!/usr/bin/env python3
"""Host-side DL/T 645 frame conversion.

The upstream project contains the protocol conversion routines but leaves
serial framing to RT-Thread.  This module keeps the conversion layer
transport-independent and accepts arbitrary chunks from a USB serial device.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Optional


START = 0x68
STOP = 0x16
PREAMBLE = 0xFE
MAX_FRAME_LENGTH = 267  # 12 bytes of envelope + one-byte data length


class ProtocolError(ValueError):
    """Raised when a DL/T 645 frame or value cannot be decoded."""


@dataclass(frozen=True)
class DataPoint:
    """Metadata for a commonly useful meter data identifier."""

    code: int
    name: str
    unit: str = ""
    scale: Optional[int] = None
    value_type: str = "numeric"


_ENERGY_POINTS_2007 = (
    DataPoint(0x00000000, "combined_active_total", "kWh", 2),
    DataPoint(0x00000100, "combined_active_rate_1", "kWh", 2),
    DataPoint(0x00000200, "combined_active_rate_2", "kWh", 2),
    DataPoint(0x00000300, "combined_active_rate_3", "kWh", 2),
    DataPoint(0x00000400, "combined_active_rate_4", "kWh", 2),
    DataPoint(0x00010000, "forward_active_total", "kWh", 2),
    DataPoint(0x00010100, "forward_active_rate_1", "kWh", 2),
    DataPoint(0x00010200, "forward_active_rate_2", "kWh", 2),
    DataPoint(0x00010300, "forward_active_rate_3", "kWh", 2),
    DataPoint(0x00010400, "forward_active_rate_4", "kWh", 2),
    DataPoint(0x00020000, "reverse_active_total", "kWh", 2),
    DataPoint(0x00020100, "reverse_active_rate_1", "kWh", 2),
    DataPoint(0x00020200, "reverse_active_rate_2", "kWh", 2),
    DataPoint(0x00020300, "reverse_active_rate_3", "kWh", 2),
    DataPoint(0x00020400, "reverse_active_rate_4", "kWh", 2),
    DataPoint(0x00030000, "combined_reactive_1_total", "kvarh", 2),
    DataPoint(0x00040000, "combined_reactive_2_total", "kvarh", 2),
    DataPoint(0x00050000, "quadrant_1_reactive_total", "kvarh", 2),
    DataPoint(0x00060000, "quadrant_2_reactive_total", "kvarh", 2),
    DataPoint(0x00070000, "quadrant_3_reactive_total", "kvarh", 2),
    DataPoint(0x00080000, "quadrant_4_reactive_total", "kvarh", 2),
    DataPoint(0x00090000, "forward_apparent_total", "kVAh", 2),
)


_MEASUREMENT_POINTS_2007 = (
    DataPoint(0x02010100, "phase_a_voltage", "V", 1),
    DataPoint(0x02010200, "phase_b_voltage", "V", 1),
    DataPoint(0x02010300, "phase_c_voltage", "V", 1),
    DataPoint(0x020C0100, "line_ab_voltage", "V", 1),
    DataPoint(0x020C0200, "line_bc_voltage", "V", 1),
    DataPoint(0x020C0300, "line_ca_voltage", "V", 1),
    DataPoint(0x02020100, "phase_a_current", "A", 3),
    DataPoint(0x02020200, "phase_b_current", "A", 3),
    DataPoint(0x02020300, "phase_c_current", "A", 3),
    DataPoint(0x02030000, "total_active_power", "kW", 4),
    DataPoint(0x02030100, "phase_a_active_power", "kW", 4),
    DataPoint(0x02030200, "phase_b_active_power", "kW", 4),
    DataPoint(0x02030300, "phase_c_active_power", "kW", 4),
    DataPoint(0x02040000, "total_reactive_power", "kvar", 4),
    DataPoint(0x02040100, "phase_a_reactive_power", "kvar", 4),
    DataPoint(0x02040200, "phase_b_reactive_power", "kvar", 4),
    DataPoint(0x02040300, "phase_c_reactive_power", "kvar", 4),
    DataPoint(0x02050000, "total_apparent_power", "kVA", 4),
    DataPoint(0x02050100, "phase_a_apparent_power", "kVA", 4),
    DataPoint(0x02050200, "phase_b_apparent_power", "kVA", 4),
    DataPoint(0x02050300, "phase_c_apparent_power", "kVA", 4),
    DataPoint(0x02060000, "total_power_factor", "", 3),
    DataPoint(0x02060100, "phase_a_power_factor", "", 3),
    DataPoint(0x02060200, "phase_b_power_factor", "", 3),
    DataPoint(0x02060300, "phase_c_power_factor", "", 3),
    DataPoint(0x02800002, "frequency", "Hz", 2),
)


_EXTRA_POINTS_2007 = (
    DataPoint(0x04000101, "meter_date", "", None, "date"),
    DataPoint(0x04000102, "meter_time", "", None, "time"),
    DataPoint(0x05060001, "last_daily_freeze_time", "", None, "raw"),
    DataPoint(0x05060101, "last_daily_forward_active_energy", "kWh", 2),
    DataPoint(0x04000403, "asset_management_code", "", None, "raw"),
    DataPoint(0x04000701, "signal_strength", "", None, "numeric"),
    DataPoint(0x04000702, "meter_version", "", None, "raw"),
)


_POINTS_1997 = (
    DataPoint(0xB611, "phase_a_voltage", "V", 0),
    DataPoint(0xB612, "phase_b_voltage", "V", 0),
    DataPoint(0xB613, "phase_c_voltage", "V", 0),
    DataPoint(0xB691, "line_ab_voltage", "V", 0),
    DataPoint(0xB692, "line_bc_voltage", "V", 0),
    DataPoint(0xB693, "line_ca_voltage", "V", 0),
    DataPoint(0xB621, "phase_a_current", "A", 2),
    DataPoint(0xB622, "phase_b_current", "A", 2),
    DataPoint(0xB623, "phase_c_current", "A", 2),
    DataPoint(0xB630, "total_active_power", "kW", 4),
    DataPoint(0xB631, "phase_a_active_power", "kW", 4),
    DataPoint(0xB632, "phase_b_active_power", "kW", 4),
    DataPoint(0xB633, "phase_c_active_power", "kW", 4),
    DataPoint(0xB640, "total_reactive_power", "kvar", 4),
    DataPoint(0xB641, "phase_a_reactive_power", "kvar", 4),
    DataPoint(0xB642, "phase_b_reactive_power", "kvar", 4),
    DataPoint(0xB643, "phase_c_reactive_power", "kvar", 4),
    DataPoint(0xB660, "total_apparent_power", "kVA", 4),
    DataPoint(0xB661, "phase_a_apparent_power", "kVA", 4),
    DataPoint(0xB662, "phase_b_apparent_power", "kVA", 4),
    DataPoint(0xB663, "phase_c_apparent_power", "kVA", 4),
)


DATA_POINTS_2007 = _ENERGY_POINTS_2007 + _MEASUREMENT_POINTS_2007 + _EXTRA_POINTS_2007
DATA_POINTS_1997 = _POINTS_1997
_POINT_INDEX = {
    "2007": {point.code: point for point in DATA_POINTS_2007},
    "1997": {point.code: point for point in DATA_POINTS_1997},
}

# These identifiers returned error code 0x03 on the connected meter and are
# intentionally excluded from both the default and --all polling sets.
EXCLUDED_CODES_2007 = frozenset({
    0x00030000, 0x00040000, 0x00050000, 0x00060000,
    0x00070000, 0x00080000, 0x00090000,
    0x02010200, 0x02010300, 0x02020300,
    0x02030200, 0x02030300,
    0x02040000, 0x02040100, 0x02040200, 0x02040300,
    0x02050000, 0x02050100, 0x02050200, 0x02050300,
    0x02060200, 0x02060300,
    0x020C0100, 0x020C0200, 0x020C0300,
    0x04000702,
})

POLL_CODES_2007 = tuple(
    point.code for point in DATA_POINTS_2007 if point.code not in EXCLUDED_CODES_2007
)

# The default polling set contains live electrical values and total energy.
# Tariff breakdowns and metadata remain available through --all, except for
# the known unsupported identifiers above.
USEFUL_CODES_2007 = tuple(
    point.code for point in _ENERGY_POINTS_2007 if point.code in {
        0x00000000, 0x00010000, 0x00020000, 0x00030000, 0x00040000,
    } and point.code not in EXCLUDED_CODES_2007
) + tuple(
    point.code for point in _MEASUREMENT_POINTS_2007
    if point.code not in EXCLUDED_CODES_2007
)
USEFUL_CODES_1997 = tuple(point.code for point in DATA_POINTS_1997)


def data_point(code: int, version: str = "2007") -> Optional[DataPoint]:
    """Return metadata for a data identifier, if it is in the local catalog."""
    return _POINT_INDEX.get(version, {}).get(code)


def read_codes(version: str = "2007", include_all: bool = False) -> tuple[int, ...]:
    """Return the built-in polling identifiers for a protocol version."""
    if version == "2007":
        return POLL_CODES_2007 if include_all else USEFUL_CODES_2007
    if version == "1997":
        return tuple(point.code for point in DATA_POINTS_1997)
    raise ValueError("version must be 1997 or 2007")


def _clean_hex(value: str) -> str:
    return value.replace(" ", "").replace(":", "").replace("-", "").replace("_", "")


def parse_address(value: str) -> bytes:
    """Parse a human-order 12-digit meter address into wire-order bytes."""
    text = _clean_hex(value)
    if len(text) != 12:
        raise ValueError("meter address must contain exactly 12 hex digits")
    try:
        address = bytes.fromhex(text)
    except ValueError as exc:
        raise ValueError("meter address is not hexadecimal") from exc
    return address[::-1]


def format_address(wire_address: bytes) -> str:
    if len(wire_address) != 6:
        raise ValueError("DL/T 645 addresses are six bytes")
    return wire_address[::-1].hex().upper()


def parse_code(value: str, version: str) -> int:
    try:
        code = int(value, 0)
    except ValueError as exc:
        raise ValueError(f"invalid data identifier: {value}") from exc
    limit = 0xFFFF if version == "1997" else 0xFFFFFFFF
    if code < 0 or code > limit:
        raise ValueError(f"data identifier does not fit DL/T 645-{version}")
    return code


def _encode_identifier(code: int, width: int) -> bytes:
    return bytes(((code >> (8 * index)) & 0xFF) + 0x33 for index in range(width))


def build_read_request(
    address: bytes,
    code: int,
    version: str = "2007",
    preamble_count: int = 4,
) -> bytes:
    """Build a DL/T 645 read-data request, including checksum and stop byte."""
    if len(address) != 6:
        raise ValueError("address must contain six wire-order bytes")
    if version not in ("1997", "2007"):
        raise ValueError("version must be 1997 or 2007")
    width = 2 if version == "1997" else 4
    if code < 0 or code >= (1 << (8 * width)):
        raise ValueError("data identifier is out of range")
    body = bytearray([START])
    body.extend(address)
    body.extend((START, 0x01 if version == "1997" else 0x11, width))
    body.extend(_encode_identifier(code, width))
    body.append(sum(body) & 0xFF)
    body.append(STOP)
    if not 0 <= preamble_count <= 32:
        raise ValueError("preamble_count must be between 0 and 32")
    return bytes([PREAMBLE] * preamble_count) + bytes(body)


def build_read_address_request(preamble_count: int = 4) -> bytes:
    """Build the DL/T 645-2007 broadcast request for a meter address."""
    if not 0 <= preamble_count <= 32:
        raise ValueError("preamble_count must be between 0 and 32")
    body = bytearray([START])
    body.extend(b"\xAA" * 6)
    body.extend((START, 0x13, 0x00))
    body.append(sum(body) & 0xFF)
    body.append(STOP)
    return bytes([PREAMBLE] * preamble_count) + bytes(body)


def _checksum(body: bytes) -> int:
    return sum(body[:-2]) & 0xFF


@dataclass(frozen=True)
class Frame:
    """A validated DL/T 645 frame."""

    body: bytes
    preamble: bytes = b""

    @property
    def raw(self) -> bytes:
        return self.preamble + self.body

    @property
    def address_wire(self) -> bytes:
        return self.body[1:7]

    @property
    def address(self) -> str:
        return format_address(self.address_wire)

    @property
    def control(self) -> int:
        return self.body[8]

    @property
    def data_length(self) -> int:
        return self.body[9]

    @property
    def data(self) -> bytes:
        return self.body[10 : 10 + self.data_length]

    @property
    def checksum(self) -> int:
        return self.body[-2]


def _validate_body(body: bytes) -> None:
    if len(body) < 12:
        raise ProtocolError("DL/T 645 frame is too short")
    if body[0] != START or body[7] != START or body[-1] != STOP:
        raise ProtocolError("invalid DL/T 645 frame markers")
    expected_length = 12 + body[9]
    if len(body) != expected_length:
        raise ProtocolError("DL/T 645 frame length does not match length field")
    if body[-2] != _checksum(body):
        raise ProtocolError("DL/T 645 checksum mismatch")


class FrameDecoder:
    """Incremental parser for USB serial chunks (noise, FE preambles, and frames)."""

    def __init__(self, max_frame_length: int = MAX_FRAME_LENGTH) -> None:
        self.buffer = bytearray()
        self.max_frame_length = max_frame_length
        self.pending_preamble = bytearray()

    def feed(self, chunk: bytes) -> List[Frame]:
        self.buffer.extend(chunk)
        frames: List[Frame] = []
        while True:
            start = self.buffer.find(bytes([START]))
            if start < 0:
                # Keep split FE preambles; unrelated USB noise is discarded.
                suffix = bytes(self.buffer)
                index = len(suffix)
                while index and suffix[index - 1] == PREAMBLE:
                    index -= 1
                self.pending_preamble = bytearray(suffix[index:])
                self.buffer.clear()
                break
            prefix = bytes(self.buffer[:start])
            index = len(prefix)
            while index and prefix[index - 1] == PREAMBLE:
                index -= 1
            preamble = bytes(self.pending_preamble) + prefix[index:]
            self.pending_preamble.clear()
            if start:
                del self.buffer[:start]
            if len(self.buffer) < 10:
                self.pending_preamble.extend(preamble)
                break
            if self.buffer[7] != START:
                del self.buffer[0]
                continue
            total = 12 + self.buffer[9]
            if total > self.max_frame_length:
                del self.buffer[0]
                continue
            if len(self.buffer) < total:
                break
            candidate = bytes(self.buffer[:total])
            del self.buffer[:total]
            try:
                _validate_body(candidate)
            except ProtocolError:
                # A corrupted frame can contain a valid start byte. Re-feed its
                # tail so the next frame is not lost.
                self.buffer = bytearray(candidate[1:]) + self.buffer
                continue
            frames.append(Frame(candidate, preamble))
        return frames


_ENERGY_2007 = {
    0x00000000, 0x00000100, 0x00000200, 0x00000300, 0x00000400,
    0x00010000, 0x00010100, 0x00010200, 0x00010300, 0x00010400,
    0x00020000, 0x00020100, 0x00020200, 0x00020300, 0x00020400,
    0x00030000, 0x00040000, 0x00050000, 0x00060000, 0x00070000,
    0x00080000, 0x00090000,
}
_RAW_2007 = {0x04000403, 0x05060001, 0x07000001, 0x07000002}


def _scale_2007(code: int) -> Optional[int]:
    if code in _ENERGY_2007:
        return 2
    if code == 0x05060101:
        return 2
    if code in {0x02010100, 0x02010200, 0x02010300, 0x020C0100, 0x020C0200, 0x020C0300}:
        return 1
    if code in {0x02020100, 0x02020200, 0x02020300}:
        return 3
    if code in {
        0x02030000, 0x02030100, 0x02030200, 0x02030300,
        0x02040000, 0x02040100, 0x02040200, 0x02040300,
        0x02050000, 0x02050100, 0x02050200, 0x02050300,
    }:
        return 4
    if code in {0x02060000, 0x02060100, 0x02060200, 0x02060300}:
        return 3
    if code == 0x02800002:
        return 2
    return None


def _scale_1997(code: int) -> Optional[int]:
    if code in {0xB611, 0xB612, 0xB613, 0xB691, 0xB692, 0xB693}:
        return 0
    if code in {0xB621, 0xB622, 0xB623}:
        return 2
    if code in {0xB630, 0xB631, 0xB632, 0xB633}:
        return 4
    return None


def _decode_bcd(encoded: bytes) -> tuple[bytes, int]:
    decoded = bytes((byte - 0x33) & 0xFF for byte in encoded)
    digits: List[str] = []
    for byte in decoded:
        low, high = byte & 0x0F, byte >> 4
        if low > 9 or high > 9:
            raise ProtocolError("invalid BCD digit in data payload")
        digits.extend((str(low), str(high)))
    # The protocol transmits the least significant BCD digit first.
    return decoded, int("".join(reversed(digits))) if digits else 0


def decode_frame(
    frame: Frame,
    version: str = "2007",
    expected_code: Optional[int] = None,
) -> dict[str, Any]:
    """Validate and convert a response frame into JSON-serializable data."""
    if version not in ("1997", "2007"):
        raise ValueError("version must be 1997 or 2007")
    width = 2 if version == "1997" else 4
    data = frame.data
    code: Optional[int] = None
    if len(data) >= width:
        decoded_identifier = bytes((byte - 0x33) & 0xFF for byte in data[:width])
        code = int.from_bytes(decoded_identifier, "little")
        if expected_code is not None and not (frame.control & 0x40) and code != expected_code:
            raise ProtocolError(f"response data identifier 0x{code:X} does not match request 0x{expected_code:X}")
    elif not (frame.control & 0x40):
        raise ProtocolError("response does not contain a data identifier")
    payload_start = width if code is not None else 0
    point = data_point(code, version) if code is not None else None

    result: dict[str, Any] = {
        "protocol": f"DLT645-{version}",
        "address": frame.address,
        "address_wire": frame.address_wire.hex().upper(),
        "control": f"0x{frame.control:02X}",
        "data_identifier": f"0x{code:0{width * 2}X}" if code is not None else None,
        "data_length": frame.data_length,
        "data_raw": data[payload_start:].hex().upper(),
        "raw": frame.raw.hex().upper(),
        "preamble_length": len(frame.preamble),
    }
    if point is not None:
        result["data_name"] = point.name
        result["unit"] = point.unit
    if frame.control & 0x40:
        error_data = data[payload_start:]
        result["ok"] = False
        result["error_code"] = (error_data[-1] - 0x33) & 0xFF if error_data else None
        result["error_data"] = error_data.hex().upper()
        return result

    payload = data[width:]
    if point is not None and point.value_type in ("raw", "date", "time"):
        decoded = bytes((byte - 0x33) & 0xFF for byte in payload)
        result["data_decoded"] = decoded.hex().upper()
        if point.value_type == "raw":
            try:
                text = decoded.decode("ascii").rstrip("\x00")
            except UnicodeDecodeError:
                text = ""
            result["value"] = text if text and all(32 <= ord(char) < 127 for char in text) else decoded.hex().upper()
        else:
            # Date/time fields are BCD in wire order. Keep the digit string
            # lossless; meter vendors differ in how they display the fields.
            digits = []
            for byte in decoded:
                digits.extend((str(byte & 0x0F), str((byte >> 4) & 0x0F)))
            result["value"] = "".join(digits)
    elif code in (_RAW_2007 if version == "2007" else set()):
        decoded = bytes((byte - 0x33) & 0xFF for byte in payload)
        result["data_decoded"] = decoded.hex().upper()
        try:
            text = decoded.decode("ascii")
        except UnicodeDecodeError:
            text = ""
        result["value"] = text if text and all(32 <= ord(char) < 127 for char in text) else decoded.hex().upper()
    else:
        decoded, integer = _decode_bcd(payload)
        scale = point.scale if point is not None and point.scale is not None else (
            _scale_2007(code) if version == "2007" else _scale_1997(code)
        )
        result["data_decoded"] = decoded.hex().upper()
        result["value"] = integer / (10**scale) if scale is not None else integer
        if scale is not None:
            result["scale"] = scale
    result["ok"] = True
    return result


def decode_chunks(chunks: Iterable[bytes], version: str = "2007") -> List[dict[str, Any]]:
    decoder = FrameDecoder()
    result: List[dict[str, Any]] = []
    for chunk in chunks:
        result.extend(decode_frame(frame, version) for frame in decoder.feed(chunk))
    return result
