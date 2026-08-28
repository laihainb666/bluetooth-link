#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
secure_link —— 蓝牙/TCP 加密通道工具（文本 + 文件全加密）
=============================================================
bluetooth-link 的加密通道升级版：
- 双通道：经典蓝牙 RFCOMM（无网离线）/ TCP（在线）
- 全流量加密：文本消息、文件头、文件数据块均 AES-GCM（随机 nonce + 认证标签）
- 每次连接随机盐握手：口令 + scrypt 派生会话密钥，同口令不同会话密钥不同
- 文件分块流式传输：大文件安全可靠，断线不撑爆内存
- 防篡改：任何密文被改动都会在接收端解密失败并明确提示

依赖：cryptography（pip 安装）；蓝牙通道另需 Linux + bluez

用法：
  # 蓝牙（无网离线，Linux + 蓝牙适配器）
  python3 secure_link.py server --channel ble --port 10 --key 口令
  python3 secure_link.py client --channel ble --mac <对方蓝牙MAC> --key 口令

  # TCP（在线）
  python3 secure_link.py server --channel tcp --port 9000 --key 口令
  python3 secure_link.py client --channel tcp --host <对方IP> --port 9000 --key 口令

  # 生成随机口令
  python3 secure_link.py passwd

交互指令：
  直接输入文本回车   -> 发送加密消息
  /send <文件路径>   -> 加密传输文件（对方自动存入 received/）
  /status            -> 连接与加密状态
  /name 名字         -> 设置昵称
  /quit              -> 退出
