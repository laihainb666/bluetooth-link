---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 7f40075f40fd472178ba0417306d8b11_0663da17a2c411f1bc17525400826444
    ReservedCode1: T1OzKzMh4zAELoHXHjKZxr/aQ9OUy/NZE/VZWAt+T7BzXZ17NLkZfXrGPDNJ99J+ysItNG1rlXqxJTU9ilFY0LCJCyzcJWwr5sJgwvOFeLxAeyT6KVFnMdBf1xAOqOxbwK/54/HVQPSD6keHD5VHUq4XevDt194JFUmotWFyw9rzHmCbs1sirki91Cw=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 7f40075f40fd472178ba0417306d8b11_0663da17a2c411f1bc17525400826444
    ReservedCode2: T1OzKzMh4zAELoHXHjKZxr/aQ9OUy/NZE/VZWAt+T7BzXZ17NLkZfXrGPDNJ99J+ysItNG1rlXqxJTU9ilFY0LCJCyzcJWwr5sJgwvOFeLxAeyT6KVFnMdBf1xAOqOxbwK/54/HVQPSD6keHD5VHUq4XevDt194JFUmotWFyw9rzHmCbs1sirki91Cw=
---

# bluetooth-link —— 加密通道工具（secure_link）

无网络蓝牙离线通讯工具升级版：**蓝牙 RFCOMM / TCP 双通道，文本与文件全加密**。
另有 **HTML 网页版**（secure_link.html）：浏览器点对点加密通讯，无需安装 Python。

## 特性

- **双通道**：经典蓝牙 RFCOMM（无网离线，Linux + 蓝牙适配器）/ TCP（在线，局域网或公网中继）
- **全流量加密**：文本消息、文件头、文件数据块全部 AES-GCM（随机 nonce + 认证标签），防窃听、防篡改
- **随机盐握手**：每次连接由服务端生成随机盐，口令 + scrypt 派生会话密钥，同口令不同会话不同密钥
- **文件分块传输**：64KB 分块流式发送，大文件不撑爆内存；接收端校验大小完整性
- **错误密钥 / 篡改检测**：密钥不一致或数据被篡改时，接收端明确提示解密失败
- 纯 Python + cryptography，跨平台 TCP 可用

## HTML 网页版（secure_link.html）v2

双击用 Chrome/Edge 打开即可，无需安装任何东西。单文件，可离线使用。

**千里之外也能对话（跨公网）**：
- 内置默认 STUN（stun.l.google.com）自动 NAT 打洞，多数家庭/办公网络可点对点直连，人在异地也能互相聊天传文件
- 打洞失败（严格 NAT / 防火墙）时，可填 **TURN 中继服务器**兜底：`turn:用户:密码@主机:端口`（可用自建 coturn 或第三方中继），经中继转发照样互通
- 信令仍走手动交换（微信/QQ 复制文本或扫码），无需自建信令服务器

**超大型文件传输**：
- 1MB 分块 + 16MB 发送背压控制，不卡死不丢块
- 接收端优先使用 **File System Access API 流式写入磁盘**（Chrome/Edge），内存占用恒定，数十 GB 大文件也能传；不支持时自动回退内存 Blob 方案
- 实时进度条 + 传输速率（MB/s）显示

**实用体验增强**：
- 三步引导界面：设置口令 → 交换信令 → 加密通讯，逐步解锁
- 信令一键复制 + **二维码展示**（对方手机扫码即可获取信令）
- 对方信令粘贴后**自动处理**（接收方自动应答、发起方自动应用），少点两步
- 支持拖拽文件发送、一次选择多个文件排队传输
- 消息带时间戳，连接/ICE 失败给出明确提示

**加密**：口令 + PBKDF2(12万次迭代) 派生 AES-256-GCM 会话密钥，盐随信令交换，每次会话不同；文本、文件头、文件数据块全加密，口令错误或数据被篡改时提示解密失败。

**流程**：
1. 双方输入相同口令（可选填 TURN）
2. 发起方点“我是发起方：创建连接”→ 复制信令或扫码发给对方
3. 对方粘贴信令 → 自动生成应答 → 把应答发回
4. 发起方粘贴应答 → 自动建立通道，开始聊天/传文件

**适用浏览器**：Chrome / Edge 最新版（完整支持流式落盘与 WebRTC）。

## 安装（Python 版）

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
*（内容由AI生成，仅供参考）*
