#!/usr/bin/env bash
# 在板卡上开启 WIFI 热点（AP），供手机连接访问 Web 仪表盘。
#
# 依赖 NetworkManager（nmcli）。若板卡用 hostapd + dnsmasq，见 web/README.md。
# 用法： sudo scripts/hotspot.sh --ssid VoltMonitor --pass 12345678 --ip 192.168.8.1
set -euo pipefail

SSID="VoltMonitor"
PASS="12345678"
IP="192.168.8.1"
IFACE="${IFACE:-}"
CONN="voltmonitor-ap"

while [ $# -gt 0 ]; do
  case "$1" in
    --ssid) SSID="$2"; shift 2 ;;
    --pass) PASS="$2"; shift 2 ;;
    --ip) IP="$2"; shift 2 ;;
    --iface) IFACE="$2"; shift 2 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

if ! command -v nmcli >/dev/null 2>&1; then
  echo "未找到 nmcli；请改用 hostapd + dnsmasq（见 web/README.md）" >&2
  exit 1
fi

# 未指定网卡时，取第一块 WiFi 设备。
if [ -z "$IFACE" ]; then
  IFACE=$(nmcli -t -f DEVICE,TYPE device | awk -F: '$2=="wifi"{print $1; exit}')
fi
if [ -z "$IFACE" ]; then
  echo "未找到 WiFi 网卡" >&2
  exit 1
fi

echo "使用网卡: ${IFACE}  热点 IP: ${IP}"

# 复用已存在的热点连接，否则新建一个 AP 连接。
if ! nmcli connection show "$CONN" >/dev/null 2>&1; then
  nmcli connection add type wifi ifname "$IFACE" con-name "$CONN" \
    autoconnect no ssid "$SSID"
  nmcli connection modify "$CONN" \
    802-11-wireless.mode ap \
    ipv4.method shared \
    ipv4.addresses "$IP/24"
  nmcli connection modify "$CONN" \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "$PASS"
fi

# 若网卡当前是客户端（station），nmcli 会自动断开原连接再起 AP。
nmcli connection up "$CONN"

echo
echo "热点已开启： SSID=${SSID}  密码=${PASS}  网关=${IP}"
echo "手机连接该热点后，浏览器打开 http://${IP}:8080（或你配置的端口）"
