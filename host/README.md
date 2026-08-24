# Local USB adapter

This directory is the host-side transport and conversion layer extracted from
the upstream DL/T 645 implementation. It does not require RT-Thread or a
third-party Python package.

## Passive USB decoding

Plug in a USB-to-RS485 adapter and find its device name (`/dev/ttyUSB0`,
`/dev/ttyACM0`, or `/dev/cu.usbserial-*` on macOS), then run:

```sh
python3 host/dlt645_usb.py --port /dev/ttyUSB0 --baud 2400 --version 2007
```

Each valid frame is printed as one JSON object. The parser accepts arbitrary
read chunk sizes, optional `FE` preambles, back-to-back frames, and discards
bad checksums. Meter addresses are entered and displayed in the conventional
human order; the protocol sends the six address bytes in reverse order.

## Active read requests

```sh
python3 host/dlt645_usb.py \
  --port /dev/ttyUSB0 --baud 2400 --version 2007 \
  --addr 123456789012 --code 0x02010100 --code 0x00010000
```

Use `--preamble 0` when the meter/adapter does not accept the usual four
`FE` bytes before a request. The default baud is 2400; select 9600 for meters
configured at that rate.

Append `--debug` to print raw `TX` and `RX` bytes. This is useful when
checking the RS485 `A/B` wiring, serial settings, and response address.

## Poll all useful values into SQLite

The default polling set for the connected meter reads active energy, A-phase
voltage, A/B current, total/A-phase active power, total/A-phase power factor,
and frequency. Use `--all` to additionally query the enabled tariff breakdowns
and meter metadata. The identifiers already known to return error `0x03` on this
meter are excluded from both polling modes.

Start a five-second polling loop (stop with `Ctrl-C`):

```sh
python3 host/dlt645_usb.py \
  --port /dev/cu.usbserial-130 --baud 2400 --parity even \
  --version 2007 --addr 557499000093 \
  --poll --interval 5 --db meter_readings.sqlite3
```

To query the complete enabled local catalog in each cycle, add `--all`:

```sh
python3 host/dlt645_usb.py \
  --port /dev/cu.usbserial-130 --baud 2400 --parity even \
  --version 2007 --addr 557499000093 \
  --all --poll --interval 5 --db meter_readings.sqlite3
```

The database is SQLite and needs no server. The `meter_readings` table stores
UTC timestamp, address, protocol, identifier, name, numeric/text value, unit,
success flag, error text, decoded bytes, and the complete raw frame. Inspect it
with:

```sh
sqlite3 meter_readings.sqlite3 \
  'select recorded_at,data_name,value,value_text,unit,ok,error from meter_readings order by id desc limit 20;'
```

List all enabled identifiers and their units without opening a port:

```sh
python3 host/dlt645_usb.py --version 2007 --list-codes
```

## Find an unknown meter address

For one connected DL/T 645-2007 meter, query its communication address with
the protocol's `AA AA AA AA AA AA` universal address request:

```sh
python3 host/dlt645_usb.py --port /dev/ttyUSB0 --baud 2400 --parity even \
  --version 2007 --discover-address --timeout 3 --debug
```

The result's `address` field is the value to use with `--addr`. Connect only
one meter during this query; several meters can respond simultaneously and
their RS485 frames will collide.

## Offline frame check

```sh
python3 host/dlt645_usb.py --version 2007 --hex '68 ... 16'
```

The conversion tables and BCD/scaling rules mirror the original files:
`src/dlt645_1997.c`, `src/dlt645_2007.c`, and `src/dlt645_data.c`.

USB-TTL cannot be connected directly to an RS485 meter. Use a TTL-to-RS485
transceiver between them: `TX -> DI`, `RO -> RX`, and the transceiver `A/B`
lines to the meter `A/B`. Check the meter manual for parity; the CLI defaults
to 8N1 for compatibility with the upstream project, while many meters use
8E1, which can be selected with `--parity even`.

## No-hardware TCP test

The repository also includes a deterministic software meter. Start it in one
terminal:

```sh
python3 host/dlt645_simulator.py --host 127.0.0.1 --port 8899 --version 2007
```

Then use the converter in another terminal:

```sh
python3 host/dlt645_usb.py --tcp 127.0.0.1:8899 --version 2007 \
  --addr 123456789012 --code 0x02010100
```

This returns a deterministic `230.5` V A-phase voltage response and exercises
the same request/response path without a USB adapter. For a graphical
simulator, `600888/ems_simulate` also provides a DL/T 645-2007 server (default
TCP port `8899`): <https://github.com/600888/ems_simulate>.
