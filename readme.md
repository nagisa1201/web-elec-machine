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
  scripts/  一键启动：模拟链路（模拟电表 + Web 服务 + 开热点）
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

一键模拟链路（模拟电表 + Web 服务 + 开热点）：`bash scripts/start_demo.sh`
（Windows 用 `scripts\start_demo.bat`），详见 [web/README.md](web/README.md)。

## RDK X5 正式部署：UART1 全量采集与入库

仓库的正式默认配置已经固化在 `scripts/start_meter_poll.sh`。它通过 RDK X5
40PIN 的 UART1 (`/dev/ttyS1`) 轮询电表并写入 SQLite；不需要也不会修改通信
测试命令 `host/dlt645_usb.py ... --code 0x02010100`。

### 硬件和固定串口配置

电表使用 RS485，RDK X5 UART1 使用 3.3 V TTL，二者之间必须使用 **3.3 V
TTL-RS485 收发器**，并在连接电表前移除 UART 回环检测时使用的 Pin 8-Pin 10
跳线。

```text
RDK X5 40PIN Pin 8  (UART1 TXD) -> RS485 收发器 DI
RDK X5 40PIN Pin 10 (UART1 RXD) <- RS485 收发器 RO
RDK X5 GND                       -> RS485 收发器 GND
RS485 收发器 A/B                 -> 电表 A/B
```

不能将电表 A/B 线直接接入 40PIN UART。固定默认参数如下：

| 配置项 | 默认值 |
| --- | --- |
| 串口 | `/dev/ttyS1`（UART1） |
| 串口格式 | 1200 baud、8E1（`--parity even`） |
| 协议 | DL/T 645-2007 |
| 电表地址 | `557499000093` |
| 轮询间隔 | 5 秒 |
| 单请求超时 | 2 秒 |
| 数据库 | `meter_readings.sqlite3`（项目根目录） |

### 启动正式采集

```sh
cd /root/web-elec-machine
bash scripts/start_meter_poll.sh
```

该脚本使用 `--all`，会读取当前项目目录内全部已启用且已知被此电表支持的
DL/T 645-2007 数据项，例如电能、电压、电流、有功/无功/视在功率、功率因数、
频率、费率电能、表内日期时间和冻结数据。项目中已记录为会返回 `0x03` 的
数据标识会自动跳过，避免每轮产生已知错误。按 `Ctrl-C` 停止采集。

下面的环境变量可仅在启动时覆盖默认值，脚本内容保持不变：

```sh
SERIAL_PORT=/dev/ttyS1 BAUD=1200 PARITY=even \
METER_ADDRESS=557499000093 POLL_INTERVAL=5 TIMEOUT=2 \
DATABASE=/root/web-elec-machine/meter_readings.sqlite3 \
bash scripts/start_meter_poll.sh
```

### 检查数据库与启动 Web 服务

采集器会为每个成功读数、通信超时和电表返回错误追加一行记录。检查最近结果：

```sh
cd /root/web-elec-machine
sqlite3 meter_readings.sqlite3 \
  'select recorded_at, data_name, value, value_text, unit, ok, error
   from meter_readings order by id desc limit 30;'
```

采集器运行在一个终端时，另开终端启动 Web 服务：

```sh
cd /root/web-elec-machine
python3 -m web --db meter_readings.sqlite3 --host 0.0.0.0 --port 8080
```

Web 页面当前以相电压数据绘制实时和历史曲线；其余全量数据已保存在同一
SQLite 数据库中，可供后续 API 或统计功能扩展。

实际部署时，电表经 RS485 接入板卡，由 `host/` 的串口采集写库，`web/` 只读：

```sh
# 采集：使用已固定的 UART1 全量采集默认配置
bash scripts/start_meter_poll.sh

# Web 服务（板卡 AP 热点下监听所有网卡）
python3 -m web --db meter_readings.sqlite3 --host 0.0.0.0 --port 80
```

板卡开启 WIFI 热点后，手机连接该热点并在浏览器输入**板卡热点 IP**（AP 的
网关地址，用 `nmcli device wifi hotspot` 开启时通常为 `10.42.0.1`，如
`http://10.42.0.1`，端口 80 可省略）即可访问仪表盘；`127.0.0.1` 仅用于板卡本机调试。

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
