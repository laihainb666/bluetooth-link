#!/usr/bin/env python3
"""SecureLink 信令服务器：房间管理 + 信令转发 + 随机匹配 + 私密房

用途：配合 secure_link_v2.html 的「服务器房间模式」使用。
- 群聊：多人同房，浏览器间 mesh 直连加密通讯
- 随机匹配：点击「随机匹配」自动加入一个公开房间
- 私密房：房主开启后，房间从公开列表隐藏、随机匹配不会进入

部署（任意有公网 IP 的 VPS / 云服务器）：
    pip install websockets
    python3 server.py --port 8765
    # 开放防火墙对应端口（TCP）
HTML 端填写: ws://你的IP:8765  （有域名+证书可用 wss://）

注意：本服务器只转发 WebRTC 信令（SDP/ICE），不接触任何聊天内容和文件数据；
所有流量均为浏览器间端到端 AES-256-GCM 加密，服务器无法解密。
"""
import argparse
import asyncio
import json
import random
import string

try:
    import websockets
except ImportError:
    raise SystemExit("缺少依赖：pip install websockets")

rooms = {}          # room_id -> Room
id_map = {}         # 永久ID -> {"ws":..., "name":...}（ID 直连用）
MAX_MEMBERS = 8     # mesh 拓扑上限（人数过多建议开第二个房间）


class Room:
    def __init__(self, rid, name, password, host_id, host_name, ws, salt):
        self.id = rid
        self.name = name or ("房间" + rid)
        self.password = password or ""      # 私密密码（空=公开房）
        self.salt = salt                    # 加密盐，随 join 广播给成员
        self.private = bool(password)       # 有密码即为私密房
        self.members = {}                   # ws_id -> {"name":..., "ws":...}
        self.members[host_id] = {"name": host_name, "ws": ws}

    def host_id(self):
        return next(iter(self.members))

    def is_host(self, wid):
        return wid == self.host_id()


def rid4():
    while True:
        r = "".join(random.choices(string.digits, k=4))
        if r not in rooms:
            return r


def ws_alive(ws):
    """websockets 版本兼容：判断连接是否仍处于打开状态。"""
    try:
        return ws.state.name == 'OPEN'
    except Exception:
        return not getattr(ws, 'closed', False)


def member_list(room):
    return [{"id": wid, "name": m["name"]} for wid, m in room.members.items()]


def room_public(room):
    return {"room": room.id, "name": room.name, "count": len(room.members),
            "private": room.private}


async def send(ws, obj):
    try:
        await ws.send(json.dumps(obj, ensure_ascii=False))
    except Exception:
        pass


async def broadcast(room, obj, exclude=None):
    for wid, m in list(room.members.items()):
        if wid == exclude:
            continue
        await send(m["ws"], obj)


async def notify_members(room):
    await broadcast(room, {"type": "members", "members": member_list(room)})


async def cleanup(ws):
    """移除断开连接的用户，清理空房间与 ID 注册。"""
    for uid, entry in list(id_map.items()):
        if entry["ws"] is ws:
            del id_map[uid]
    for rid, room in list(rooms.items()):
        if ws in [m["ws"] for m in room.members.values()]:
            wid = next(w for w, m in room.members.items() if m["ws"] is ws)
            del room.members[wid]
            await notify_members(room)
            if not room.members:
                del rooms[rid]
            return


