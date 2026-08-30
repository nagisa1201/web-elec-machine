#!/usr/bin/env bash
# 一键启动「真实链路」：RS485 串口采集（DL/T 645-2007）+ Web 服务 + (可选) WIFI 热点。
#
# 与 scripts/start_demo.sh 的区别：这里用真实电表（RS485 串口）采集，
# 而不是 TCP 模拟器。采集进程 (host/dlt645_usb.py) 负责写库，
# Web 进程 (python3 -m web) 只读同一份 SQLite 库（WAL 模式并发），
# 两者通过共享库文件「串」成一条完整的数据链路。
#
# 运行：     bash scripts/start_full.sh
# 跳过热点： SKIP_HOTSPOT=1 bash scripts/start_full.sh
# 所有默认值均可用环境变量覆盖（与 start_meter_poll.sh / start_demo.sh 保持一致）。
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

# ---- 采集（串口）参数：与 scripts/start_meter_poll.sh 保持一致 ----
SERIAL_PORT="${SERIAL_PORT:-/dev/ttyS1}"
BAUD="${BAUD:-1200}"
PARITY="${PARITY:-even}"
METER_ADDRESS="${METER_ADDRESS:-557499000093}"
POLL_INTERVAL="${POLL_INTERVAL:-5}"
TIMEOUT="${TIMEOUT:-2}"
DATABASE="${DATABASE:-${ROOT_DIR}/meter_readings.sqlite3}"

# ---- Web 服务参数 ----
WEB_HOST="${WEB_HOST:-0.0.0.0}"
WEB_PORT="${WEB_PORT:-8080}"
OUTAGE_GAP="${OUTAGE_GAP:-30}"   # 连续多少秒无读数即判为停电

# ---- WIFI 热点参数 ----
HOTSPOT_SSID="${HOTSPOT_SSID:-RDK_VOLT}"
HOTSPOT_PASS="${HOTSPOT_PASS:-12345678}"
HOTSPOT_IFACE="${HOTSPOT_IFACE:-wlan0}"
AP_IP="${AP_IP:-10.42.0.1}"

# 串口不存在则快速失败，避免采集进程空转。
if [[ ! -e "${SERIAL_PORT}" ]]; then
  echo "串口设备不存在: ${SERIAL_PORT}" >&2
  echo "  请检查 RS485 接线，或用 SERIAL_PORT=/dev/ttySx 指定正确串口。" >&2
  exit 2
fi

echo "[1/3] 启动 RS485 串口采集 -> ${DATABASE}"
echo "      ${SERIAL_PORT} @ ${BAUD} ${PARITY}  电表 ${METER_ADDRESS}  每 ${POLL_INTERVAL}s 一轮"
env PYTHONPATH=host python3 host/dlt645_usb.py \
  --port "${SERIAL_PORT}" --baud "${BAUD}" --parity "${PARITY}" \
  --version 2007 --addr "${METER_ADDRESS}" --all --poll \
  --interval "${POLL_INTERVAL}" --timeout "${TIMEOUT}" \
  --db "${DATABASE}" --brief &
POLL_PID=$!

echo "[2/3] 启动 Web 服务 http://${WEB_HOST}:${WEB_PORT}  (读库 ${DATABASE}, 停电阈值 ${OUTAGE_GAP}s)"
python3 -m web --db "${DATABASE}" --host "${WEB_HOST}" --port "${WEB_PORT}" \
  --outage-gap "${OUTAGE_GAP}" &
WEB_PID=$!

cleanup() {
  kill "${POLL_PID}" "${WEB_PID}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if [ "${SKIP_HOTSPOT:-0}" != "1" ]; then
  echo "[3/3] 尝试开启 WIFI 热点（SSID: ${HOTSPOT_SSID}）..."
  if sudo -n true 2>/dev/null; then
    sudo python3 scripts/hotspot.py \
      --ssid "${HOTSPOT_SSID}" --password "${HOTSPOT_PASS}" \
      --iface "${HOTSPOT_IFACE}" --ip "${AP_IP}" --port "${WEB_PORT}" \
      || echo "    热点开启失败，请手动开启后重试（见 README）"
  else
    echo "    开启热点需要 sudo；先执行 'sudo -v' 或加 SKIP_HOTSPOT=1 跳过。"
  fi
fi

echo
echo "========================================================"
echo "  真实链路已启动"
echo "  串口采集  ${SERIAL_PORT} @ ${BAUD} ${PARITY} -> ${DATABASE}"
echo "  Web 服务  http://${AP_IP}:${WEB_PORT}"
echo
echo "  手机连热点 '${HOTSPOT_SSID}'（密码 ${HOTSPOT_PASS}）后，"
echo "  浏览器打开 http://${AP_IP}:${WEB_PORT}"
echo "========================================================"
echo "  按 Ctrl+C 停止（会自动结束采集与 Web 两个进程）"
wait "${WEB_PID}"
