# bluetooth-link —— 加密通道工具（secure_link）

无网络蓝牙离线通讯工具升级版：**蓝牙 RFCOMM / TCP 双通道，文本与文件全加密**。

## 特性

- **双通道**：经典蓝牙 RFCOMM（无网离线，Linux + 蓝牙适配器）/ TCP（在线，局域网或公网中继）
- **全流量加密**：文本消息、文件头、文件数据块全部 AES-GCM（随机 nonce + 认证标签），防窃听、防篡改
- **随机盐握手**：每次连接由服务端生成随机盐，口令 + scrypt 派生会话密钥，同口令不同会话不同密钥
- **文件分块传输**：64KB 分块流式发送，大文件不撑爆内存；接收端校验大小完整性
- **错误密钥 / 篡改检测**：密钥不一致或数据被篡改时，接收端明确提示解密失败
- 纯 Python + cryptography，跨平台 TCP 可用

## 安装

```bash
pip install cryptography        # 必装
sudo apt install bluez          # 仅蓝牙通道需要（Linux）
```

## 用法

### 蓝牙（无网离线，两台 Linux + 蓝牙适配器）

```bash
# 服务端（等待连接）
python3 secure_link.py server --channel ble --port 10 --key 你的口令

# 客户端（发起连接）
python3 secure_link.py client --channel ble --mac <对方蓝牙MAC> --key 你的口令
```

### TCP（在线）

```bash
# 服务端
python3 secure_link.py server --channel tcp --port 9000 --key 你的口令

# 客户端
python3 secure_link.py client --channel tcp --host <对方IP> --port 9000 --key 你的口令
```

### 生成随机口令

```bash
python3 secure_link.py passwd
```

### 交互指令

| 指令 | 作用 |
|------|------|
| 直接输入文本 | 发送加密消息 |
| `/send <文件路径>` | 加密传输文件（对方自动存入 `received/`） |
| `/status` | 查看连接与加密状态 |
| `/name 名字` | 设置昵称 |
| `/quit` | 退出 |

## 协议帧（简要）

- 帧头：`SL` + 版本 + 类型 + 4 字节长度
- 类型：`Z` 握手盐（明文随机盐，不敏感） / `M` 加密文本 / `H` 加密文件头(JSON: 名称+大小) / `D` 加密文件块 / `E` 加密结束帧
- 加密载荷：`nonce(12B) + AES-GCM 密文 + tag(16B)`

## 测试

云端无蓝牙硬件，协议逻辑已用 TCP 双进程实测验证：

- 文本消息加密收发正常
- 1MB+ 文件分块传输正常，接收文件与源文件字节一致（SHA-256 校验）
- 错误口令被拦截，明确提示解密失败
- 语法检查通过（py_compile）

## 限制

- 经典蓝牙 RFCOMM，非 BLE；单连接（1 对 1）
- 蓝牙通道需要 Linux + 蓝牙硬件；TCP 通道任意联网环境可用