async def handle(ws):
    wid = None
    room = None
    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            t = msg.get("type")
            name = str(msg.get("name") or "")[:20] or "匿名"

            if t == "create":
                if room:
                    await send(ws, {"type": "error", "msg": "请先离开当前房间"})
                    continue
                wid = str(ws.id)
                rid = rid4()
                salt = msg.get("salt")  # HTML 端生成
                r = Room(rid, str(msg.get("name") or "")[:20],
                         str(msg.get("password") or ""), wid, name, ws, salt)
                rooms[rid] = r
                room = r
                await send(ws, {"type": "created", "room": rid, "salt": r.salt,
                                "host": True, "id": wid, "members": member_list(r)})
                print(f"[+] 创建房间 {rid} 成员 {name}")

            elif t == "join":
                rid = str(msg.get("room") or "")
                r = rooms.get(rid)
                if not r:
                    await send(ws, {"type": "error", "msg": "房间不存在"})
                    continue
                if len(r.members) >= MAX_MEMBERS:
                    await send(ws, {"type": "error", "msg": "房间已满"})
                    continue
                if r.password and msg.get("password") != r.password:
                    await send(ws, {"type": "error", "msg": "房间密码错误"})
                    continue
                wid = str(ws.id)
                r.members[wid] = {"name": name, "ws": ws}
                room = r
                await send(ws, {"type": "joined", "room": rid, "salt": r.salt,
                                "host": r.is_host(wid), "id": wid, "members": member_list(r)})
                await notify_members(r)
                print(f"[+] {name} 加入房间 {rid} ({len(r.members)})")

            elif t == "random":
                rid = str(msg.get("room") or "")
                # 找非私密且未满的公开房间；若已在房间则不再换
                cand = [r for r in rooms.values()
                        if not r.private and len(r.members) < MAX_MEMBERS]
                if cand:
                    r = random.choice(cand)
                else:
                    wid = str(ws.id)
                    rid = rid4()
                    salt = msg.get("salt")
                    r = Room(rid, "", "", wid, name, ws, salt)
                    rooms[rid] = r
                    room = r
                    await send(ws, {"type": "created", "room": rid, "salt": r.salt,
                                    "host": True, "id": wid, "members": member_list(r)})
                    print(f"[+] 随机创建房间 {rid} 成员 {name}")
                    continue
                if len(r.members) >= MAX_MEMBERS:
                    await send(ws, {"type": "error", "msg": "没有可加入的公开房间"})
                    continue
                wid = str(ws.id)
                r.members[wid] = {"name": name, "ws": ws}
                room = r
                await send(ws, {"type": "joined", "room": r.id, "salt": r.salt,
                                "host": r.is_host(wid), "id": wid, "members": member_list(r)})
                await notify_members(r)
                print(f"[+] {name} 随机匹配进房间 {r.id} ({len(r.members)})")

            elif t == "list":
                await send(ws, {"type": "rooms",
                                "rooms": [room_public(r) for r in rooms.values()]})

            elif t == "private":
                if not room:
                    await send(ws, {"type": "error", "msg": "不在房间内"})
                    continue
                if not room.is_host(wid):
                    await send(ws, {"type": "error", "msg": "仅房主可设置私密"})
                    continue
                room.private = bool(msg.get("private"))
                if room.private:
                    room.password = str(msg.get("password") or "")[:20]
                else:
                    room.password = ""
                await broadcast(room, {"type": "private_changed",
                                       "private": room.private})
                print(f"[*] 房间 {room.id} 私密={room.private}")

            elif t == "signal":
                if not room:
                    continue
                to = str(msg.get("to") or "")
                target = room.members.get(to)
                if target:
                    await send(target["ws"], {"type": "signal",
                                              "from": wid, "data": msg.get("data")})

            elif t == "register":
                # 永久 ID 注册：id_map 维护 用户ID -> ws，供 ID 直连
                uid = str(msg.get("id") or "")[:64]
                if not uid:
                    continue
                old = id_map.get(uid)
                if old and old["ws"] is not ws and ws_alive(old["ws"]):
                    await send(ws, {"type": "error",
                                    "msg": "该 ID 已在其他页面在线（同一浏览器同 ID 只允许一个连接），请刷新后重试"})
                    continue
                id_map[uid] = {"ws": ws, "name": name}
                await send(ws, {"type": "registered", "id": uid})
                print(f"[*] ID 注册 {uid} ({name})")

            elif t == "id_status":
                uid = str(msg.get("id") or "")[:64]
                entry = id_map.get(uid)
                online = bool(entry and ws_alive(entry["ws"]))
                await send(ws, {"type": "id_status", "id": uid,
                                "online": online,
                                "name": entry["name"] if online else ""})

            elif t == "direct":
                # ID 直连信令：转发给指定永久 ID（不需要房间）
                to = str(msg.get("to") or "")[:64]
                entry = id_map.get(to)
                if not entry or not ws_alive(entry["ws"]):
                    await send(ws, {"type": "error", "msg": "对方 ID 不在线"})
                    continue
                if entry["ws"] is ws:
                    await send(ws, {"type": "error", "msg": "不能直连自己"})
                    continue
                await send(entry["ws"], {"type": "direct",
                                         "from": str(msg.get("from") or ""),
                                         "from_id": to,
                                         "data": msg.get("data")})

            elif t == "leave":
                if room and wid:
                    room.members.pop(wid, None)
                    await notify_members(room)
                    if not room.members:
                        del rooms[rid]
                    room = None
                    wid = None
                    await send(ws, {"type": "left"})

    except websockets.ConnectionClosed:
        pass
    finally:
        await cleanup(ws)


def main():
    ap = argparse.ArgumentParser(description="SecureLink 信令服务器")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    print(f"SecureLink 信令服务器启动 ws://{args.host}:{args.port}")
    print("已创建/加入/随机/列表/私密/信令转发等接口")

    async def serve_forever():
        async with websockets.serve(handle, args.host, args.port):
            await asyncio.Future()  # 永久运行

    asyncio.run(serve_forever())


if __name__ == "__main__":
    main()
