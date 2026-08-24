# web — 嵌入式 Web 服务器与电压监测界面

面向 **RDK X5** 的无线电压监测 Web 服务：一个纯 Python 标准库实现的 HTTP
服务器，加上一套零依赖、可离线的 Web 仪表盘（Canvas 图表），用于展示电表的
**实时分钟电压曲线**、**历史日分钟电压曲线**，以及按日的
**最高 / 最低电压及发生时间、停电时间** 统计。

不依赖任何第三方 Python 包与任何前端 CDN，适合在无外网的 WIFI 热点（AP）场景
下运行。仅复用同仓库 `host/` 提供的协议转换与 SQLite 存储，**不修改** `host/`。

## 功能

- 标准库 HTTP 服务器（`http.server`），可绑定任意网卡与端口
- JSON API：电表列表、可用日期、实时曲线、历史日曲线、日统计
- 实时电压：最近 N 分钟原始采样，秒级自动刷新
- 历史曲线：按分钟取平均的全天曲线，可切换日期
- 日统计：最高电压、最低电压及其发生时间；停电次数与累计停电时长
- 停电检测：长时间无读数（采样中断）或电压骤降至阈值以下
- 自包含前端：HTML + CSS + 原生 Canvas 折线图（无 Chart.js / 无 CDN）
- 可选的内置采集线程：通过 TCP 轮询电表或模拟器，与 Web 服务同进程运行

## 分层设计（解耦）

依赖方向严格单向，各层可独立理解与测试：

```text
┌─────────────────────────────────────────────────────────────┐
│  表现层  static/  (HTML/CSS/JS 仪表盘，Canvas 图表)           │
└───────────────┬─────────────────────────────────────────────┘
                │  HTTP + JSON
┌───────────────▼─────────────────────────────────────────────┐
│  服务层  server.py  路由、静态文件、JSON API                   │
└───────────────┬─────────────────────────────────────────────┘
                │  只读查询 / 统计
┌───────────────▼─────────────────────────────────────────────┐
│  数据层  datastore.py  SQLite 只读访问、分钟聚合、日统计        │
└───────────────┬─────────────────────────────────────────────┘
                │  SELECT                         ▲ 写入
      meter_readings.sqlite3 (SQLite / WAL)       │
                                                  │
┌─────────────────────────────────────────────────┴───────────┐
│  采集层  host/  (未修改)  + 可选 web/poller.py                 │
│  · host/dlt645_usb.py --poll --db   ← RS485 串口采集          │
│  · web/poller.py                    ← TCP 采集（模拟器/网络表） │
└──────────────────────────────────────────────────────────────┘
```

要点：

- **`datastore.py` 是纯数据层**：只有 `SELECT`，不含 HTTP 与串口依赖，可独立
  单测；写入永远由采集层负责。
- **`server.py` 只做搬运**：把 HTTP 请求翻译成 `DataStore` 调用，不包含业务规则。
- **`poller.py` 是可选桥**：复用 `host/dlt645_converter` 的组帧 / 解码，只补充
  了 CLI 未暴露的传输小循环，避免重复实现协议。

## 目录结构

```text
web/
  __init__.py        包说明与版本号
  __main__.py        入口：python -m web
  config.py          配置（命令行 > 环境变量 > 默认值）
  datastore.py       只读数据访问 + 分钟聚合 + 日统计 + 停电检测
  poller.py          可选 TCP 采集线程（复用 host 转换器）
  server.py          HTTP 服务器 + JSON API + 静态文件
  static/
    index.html       仪表盘
    css/app.css      样式
    js/chart.js      原生 Canvas 折线图
    js/api.js        fetch 封装
    js/app.js        控制器（轮询、刷新、绑定）
  tests/             单元测试与集成测试
```

## 快速开始

### 1. 无硬件演示（模拟器）

终端一，启动确定性 TCP 电表模拟器（返回 A 相 230.5 V）：

```sh
python3 host/dlt645_simulator.py --host 127.0.0.1 --port 8899 --version 2007
```

