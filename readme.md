# DL/T 645 Python 解析与采集工具

用于解析和采集 DL/T 645 电表数据的纯 Python 工具集，支持 DL/T 645-1997 与 DL/T 645-2007。

不依赖第三方 Python 包，要求 Python 3.8 或更高版本。

## 功能

- 解析任意分片的串口或 TCP 字节流
- 处理噪声、连续帧、校验和与可选 `FE` 前导码
- 构造读数据和 2007 通信地址查询请求
- 解析常用电能、电压、电流、功率、功率因数和频率
- 从 USB-RS485 适配器读取并以 JSON Lines 输出
- 支持轮询、SQLite 持久化和确定性 TCP 模拟电表

## 项目结构

```text
host/
  dlt645_converter.py   协议帧构造、流式解码与数据转换
  dlt645_usb.py         USB 串口和 TCP 命令行工具
  dlt645_database.py    SQLite 存储
  dlt645_simulator.py   TCP 模拟电表
  test_*.py             单元测试
```

## 离线解析

不连接设备，直接检查并解析一帧十六进制报文：

```sh
python3 host/dlt645_usb.py --version 2007 --hex '68 ... 16'
```

输出为一行 JSON，包含协议版本、电表地址、数据标识、原始数据、转换后的值和单位。

## 在 Python 中使用

将 `host/` 加入模块搜索路径后，可直接使用协议转换函数：

```python
from dlt645_converter import decode_chunks

chunks = [
    bytes.fromhex("FE FE 68 12 90 78 56 34 12 68 91 06 33 34 34 35 38 56 7B 16"),
]

for reading in decode_chunks(chunks, version="2007"):
    print(reading["address"])          # 123456789012
    print(reading["data_identifier"])  # 0x02010100
    print(reading["value"])            # 230.5
    print(reading["unit"])             # V
```

对串口或 socket 的每个读取块调用 `FrameDecoder.feed(chunk)`；该解码器会在数据到齐时返回已校验的帧。

## USB-RS485 采集

USB-TTL 不能直接接入 RS485 电表，请使用 USB-RS485 适配器或 TTL-RS485 收发器。设备名通常为 Linux 的 `/dev/ttyUSB0`、`/dev/ttyACM0`，或 macOS 的 `/dev/cu.usbserial-*`。

被动监听：

```sh
python3 host/dlt645_usb.py \
  --port /dev/ttyUSB0 --baud 2400 --parity even --version 2007
```

主动读取 A 相电压：

```sh
python3 host/dlt645_usb.py \
  --port /dev/ttyUSB0 --baud 2400 --parity even --version 2007 \
  --addr 123456789012 --code 0x02010100
```

地址以铭牌上的 12 位十六进制格式传入；程序会自动转换为协议线路顺序。添加 `--debug` 可将收发原始字节输出到标准错误。

## 轮询和 SQLite

```sh
python3 host/dlt645_usb.py \
  --port /dev/ttyUSB0 --baud 2400 --parity even --version 2007 \
  --addr 123456789012 --poll --interval 5 \
  --db meter_readings.sqlite3
```

默认读取常用电能与实时电气量。使用 `--all` 读取本地目录中全部已启用的标识符，使用 `--list-codes` 查看目录。结果会追加到 SQLite 的 `meter_readings` 表。

## 查询电表地址

只连接一台 DL/T 645-2007 电表时：

```sh
python3 host/dlt645_usb.py \
  --port /dev/ttyUSB0 --baud 2400 --parity even --version 2007 \
  --discover-address --timeout 3 --debug
```

多台电表会同时响应广播请求并造成总线冲突，因此不能在多表总线上运行该命令。

## 无硬件测试

终端一启动模拟器：

```sh
python3 host/dlt645_simulator.py --host 127.0.0.1 --port 8899 --version 2007
```

终端二发起读取：

```sh
python3 host/dlt645_usb.py --tcp 127.0.0.1:8899 \
  --version 2007 --addr 123456789012 --code 0x02010100
```

模拟器返回确定性的 A 相电压 `230.5 V`。

## 测试

```sh
python3 -m unittest discover -s host -v
python3 -m py_compile host/*.py
```

## 常见参数

- `--preamble 0`：不在请求前发送默认的 4 个 `FE` 前导字节。
- `--timeout 3`：将响应超时设置为 3 秒。
- `--version 1997`：选择 DL/T 645-1997 数据标识和解析规则。

详细命令行参数和 SQLite 字段见 [`host/README.md`](host/README.md)。

## 许可证

详见 [`LICENSE.txt`](LICENSE.txt)。
