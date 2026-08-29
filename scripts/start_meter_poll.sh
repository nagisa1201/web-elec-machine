#!/usr/bin/env bash
# RDK X5 UART1 DL/T 645-2007 full-catalog meter acquisition.
# Override a default only when the meter or wiring configuration changes.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SERIAL_PORT="${SERIAL_PORT:-/dev/ttyS1}"
BAUD="${BAUD:-1200}"
PARITY="${PARITY:-even}"
METER_ADDRESS="${METER_ADDRESS:-557499000093}"
POLL_INTERVAL="${POLL_INTERVAL:-5}"
TIMEOUT="${TIMEOUT:-2}"
DATABASE="${DATABASE:-${ROOT_DIR}/meter_readings.sqlite3}"

if [[ ! -e "${SERIAL_PORT}" ]]; then
  echo "Serial device not found: ${SERIAL_PORT}" >&2
  exit 2
fi

echo "Starting DL/T 645 full-catalog polling"
echo "  port:     ${SERIAL_PORT}"
echo "  format:   ${BAUD} baud, 8 data bits, ${PARITY} parity, 1 stop bit"
echo "  meter:    ${METER_ADDRESS}"
echo "  interval: ${POLL_INTERVAL}s"
echo "  database: ${DATABASE}"

cd "${ROOT_DIR}"
exec env PYTHONPATH=host python3 host/dlt645_usb.py \
  --port "${SERIAL_PORT}" \
  --baud "${BAUD}" \
  --parity "${PARITY}" \
  --version 2007 \
  --addr "${METER_ADDRESS}" \
  --all \
  --poll \
  --interval "${POLL_INTERVAL}" \
  --timeout "${TIMEOUT}" \
  --db "${DATABASE}" \
  --brief