终端二，启动 Web 服务并让内置采集线程同时轮询该模拟器：

```sh
python3 -m web --db meter_readings.sqlite3 \
  --poll-tcp 127.0.0.1:8899 --meter 123456789012 --interval 5
```

在运行服务的机器上打开 <http://127.0.0.1:8080> 即可看到实时曲线随时间累积
（手机接入板卡热点后访问的是板卡热点 IP，见下方“部署到 RDK X5”）。

### 2. 仅启动服务（数据由外部采集写入）

如果电表通过 RS485 串口采集，由 `host/` 的 CLI 负责写库，Web 服务只读：

```sh
# 终端一：采集（RS485，Linux 原生）
python3 host/dlt645_usb.py --port /dev/ttyUSB0 --baud 2400 --parity even \
  --version 2007 --addr 123456789012 --poll --interval 5 --db meter_readings.sqlite3

# 终端二：服务
python3 -m web --db meter_readings.sqlite3 --host 0.0.0.0 --port 8080
```

## 命令行参数

```text
服务：
  --host        绑定地址（默认 0.0.0.0）
  --port        监听端口（默认 8080）
  --db          SQLite 数据文件路径（默认 meter_readings.sqlite3）
  --tz          板卡时区偏移，如 +08:00（默认 +08:00）

监测口径：
  --minutes     实时窗口分钟数（默认 60）
  --outage-gap  多长时间无读数算停电，秒（默认 120）
  --outage-low  电压低于多少 V 算停电（默认 30）

采集（可选）：
  --poll-tcp    轮询的 HOST:PORT（电表或模拟器）
  --meter       电表地址（铭牌 12 位十六进制，如 123456789012）
  --interval    轮询间隔秒（默认 5）
  --timeout     电表响应超时秒（默认 1.5）
  --version     DL/T 645 版本 1997|2007（默认 2007）
  --phases      采集相电压：a | ab | abc（默认 a，单相表仅 A 相）
```

也支持环境变量：`WEB_HOST`、`WEB_PORT`、`WEB_DB`、`WEB_TZ`、`WEB_POLL_TCP`、
`WEB_METER`（命令行优先）。

## HTTP API

所有接口返回 `application/json`，时间戳为该时区下的本地 ISO 8601。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 服务状态、版本、数据库可用性、电表列表、最近更新时间 |
| GET | `/api/meters` | 有数据的电表地址列表 |
| GET | `/api/days?meter=` | 该电表有数据的本地日期（新→旧） |
| GET | `/api/realtime?meter=&minutes=` | 最近 N 分钟原始采样，按相分组 |
| GET | `/api/series?meter=&date=YYYY-MM-DD` | 某天按分钟平均的曲线 |
| GET | `/api/stats?meter=&date=YYYY-MM-DD` | 某天最高/最低电压及停电统计 |
| GET | `/api/stats?meter=&days=N` | 最近 N 天的统计列表 |

`realtime` / `series` 的 `series` 形如：

```json
{
  "series": [
    { "phase": "a", "label": "A相", "color": "#4f8cff",
      "points": [["2026-08-24T10:00:00+08:00", 230.5], ["2026-08-24T10:00:05+08:00", 230.8]] }
  ],
  "phases": ["a"]
}
```

`stats` 的停电段形如：

```json
{
  "max": { "value": 245.0, "time": "2026-08-24T12:00:00+08:00", "phase": "a" },
  "min": { "value": 210.0, "time": "2026-08-24T18:00:00+08:00", "phase": "a" },
  "outage_count": 1,
  "outage_seconds": 240.0,
  "outages": [ { "start": "2026-08-24T10:05:00+08:00",
                 "end": "2026-08-24T10:09:00+08:00", "seconds": 240.0 } ]
}
```

## 统计口径说明

- **本地日**：`recorded_at` 存的是 UTC 时间，读入后按 `--tz`（默认 +08:00）
  折算到板卡本地日期，“一天”即一个本地日历日。
