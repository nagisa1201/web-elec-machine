import unittest

from dlt645_converter import (
    FrameDecoder,
    build_read_address_request,
    build_read_request,
    data_point,
    decode_frame,
    parse_address,
    read_codes,
)


def response(address: bytes, code: int, payload: bytes, version: str = "2007", control: int | None = None) -> bytes:
    width = 2 if version == "1997" else 4
    body = bytearray([0x68])
    body.extend(address)
    body.extend((0x68, control if control is not None else (0x81 if version == "1997" else 0x91)))
    body.append(width + len(payload))
    body.extend(bytes(((code >> (8 * i)) & 0xFF) + 0x33 for i in range(width)))
    body.extend(payload)
    body.extend((sum(body) & 0xFF, 0x16))
    return bytes(body)


class ConverterTests(unittest.TestCase):
    def test_request_contains_reversed_address_and_encoded_code(self):
        address = parse_address("123456789012")
        request = build_read_request(address, 0x02010100, "2007", preamble_count=0)
        self.assertEqual(request.hex().upper(), "68129078563412681104333434356B16")

    def test_read_address_request_uses_universal_address(self):
        request = build_read_address_request(preamble_count=0)
        self.assertEqual(request.hex().upper(), "68AAAAAAAAAAAA681300DF16")

    def test_decoder_handles_preamble_split_and_two_frames(self):
        address = parse_address("123456789012")
        first = response(address, 0x02010100, bytes((0x33 + 0x32, 0x33 + 0x12)))
        second = response(address, 0x02010100, bytes((0x33 + 0x04, 0x33 + 0x31)))
        decoder = FrameDecoder()
        frames = decoder.feed(b"\xFE\xFE" + first[:7])
        self.assertEqual(frames, [])
        frames = decoder.feed(first[7:] + second)
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0].preamble, b"\xFE\xFE")

    def test_2007_voltage_conversion(self):
        address = parse_address("123456789012")
        frame = FrameDecoder().feed(response(address, 0x02010100, bytes((0x33 + 0x32, 0x33 + 0x12))))[0]
        decoded = decode_frame(frame, "2007", 0x02010100)
        self.assertEqual(decoded["value"], 123.2)
        self.assertEqual(decoded["scale"], 1)

    def test_1997_current_conversion(self):
        address = parse_address("123456789012")
        frame = FrameDecoder().feed(response(address, 0xB621, bytes((0x33 + 0x34, 0x33 + 0x12)), "1997"))[0]
        decoded = decode_frame(frame, "1997", 0xB621)
        self.assertEqual(decoded["value"], 1234 / 100)

    def test_checksum_error_is_not_emitted(self):
        address = parse_address("123456789012")
        bad = bytearray(response(address, 0x02010100, b"\x33\x33"))
        bad[-2] ^= 1
        self.assertEqual(FrameDecoder().feed(bytes(bad)), [])

    def test_error_response_without_identifier_is_reported(self):
        address = parse_address("123456789012")
        body = bytearray([0x68])
        body.extend(address)
        body.extend((0x68, 0xD1, 1, 0x35))
        body.extend((sum(body) & 0xFF, 0x16))
        frame = FrameDecoder().feed(bytes(body))[0]
        decoded = decode_frame(frame, "2007")
        self.assertFalse(decoded["ok"])
        self.assertEqual(decoded["error_code"], 2)

    def test_catalog_contains_measurements_and_full_energy_set(self):
        self.assertEqual(data_point(0x02010100).name, "phase_a_voltage")
        self.assertEqual(data_point(0x02010100).unit, "V")
        self.assertIn(0x00010000, read_codes("2007", include_all=False))
        self.assertIn(0x00010100, read_codes("2007", include_all=True))
        self.assertNotIn(0x020C0100, read_codes("2007", include_all=False))
        self.assertNotIn(0x020C0100, read_codes("2007", include_all=True))


if __name__ == "__main__":
    unittest.main()
