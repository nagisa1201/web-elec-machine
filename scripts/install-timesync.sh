#!/usr/bin/env bash
# 一键配置开机自动对时（无 RTC 电池的 RDK X5 专用）。
#   fake-hwclock  记住上次时间 —— 断电重启不再回到 2000 年
#   NTP           联网精确对时 —— 把分钟/秒校准到位
# 用法（在板子上，root）：sudo bash install-timesync.sh
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "请用 root 运行：sudo bash $0" >&2
  exit 1
fi

echo "[1/4] 安装 fake-hwclock（记住上次时间）"
apt-get update -qq
apt-get install -y fake-hwclock

echo "[2/4] 启用 NTP 对时（systemd-timesyncd）"
systemctl enable systemd-timesyncd
systemctl restart systemd-timesyncd

echo "[3/4] 配置国内 NTP 服务器"
if ! grep -q '^NTP=' /etc/systemd/timesyncd.conf; then
  printf '\n[Time]\nNTP=ntp.aliyun.com ntp.tencent.com\n' >> /etc/systemd/timesyncd.conf
fi
systemctl restart systemd-timesyncd

echo "[4/4] 立即对时一次并写入 fake-hwclock"
timedatectl set-ntp true
sleep 8
timedatectl
fake-hwclock save
echo
echo "完成。当前系统时间：$(date)"
echo "若上面 System clock synchronized: yes，说明对时正常。"
echo
echo "以后每次上电流程："
echo "  1) fake-hwclock 先恢复上次保存的时间（不会回到 2000）"
echo "  2) NTP 联网后把时间精确校准"
echo "  3) 采集程序等时钟正常后才开始写库（代码里已加兜底）"
