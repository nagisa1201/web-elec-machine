#!/usr/bin/env python3
"""在 RDK X5 上开启 WIFI 热点（AP），供手机连接访问 Web 仪表盘。

等价于参考实现里的 ``start_hotspot()``：先断开当前 WiFi，再用 NetworkManager
的「一键热点」子命令 ``nmcli device wifi hotspot`` 创建热点。热点网关默认
``10.42.0.1``（NetworkManager 共享连接的默认地址）。

用法：
    sudo python3 scripts/hotspot.py
    sudo python3 scripts/hotspot.py --ssid RDK_VOLT --password 12345678 --iface wlan0
"""

from __future__ import annotations

import argparse
import subprocess
import time

DEFAULT_SSID = "RDK_VOLT"
DEFAULT_PASSWORD = "12345678"
DEFAULT_IFACE = "wlan0"
DEFAULT_AP_IP = "10.42.0.1"  # NetworkManager shared-hotspot default gateway
DEFAULT_WEB_PORT = "8080"


def start_hotspot(
    ssid: str = DEFAULT_SSID,
    password: str = DEFAULT_PASSWORD,
    iface: str = DEFAULT_IFACE,
    ap_ip: str = DEFAULT_AP_IP,
    web_port: str = DEFAULT_WEB_PORT,
) -> bool:
    """断开当前 WiFi 并启动 AP 热点，返回是否成功。"""
    print(">>> 准备切换到热点模式...")

    # 1. 断开当前 WiFi 连接（若网卡处于客户端模式）。
    subprocess.run(
        ["nmcli", "device", "disconnect", iface],
        capture_output=True,
    )
    time.sleep(1)

    # 2. 一键启动 AP 热点。
    print(f">>> 正在启动 {ssid} 热点...")
    result = subprocess.run(
        [
            "nmcli", "device", "wifi", "hotspot",
            "ssid", ssid,
            "password", password,
            "ifname", iface,
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print("==================================================")
        print("✅ 热点启动成功！")
        print(f"📱 1. 请用手机连接 Wi-Fi: {ssid} (密码: {password})")
        print(f"🌐 2. 手机浏览器访问: http://{ap_ip}:{web_port}")
        print("==================================================")
        return True

    print("❌ 热点启动失败，请检查网卡状态:", result.stderr)
    return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="开启 RDK X5 WIFI 热点（AP）")
    parser.add_argument("--ssid", default=DEFAULT_SSID, help="热点名称")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="热点密码")
    parser.add_argument("--iface", default=DEFAULT_IFACE, help="WiFi 网卡名")
    parser.add_argument("--ip", default=DEFAULT_AP_IP, help="热点网关 IP（仅用于提示）")
    parser.add_argument("--port", default=DEFAULT_WEB_PORT, help="Web 服务端口（仅用于提示）")
    args = parser.parse_args(argv)

    return 0 if start_hotspot(args.ssid, args.password, args.iface, args.ip, args.port) else 1


if __name__ == "__main__":
    raise SystemExit(main())