"""

import argparse
import getpass
import hashlib
import json
import os
import socket
import sys
import threading
import time

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    CRYPTO_OK = True
except ImportError:
    CRYPTO_OK = False

PROTO = b"SL"        # 协议魔数
VER = 1
T_MSG = b"M"         # 加密文本消息
T_HDR = b"H"         # 加密文件头
T_DATA = b"D"        # 加密文件数据块
T_END = b"E"         # 加密文件结束
T_HI = b"Z"          # 明文握手：随机盐

DEFAULT_BLE_PORT = 10
DEFAULT_TCP_PORT = 9000
CHUNK = 64 * 1024    # 文件分块 64KB
SALT_LEN = 16
HDR_LEN = 8          # 魔数2 + 版本1 + 类型1 + 长度4


def ensure_crypto():
    if not CRYPTO_OK:
        sys.exit("[!] 需要 cryptography：python3 -m pip install cryptography")


def derive_key(password: bytes, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(password)


def encrypt(plain: bytes, key: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, plain, None)


def decrypt(blob: bytes, key: bytes) -> bytes:
    nonce, ct = blob[:12], blob[12:]
    return AESGCM(key).decrypt(nonce, ct, None)


# ---------------------------------------------------------------- 帧协议

def recv_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("连接已断开")
        buf += chunk
    return buf


def recv_frame(conn):
    head = recv_exact(conn, HDR_LEN)
    if head[:2] != PROTO:
        raise ValueError("协议魔数不匹配，对方可能不是 secure_link")
    ftype = head[3:4]
    length = int.from_bytes(head[4:8], "big")
    if length < 0 or length > 512 * 1024 * 1024:
        raise ValueError("非法帧长度")
    return ftype, recv_exact(conn, length)


def send_frame(sock, ftype, payload):
    head = PROTO + bytes([VER]) + ftype + len(payload).to_bytes(4, "big")
    sock.sendall(head + payload)


# ---------------------------------------------------------------- 会话

class Session:
    def __init__(self, sock, key, nickname, is_server):
        self.sock = sock
        self.key = key
        self.nickname = nickname
        self.is_server = is_server
        self.lock = threading.Lock()
        self.peer = "?"
        try:
            self.peer = str(sock.getpeername())
        except Exception:
            pass
        self.save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "received")

    # --- 发送 ---
    def send_text(self, text: str):
        with self.lock:
            send_frame(self.sock, T_MSG, encrypt(text.encode("utf-8"), self.key))

    def send_file(self, path: str):
        if not os.path.isfile(path):
            print(f"[!] 文件不存在：{path}")
            return
        size = os.path.getsize(path)
        name = os.path.basename(path)
        hdr = json.dumps({"n": name, "s": size}).encode("utf-8")
        with self.lock:
            send_frame(self.sock, T_HDR, encrypt(hdr, self.key))
            with open(path, "rb") as f:
                while True:
                    blk = f.read(CHUNK)
                    if not blk:
                        break
                    send_frame(self.sock, T_DATA, encrypt(blk, self.key))
            send_frame(self.sock, T_END, encrypt(b"ok", self.key))
        print(f"[已加密发送文件] {name} ({size} 字节)")

    # --- 接收 ---
    def _on_file(self, hdr_payload):
        """接收文件：H(已收) -> D* -> E"""
        try:
            hdr = json.loads(decrypt(hdr_payload, self.key).decode("utf-8"))
            fname = os.path.basename(hdr.get("n", "file.bin"))
            fsize = int(hdr.get("s", 0))
        except Exception:
            print("\n[!] 文件头解密失败（密钥不一致或数据被篡改）\n> ", end="", flush=True)
            return
        os.makedirs(self.save_dir, exist_ok=True)
        fpath = os.path.join(self.save_dir, fname)
        got = 0
        with open(fpath, "wb") as f:
            while True:
                ftype, payload = recv_frame(self.sock)
                if ftype == T_END:
                    try:
                        decrypt(payload, self.key)
                    except Exception:
                        print("\n[!] 文件结束帧校验失败")
                    break
                if ftype != T_DATA:
                    raise ValueError("文件传输中收到异常帧")
                try:
                    blk = decrypt(payload, self.key)
                except Exception:
                    raise ValueError("文件数据块解密失败（密钥不一致或数据被篡改）")
                f.write(blk)
                got += len(blk)
        ok = (got == fsize)
        print(f"\n[收到加密文件] {fname} ({got} 字节) -> {fpath}{' [完整]' if ok else ' [大小不符!]'}\n> ", end="", flush=True)
        return True

    def read_loop(self):
        while True:
            try:
                ftype, payload = recv_frame(self.sock)
            except Exception as e:
                print(f"\n[!] 接收结束：{e}")
                break
            try:
                if ftype == T_MSG:
                    text = decrypt(payload, self.key).decode("utf-8", "replace")
                    print(f"\n[对方消息] {text}\n> ", end="", flush=True)
                elif ftype == T_HDR:
                    try:
                        self._on_file(payload)
                    except Exception as e:
                        print(f"\n[!] 文件接收失败：{e}\n> ", end="", flush=True)
                elif ftype == T_HI:
                    # 握手盐不应出现在加密会话中，忽略
                    continue
                else:
                    print(f"\n[未知帧] {ftype!r}\n> ", end="", flush=True)
            except Exception as e:
                print(f"\n[!] 消息解密失败（密钥不一致或数据被篡改）：{e}\n> ", end="", flush=True)

    def cli_loop(self):
        print(f"[加密通道已建立] 对端 {self.peer} · AES-GCM · 文本/文件全加密")
        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n[退出]")
                break
            if not line:
                continue
            if line == "/quit":
                print("[退出]")
                break
            elif line == "/status":
                print(f"[状态] 对端 {self.peer} · 加密 AES-256-GCM · 昵称 {self.nickname}")
            elif line == "/name " or line.startswith("/name "):
                self.nickname = line.split(" ", 1)[1].strip() if " " in line else self.nickname
                print(f"[昵称已设为 {self.nickname}]")
            elif line.startswith("/send "):
                self.send_file(line[6:].strip())
            elif line.startswith("/"):
                print("[!] 指令：/send <文件>  /status  /name 名字  /quit")
            else:
                self.send_text(f"{self.nickname}: {line}")

    def run(self):
        threading.Thread(target=self.read_loop, daemon=True).start()
        self.cli_loop()
        try:
            self.sock.close()
        except Exception:
            pass


# ---------------------------------------------------------------- 握手：随机盐交换

def handshake_server(conn):
    """服务端生成随机盐并发送（盐明文不敏感），随后派生会话密钥"""
    salt = os.urandom(SALT_LEN)
    send_frame(conn, T_HI, salt)
    return salt


def handshake_client(conn):
    ftype, payload = recv_frame(conn)
    if ftype != T_HI:
        raise ValueError("对方未按 secure_link 握手协议响应")
    if len(payload) != SALT_LEN:
        raise ValueError("握手盐长度异常")
    return payload


# ---------------------------------------------------------------- 通道

def ble_listen(port, adapter, password):
    if not hasattr(socket, "AF_BLUETOOTH"):
        sys.exit("[!] 当前系统不支持 AF_BLUETOOTH（需要 Linux + bluez）")
    if not adapter or adapter.startswith("00:00"):
        adapter = "00:00:00:00:00:00"
        try:
            import subprocess
            out = subprocess.check_output(["hciconfig", "-a"], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                if "BD Address:" in line:
                    adapter = line.split("BD Address:")[1].split()[0].strip()
                    break
        except Exception:
            pass
    srv = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    srv.bind((adapter, port))
    srv.listen(1)
    print(f"[蓝牙服务端] 地址 {adapter} 端口 {port}，等待连接…")
    conn, addr = srv.accept()
    print(f"[已连接] {addr}")
    salt = handshake_server(conn)
    key = derive_key(password.encode("utf-8"), salt)
    Session(conn, key, "server", True).run()
    srv.close()


def ble_chat(mac, port, password):
    if not hasattr(socket, "AF_BLUETOOTH"):
        sys.exit("[!] 当前系统不支持 AF_BLUETOOTH（需要 Linux + bluez）")
    print(f"[蓝牙客户端] 连接 {mac}:{port} …")
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    try:
        s.connect((mac, port))
    except OSError as e:
        sys.exit(f"[!] 蓝牙连接失败：{e}")
    print("[已连接]")
    salt = handshake_client(s)
    key = derive_key(password.encode("utf-8"), salt)
    Session(s, key, "client", False).run()


def tcp_listen(port, password):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", port))
    srv.listen(1)
    print(f"[TCP 服务端] 0.0.0.0:{port}，等待连接…（对端：secure_link.py client --host <本机IP> --port {port} --key 同一口令）")
    conn, addr = srv.accept()
    print(f"[已连接] {addr}")
    salt = handshake_server(conn)
    key = derive_key(password.encode("utf-8"), salt)
    Session(conn, key, "server", True).run()
    srv.close()


def tcp_chat(host, port, password):
    print(f"[TCP 客户端] 连接 {host}:{port} …")
    try:
        s = socket.create_connection((host, port), timeout=15)
    except OSError as e:
        sys.exit(f"[!] 连接失败：{e}")
    print("[已连接]")
    salt = handshake_client(s)
    key = derive_key(password.encode("utf-8"), salt)
    Session(s, key, "client", False).run()


# ---------------------------------------------------------------- 入口

def main():
    ensure_crypto()
    p = argparse.ArgumentParser(description="secure_link 蓝牙/TCP 加密通道工具（AES-GCM，文本+文件全加密）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("server", help="服务端：监听等待连接")
    sp.add_argument("--channel", choices=["ble", "tcp"], default="tcp")
    sp.add_argument("--port", type=int, default=None)
    sp.add_argument("--adapter", default="", help="蓝牙适配器地址（默认自动探测）")
    sp.add_argument("--key", default=None, help="口令（不传则交互输入）")

    sp = sub.add_parser("client", help="客户端：主动连接")
    sp.add_argument("--channel", choices=["ble", "tcp"], default="tcp")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=None)
    sp.add_argument("--mac", default=None, help="蓝牙模式：对方蓝牙 MAC")
    sp.add_argument("--key", default=None, help="口令（不传则交互输入）")

    sp = sub.add_parser("passwd", help="生成随机口令")
    sp.set_defaults(cmd="passwd")

    args = p.parse_args()

    if args.cmd == "passwd":
        print("建议口令：" + hashlib.sha256(os.urandom(32)).hexdigest()[:24])
        return

    key = args.key if args.key else getpass.getpass("口令（两端必须一致）: ")
    if not key:
        sys.exit("[!] 口令不能为空")

    if args.cmd == "server":
        port = args.port if args.port is not None else (DEFAULT_BLE_PORT if args.channel == "ble" else DEFAULT_TCP_PORT)
        if args.channel == "ble":
            ble_listen(port, args.adapter, key)
        else:
            tcp_listen(port, key)
    else:
        port = args.port if args.port is not None else (DEFAULT_BLE_PORT if args.channel == "ble" else DEFAULT_TCP_PORT)
        if args.channel == "ble":
            if not args.mac:
                sys.exit("[!] 蓝牙模式需要 --mac <对方蓝牙MAC>")
            ble_chat(args.mac, port, key)
        else:
            tcp_chat(args.host, port, key)


if __name__ == "__main__":
    main()