- **分钟聚合**：历史曲线把同一分钟内的多次采样取算术平均，得到每个相每
  分钟一个点（每天至多 1440 点）。
- **最高 / 最低电压**：该日内有效电压采样的极值及其发生时刻。
- **停电检测**：满足以下任一条件即视为停电——
  1. 相邻两次读数间隔超过 `--outage-gap` 秒（电表掉电后不再上报）；
  2. 读数低于 `--outage-low` V（220 V 线路上的近零值）。
  一天首条数据之前、末条数据之后的空白不计为停电（无法与“监测器未开机”区分）。

## 模拟链路（一键启动）

不接真实电表也能完整跑通「模拟电表 → 写库 → Web 展示 → 手机访问」：

```sh
# Linux / RDK X5：模拟电表 + Web 服务 + 开热点，一步到位
bash scripts/start_demo.sh
```

启动后手机访问方式：

| 平台 | 手机怎么访问 |
| --- | --- |
| Linux / 板卡 | 手机连热点 `RDK_VOLT`（密码 `12345678`），浏览器打开 `http://10.42.0.1:8080` |
| Windows | 手动开启「设置 > 网络 > 移动热点」，手机连该热点，打开 `http://<热点IP>:8080`（通常 `192.168.137.1`） |

`start_demo.sh` 可用环境变量覆盖默认值：

```text
METER_PORT  模拟电表端口（默认 8899）    WEB_PORT  Web 服务端口（默认 8080）
METER_ADDR  电表地址（默认 123456789012） INTERVAL  轮询间隔秒（默认 5）
HOTSPOT_SSID / HOTSPOT_PASS  热点名称 / 密码    AP_IP  热点网关 IP（默认 10.42.0.1）
HOTSPOT_IFACE  WiFi 网卡名（默认 wlan0）        SKIP_HOTSPOT=1  跳过开热点
```

开热点用 NetworkManager 的一键子命令（与参考实现一致，见 `scripts/hotspot.py`）：

```text
nmcli device disconnect wlan0
nmcli device wifi hotspot ssid RDK_VOLT password 12345678 ifname wlan0
```

热点网关为 NetworkManager 共享连接的默认地址 `10.42.0.1`；Web 服务只要求绑定 `0.0.0.0`。

## 部署到 RDK X5（AP 热点场景）

完整链路：**RDK X5 开启 WIFI 热点 → 手机连接该热点 → 手机浏览器访问板卡热点 IP**。

1. 由队友用 `host/dlt645_usb.py --poll --db` 通过 RS485 持续写库（或加
   `--poll-tcp` 让本服务内置采集）。
2. 启动服务并监听所有网卡（`0.0.0.0` 是默认值，热点网卡也会被监听）：

   ```sh
   python3 -m web --db /var/lib/meter.sqlite3 --host 0.0.0.0 --port 80
   ```

3. 开启热点（一键子命令，同参考实现）：

   ```sh
   sudo python3 scripts/hotspot.py
   ```

   手机连接板卡建立的 WIFI 热点后，在浏览器地址栏输入**板卡热点 IP**（AP 的
   网关地址，通常为 NetworkManager 共享连接的默认地址 `10.42.0.1`，可用
   `ip addr` 查看热点网卡地址确认），例如 `http://10.42.0.1`（端口 80 可省略）
   或 `http://10.42.0.1:8080`。

   > `127.0.0.1` 只是板卡自身的回环地址，仅用于板卡本机调试；手机走的是
   > 热点网络，必须用板卡在热点网络里的 IP。

4. 因前端完全自包含，热点内无需互联网即可正常显示图表。

## 测试

```sh
python3 -m unittest discover -s web/tests -v
python3 -m py_compile web/*.py
```

`test_poller.py` 会拉起 `host/dlt645_simulator.py` 做端到端联调，验证
`web` 复用 `host` 协议转换的完整链路。

## 许可证

同仓库根目录 [`LICENSE.txt`](../LICENSE.txt)。
