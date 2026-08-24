#!/usr/bin/env bash
# 一键启动「模拟链路」：模拟电表 + Web 服务 + (可选) WIFI 热点。
#
# 用途：在 RDK X5（或任意 Linux 主机）上，用确定性模拟电表喂数据给仪表盘，
#       并顺手开一个 WIFI 热点，让你开机后立刻用手机连热点测试。
# 运行： bash scripts/start_demo.sh
#        （跳过热点： SKIP_HOTSPOT=1 bash scripts/start_demo.sh）
set -euo pipefail
cd "$(dirname "$0")/.."

# 全部可用环境变量覆盖默认值
METER_PORT="${METER_PORT:-8899}"
WEB_PORT="${WEB_PORT:-8080}"
METER_ADDR="${METER_ADDR:-123456789012}"
INTERVAL="${INTERVAL:-5}"
HOTSPOT_SSID="${HOTSPOT_SSID:-VoltMonitor}"
HOTSPOT_PASS="${HOTSPOT_PASS:-12345678}"
AP_IP="${AP_IP:-192.168.8.1}"

echo "[1/3] 启动模拟电表 tcp://127.0.0.1:${METER_PORT}（A 相 230.5 V）..."
python3 host/dlt645_simulator.py --host 127.0.0.1 --port "${METER_PORT}" --version 2007 &
SIM_PID=$!

echo "[2/3] 启动 Web 服务 0.0.0.0:${WEB_PORT} ..."
python3 -m web --db meter_readings.sqlite3 \
  --poll-tcp "127.0.0.1:${METER_PORT}" --meter "${METER_ADDR}" --interval "${INTERVAL}" \
  --host 0.0.0.0 --port "${WEB_PORT}" &
WEB_PID=$!

cleanup() {
  kill "${SIM_PID}" "${WEB_PID}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if [ "${SKIP_HOTSPOT:-0}" != "1" ]; then
  echo "[3/3] 尝试开启 WIFI 热点（SSID: ${HOTSPOT_SSID}）..."
  if sudo -n true 2>/dev/null; then
    sudo scripts/hotspot.sh --ssid "${HOTSPOT_SSID}" --pass "${HOTSPOT_PASS}" --ip "${AP_IP}" \
      || echo "    热点开启失败，请手动开启后重试（见 README）"
  else
    echo "    开启热点需要 sudo；先执行 'sudo -v' 或加 SKIP_HOTSPOT=1 跳过。"
  fi
fi

echo
echo "========================================================"
echo "  模拟链路已启动"
echo "  模拟电表  tcp://127.0.0.1:${METER_PORT}"
echo "  Web 服务  http://${AP_IP}:${WEB_PORT}"
echo
echo "  手机连热点 '${HOTSPOT_SSID}'（密码 ${HOTSPOT_PASS}）后，"
echo "  浏览器打开 http://${AP_IP}:${WEB_PORT}"
echo "========================================================"
echo " 按 Ctrl+C 停止"
wait "${WEB_PID}"
