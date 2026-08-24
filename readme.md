# DL/T 645 电表采集工具包

这是一个面向嵌入式和桌面主机的 DL/T 645 电表通信工具包，支持
DL/T 645-1997 与 DL/T 645-2007 的数据读取、报文编解码和常用数据标识解析。

项目包含两部分：

- `src/`、`inc/`、`port/`：可移植的 C 协议核心，适合 RT-Thread 或其他裸机/RTOS 工程。
- `host/`：无需 RT-Thread 的 Python 主机工具，可通过 USB-RS485 适配器或 TCP 模拟器采集数据。

## 功能

- 支持 DL/T 645-1997、DL/T 645-2007 读数据请求和响应解析
- 支持电表地址反序、数据标识、校验和、`FE` 前导码处理
- 支持常用电压、电流、有功功率、功率因数、频率和电能等数据转换
- 主机工具以 JSON Lines 输出结果，可选 SQLite 持久化
- 提供离线报文校验、地址发现、轮询采集和 TCP 软件电表模拟器
- 不依赖第三方 Python 包；主机工具需要 Python 3.8 或更高版本

目前只实现读数据路径，暂不包含参数设置、费率配置等写操作。

## 快速开始：嵌入式 C

### 1. 添加源码

将以下目录加入工程：

```text
inc/       头文件
src/       协议核心
port/      串口/RS485 移植参考
sample/    RT-Thread 示例
```

`src/` 中的文件都需要参与编译。 `port/` 中的示例依赖 RT-Thread，不能直接作为所有平台的通用驱动。

### 2. 提供底层读写接口

协议核心通过 `dlt645_t` 调用平台相关的发送和接收函数：

```c
typedef struct dlt645 {
    uint8_t addr[6];
    uint8_t debug;
    int (*write)(struct dlt645 *ctx, uint8_t *buf, uint16_t len);
    int (*read)(struct dlt645 *ctx, uint8_t *msg, uint16_t len);
    void *port_data;
} dlt645_t;
```

`write` 应返回实际发送的字节数；`read` 应返回实际接收的字节数，超时或数据不完整时返回 `0`。RS485 半双工方向控制、串口波特率、校验位和超时策略由移植层负责。

### 3. 设置地址并读取数据

```c
#include "dlt645.h"

static dlt645_t meter;
static uint8_t meter_addr[6] = {0x12, 0x34, 0x56, 0x78, 0x90, 0x12};
static uint8_t value[4];

dlt645_set_addr(&meter, meter_addr);

if (dlt645_read_data(&meter, 0x02010100, value, DLT645_2007) > 0) {
    /* 2007 标识符 0x02010100：A 相电压，结果按 float 保存。 */
    float voltage = *(float *)value;
}
```

地址数组使用协议的 6 字节顺序。完整的 RT-Thread 串口移植示例见
[`port/dlt645_port.c`](port/dlt645_port.c) 和 [`sample/dlt645_sample.c`](sample/dlt645_sample.c)。

## 快速开始：主机 USB-RS485

USB-TTL 不能直接连接电表，必须使用 USB-RS485 适配器或 TTL-RS485 收发器。先确认设备名，例如 Linux 的 `/dev/ttyUSB0` 或 macOS 的 `/dev/cu.usbserial-*`。

被动监听并解码收到的报文：

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

每个结果占一行 JSON。地址使用电表铭牌上的 12 位十六进制字符串，程序会自动转换为协议要求的线路顺序。

### 轮询并保存 SQLite

```sh
python3 host/dlt645_usb.py \
  --port /dev/ttyUSB0 --baud 2400 --parity even --version 2007 \
  --addr 123456789012 --poll --interval 5 \
  --db meter_readings.sqlite3
```

默认轮询常用电能和实时电气量。使用 `--all` 查询本地目录中的全部已启用标识符；使用 `--list-codes` 查看目录。SQLite 表名为 `meter_readings`，临时数据库文件已被 `.gitignore` 排除。

### 地址发现

只连接一台电表时，可以使用 DL/T 645-2007 的广播地址请求查询通信地址：

```sh
python3 host/dlt645_usb.py \
  --port /dev/ttyUSB0 --baud 2400 --parity even --version 2007 \
  --discover-address --timeout 3 --debug
```

多个电表同时在线会产生响应冲突，不要在多表总线上执行地址发现。

更多参数、数据表字段和接线说明见 [`host/README.md`](host/README.md)。

## 无硬件测试

终端一启动确定性 TCP 模拟电表：

```sh
python3 host/dlt645_simulator.py --host 127.0.0.1 --port 8899 --version 2007
```

终端二发送读取请求：

```sh
python3 host/dlt645_usb.py --tcp 127.0.0.1:8899 \
  --version 2007 --addr 123456789012 --code 0x02010100
```

模拟器会返回确定性的 `230.5 V` A 相电压响应，可用于验证请求、拆包、校验和数据转换链路。

也可以直接离线解析十六进制报文：

```sh
python3 host/dlt645_usb.py --version 2007 --hex '68 ... 16'
```

## 测试

```sh
python3 -m unittest discover -s host -v
python3 -m py_compile host/*.py
```

测试覆盖地址和标识编码、分片报文、前导码、校验失败、1997/2007 数据转换及 SQLite 写入。

## 目录结构

```text
inc/       C 头文件
src/       DL/T 645-1997/2007 协议核心
port/      串口和 RS485 移植参考
sample/    RT-Thread 使用示例
host/      Python 主机工具、模拟器和测试
docs/      项目资源
```

## 注意事项

- 电表的波特率、校验位和停止位必须与适配器配置一致；很多电表使用 `2400 8E1`。
- `FE` 前导码长度由电表和适配器决定，主机工具默认发送 4 个 `FE`，可用 `--preamble 0` 调整。
- 读写接口的超时和接收边界应在移植层正确处理，避免把多帧数据或半帧数据交给协议核心。

## 许可证

项目沿用原仓库许可证，详见 [`LICENSE.txt`](LICENSE.txt)。
