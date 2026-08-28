#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bluetooth-link —— 无网络蓝牙离线通讯工具
==========================================
复刻自 GitHub 项目思路（Kabootar / Chat-app-using-Bluetooth / PhoneLink）：
一台 Linux 电脑作为服务端，另一台设备（同样运行本脚本或支持 RFCOMM 的设备）
通过蓝牙 RFCOMM 直接点对点通讯：文本消息 + 文件传输，全程无需互联网/服务器/SIM。

依赖：仅 Python 3 标准库（socket.AF_BLUETOOTH），需要系统安装 bluez 且有蓝牙适配器。
用法：
    服务端（等待连接）：python3 bluetooth_link.py server [端口=10] [蓝牙适配器地址]
    客户端（发起连接）：python3 bluetooth_link.py client <对方蓝牙MAC> [端口=10]

交互指令：
    直接输入文本并回车        -> 发送消息
    /send <文件路径>          -> 发送文件（对方自动保存到接收目录）
    /status                   -> 查看连接状态
    /quit                     -> 退出
"""

import os
import socket
import sys
import threading
import time

PROTO = b"BL"          # 协议魔数
VERSION = 1
TYPE_MSG = b"M"         # 文本消息
TYPE_FILE = b"F"        # 文件传输
DEFAULT_PORT = 10       # 经典蓝牙 RFCOMM 常用 channel


def ensure_bluetooth_supported():
    """检查当前平台是否支持 AF_BLUETOOTH"""
    if not hasattr(socket, "AF_BLUETOOTH"):
        sys.exit("当前系统不支持 AF_BLUETOOTH（需要 Linux + bluez），无法运行。")


def get_adapter_addr():
    """获取本机蓝牙适配器地址，缺省用 hci0"""
    try:
        import subprocess
        out = subprocess.check_output(["hciconfig", "-a"], text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            line = line.strip()
            if "BD Address:" in line:
                return line.split("BD Address:")[1].split()[0].strip()
    except Exception:
        pass
    return "00:00:00:00:00:00"


def recv_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("连接已断开")
        buf += chunk
    return buf


def recv_frame(conn):
    """接收一帧：魔数(2) + 版本(1) + 类型(1) + 长度(4) + 内容"""
    head = recv_exact(conn, 8)
    if head[:2] != PROTO:
        raise ValueError("协议魔数不匹配，对方可能不是 bluetooth-link")
    ftype = head[3:4]
    length = int.from_bytes(head[4:8], "big")
    payload = recv_exact(conn, length)
    return ftype, payload


def send_frame(sock, ftype, payload):
    head = PROTO + bytes([VERSION]) + ftype + len(payload).to_bytes(4, "big")
    sock.sendall(head + payload)


def recv_loop(conn, save_dir, role):
    """后台线程：持续接收消息/文件"""
    while True:
        try:
            ftype, payload = recv_frame(conn)
        except Exception as e:
            print(f"\n[!] 接收结束：{e}")
            break
        if ftype == TYPE_MSG:
            try:
                text = payload.decode("utf-8", errors="replace")
            except Exception:
                text = repr(payload)
            print(f"\n[对方消息] {text}\n> ", end="", flush=True)
        elif ftype == TYPE_FILE:
            # payload = 文件名(utf-8) + b'\n' + 文件内容
            try:
                sep = payload.index(b"\n")
                fname = payload[:sep].decode("utf-8", errors="replace")
                fdata = payload[sep + 1:]
            except ValueError:
                fname = f"received_{int(time.time())}.bin"
                fdata = payload
            fname = os.path.basename(fname)
            os.makedirs(save_dir, exist_ok=True)
            fpath = os.path.join(save_dir, fname)
            with open(fpath, "wb") as f:
                f.write(fdata)
            print(f"\n[收到文件] {fname} ({len(fdata)} 字节) -> {fpath}\n> ", end="", flush=True)
        else:
            print(f"\n[未知类型] {ftype!r}\n> ", end="", flush=True)


def send_file(sock, path):
    if not os.path.isfile(path):
        print(f"[!] 文件不存在：{path}")
        return
    with open(path, "rb") as f:
        data = f.read()
    payload = os.path.basename(path).encode("utf-8") + b"\n" + data
    send_frame(sock, TYPE_FILE, payload)
    print(f"[已发送文件] {path} ({len(data)} 字节)")


def cli_loop(sock):
    """主线程：读取用户输入并发送"""
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
            print(f"[连接状态] 已建立：{sock.getpeername()}")
        elif line.startswith("/send "):
            send_file(sock, line[6:].strip())
        elif line.startswith("/"):
            print("[!] 未知指令，支持：/send <文件>  /status  /quit")
        else:
            send_frame(sock, TYPE_MSG, line.encode("utf-8"))


def run_server(port, adapter):
    ensure_bluetooth_supported()
    if not adapter or adapter.startswith("00:00"):
        adapter = get_adapter_addr()
        print(f"[提示] 未指定适配器，自动探测：{adapter}")
        if adapter.startswith("00:00"):
            print("[警告] 未检测到蓝牙适配器，若设备无蓝牙将无法工作。")

    server = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    server.bind((adapter, port))
    server.listen(1)
    print(f"[服务端] 蓝牙地址 {adapter} 端口 {port}，等待连接...（Ctrl+C 退出）")

    conn, addr = server.accept()
    print(f"[已连接] {addr}")

    save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "received")
    t = threading.Thread(target=recv_loop, args=(conn, save_dir, "server"), daemon=True)
    t.start()
    cli_loop(conn)
    try:
        conn.close()
    except Exception:
        pass
    server.close()


def run_client(target, port):
    ensure_bluetooth_supported()
    print(f"[客户端] 连接 {target}:{port} ...")
    sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    try:
        sock.connect((target, port))
    except Exception as e:
        sys.exit(f"[!] 连接失败：{e}（请确认对方已运行 server 且蓝牙可见）")
    print("[已连接] 输入文本发送；/send <文件> 发文件；/quit 退出")

    save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "received")
    t = threading.Thread(target=recv_loop, args=(sock, save_dir, "client"), daemon=True)
    t.start()
    cli_loop(sock)
    try:
        sock.close()
    except Exception:
        pass


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    mode = sys.argv[1].lower()
    if mode == "server":
        port = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PORT
        adapter = sys.argv[3] if len(sys.argv) > 3 else ""
        run_server(port, adapter)
    elif mode == "client":
        if len(sys.argv) < 3:
            sys.exit("用法：python3 bluetooth_link.py client <对方蓝牙MAC> [端口]")
        target = sys.argv[2]
        port = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_PORT
        run_client(target, port)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
