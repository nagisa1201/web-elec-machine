# 基于嵌入式 Web 服务器的无线电压监测系统

基于 **RDK X5** 的用电回路电压监测软件：通过 DL/T 645-2007 协议读取电表实时
电压，并在板卡上架设 Web 服务器，提供实时分钟电压曲线、历史日分钟电压曲线，
以及按日的最高 / 最低电压及发生时间、停电时间统计。

纯 Python 标准库实现，采集端无需第三方包，Web 端无需任何前端 CDN，适合在无
外网的 WIFI 热点（AP）场景下运行。

## 模块结构

```text
web-elec-machine/
  host/     DL/T 645 采集：协议转换、串口/TCP 传输、SQLite 存储、模拟器
  web/      Web 服务器与 UI：数据层、HTTP 服务、JSON API、自包含仪表盘
```

两个模块通过共享的 SQLite 数据文件（`meter_readings.sqlite3`）解耦：`host/`
负责“采集 + 写库”，`web/` 负责“读库 + 展示 + 统计”，互不修改对方代码。

```text
 电表 ──RS485──▶ host/dlt645_usb.py ──写──▶ meter_readings.sqlite3
                                              ▲        │
              web/poller.py (可选, TCP) ───────┘        │ 只读
                                                       ▼
                                              web/server.py ──▶ 浏览器 UI
```

| 模块 | 职责 | 详情 |
| --- | --- | --- |
| `host/` | DL/T 645-2007 帧解析、串口/TCP 采集、SQLite 落库、确定性模拟器 | [host/README.md](host/README.md) |
| `web/` | 数据访问与统计、HTTP 服务、JSON API、实时/历史曲线与日统计 UI | [web/README.md](web/README.md) |

## 快速开始

无硬件即可完整跑通“采集 → 存储 → Web 展示”链路：

```sh
# 终端一：启动确定性 TCP 电表模拟器（返回 A 相 230.5 V）
python3 host/dlt645_simulator.py --host 127.0.0.1 --port 8899 --version 2007

# 终端二：启动 Web 服务，并让内置采集线程轮询模拟器
python3 -m web --db meter_readings.sqlite3 \
  --poll-tcp 127.0.0.1:8899 --meter 123456789012 --interval 5
```

在运行服务的机器上打开 <http://127.0.0.1:8080>；手机接入板卡热点后访问的
是板卡热点 IP（见下方部署说明）。

实际部署时，电表经 RS485 接入板卡，由 `host/` 的串口采集写库，`web/` 只读：

```sh
# 采集（RS485，Linux 原生）
python3 host/dlt645_usb.py --port /dev/ttyUSB0 --baud 2400 --parity even \
  --version 2007 --addr 123456789012 --poll --interval 5 --db meter_readings.sqlite3

# Web 服务（板卡 AP 热点下监听所有网卡）
python3 -m web --db meter_readings.sqlite3 --host 0.0.0.0 --port 80
```

板卡开启 WIFI 热点后，手机连接该热点并在浏览器输入**板卡热点 IP**（AP 的
网关地址，常见 `192.168.x.1`，如 `http://192.168.8.1`，端口 80 可省略）即可
访问仪表盘；`127.0.0.1` 仅用于板卡本机调试。

## 离线解析单帧

不接设备，直接检查一帧十六进制报文：

```sh
python3 host/dlt645_usb.py --version 2007 --hex '68 ... 16'
```

## 测试

```sh
python3 -m unittest discover -s host -v
python3 -m unittest discover -s web/tests -v
python3 -m py_compile host/*.py web/*.py
```

## 许可证

详见 [`LICENSE.txt`](LICENSE.txt)。
