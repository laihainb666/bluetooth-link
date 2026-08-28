---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 7f40075f40fd472178ba0417306d8b11_c2b3c8f3a28b11f1abe1525400e6dd8f
    ReservedCode1: CiYCOt9imzJcTbPVuKHtbfwfFsO615ttIreUwp/uQP6jl20/7gaNnpRpzEuujQzF5iOPzTpNU/pvE8jlSFRDc3wqyYYQAn5JqfwRKBTOQyaKtqr87efcQFSOYy4+LyaD9yZMHyeY1ECHZmBoKlnHTH1GUNpxne3alNGclwSiKKAaXKB3/12BLcBTdhQ=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 7f40075f40fd472178ba0417306d8b11_c2b3c8f3a28b11f1abe1525400e6dd8f
    ReservedCode2: CiYCOt9imzJcTbPVuKHtbfwfFsO615ttIreUwp/uQP6jl20/7gaNnpRpzEuujQzF5iOPzTpNU/pvE8jlSFRDc3wqyYYQAn5JqfwRKBTOQyaKtqr87efcQFSOYy4+LyaD9yZMHyeY1ECHZmBoKlnHTH1GUNpxne3alNGclwSiKKAaXKB3/12BLcBTdhQ=
---



# bluetooth-link

无网络蓝牙离线通讯工具（纯 Python 标准库复刻）。

参考 GitHub 开源思路（Kabootar / Chat-app-using-Bluetooth / PhoneLink）：两台 Linux 设备通过蓝牙 RFCOMM 点对点直连，支持文本消息与文件传输，全程不依赖互联网、服务器或 SIM 卡。

## 特性

- 纯标准库实现：`socket.AF_BLUETOOTH` + `BTPROTO_RFCOMM`
- 自定义帧协议：魔数 `BL` + 版本 + 类型（文本/文件）+ 长度头
- 文本消息即时收发（UTF-8）
- 文件传输：`文件名 + 内容` 单帧发送，接收端自动存入 `received/`
- 命令行交互：`/send <文件>`、`/status`、`/quit`

## 加密通道对话（encrypt_chat.py）

有网络 / 无网络都能用的 AES-GCM 加密点对点对话：

- **在线（TCP）**：局域网或公网中继，`--channel tcp`
- **离线（蓝牙）**：Linux 蓝牙 RFCOMM 直连，`--channel ble`，不依赖网络
- 口令经 scrypt 派生 256-bit 密钥，每条消息随机 nonce + 认证标签，防窃听防篡改
- 消息帧：`BLCHAT|1|nonce+密文+tag`（十六进制）

```bash
# 依赖
python3 -m pip install cryptography

# 在线模式
python3 encrypt_chat.py listen --port 9000 --key 你的口令
python3 encrypt_chat.py chat   --host <对方IP> --port 9000 --key 你的口令

# 离线蓝牙模式（双方 Linux + 蓝牙）
python3 encrypt_chat.py listen --channel ble --key 你的口令
python3 encrypt_chat.py chat   --channel ble --mac <对方蓝牙MAC> --key 你的口令

# 生成随机口令
python3 encrypt_chat.py passwd
```

输入消息回车发送，`/quit` 退出，`/name 名字` 改昵称。

## 依赖

- Linux + bluez（蓝牙协议栈）
- 带蓝牙适配器的设备（如树莓派、笔记本）

```bash
sudo apt install bluez
```

## 用法

服务端（等待连接）：

```bash
python3 bluetooth_link.py server [端口=10] [蓝牙适配器地址]
```

客户端（发起连接）：

```bash
python3 bluetooth_link.py client <对方蓝牙MAC> [端口=10]
```

连接建立后直接输入文本发送；`/send 文件路径` 发送文件；`/quit` 退出。

## 测试

云端无蓝牙硬件，协议逻辑已用 TCP socketpair 模拟验证：

- 语法检查通过（py_compile）
- 文本消息帧收发正常
- 文件帧收发正常，接收端文件与源文件字节一致
- encrypt_chat 加解密/篡改拦截/错误密钥拒绝/TCP 双向收发均通过实测

## 限制

- 经典蓝牙 RFCOMM，非 BLE
- 单连接（1 对 1）
- encrypt_chat 蓝牙通道需要 Linux + 蓝牙硬件；TCP 通道可在任意联网环境使用
*（内容由AI生成，仅供参考）*
*（内容由AI生成，仅供参考）*
