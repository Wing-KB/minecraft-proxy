"""
真正可用的中继服务器（支持陶瓦房间码 + TCP/UDP 中继）
- 支持 6 位房间码（向下兼容）和陶瓦格式 U/XXXX-XXXX-XXXX-XXXX
- 支持陶瓦标记（房间内有人用陶瓦则禁用 UDP 中继）
- 支持 UDP 中继（通过 TCP 隧道传输 UDP 包）

协议格式（big-endian）：
注册/加入包 data: [1 字节 flags] [房间码 ASCII...]
  flags: bit0=使用陶瓦, bit1=请求UDP中继
服务器回应 OK: [房间码 ASCII] [2 字节 UDP端口, 0=禁用]
流量包: CMD_DATA [2 字节 len] [data]  （原样转发）
UDP 包: CMD_UDP_DATA [2 字节 player_id] [data]  （通过 TCP 隧道传 UDP）
"""

import asyncio
import logging
import random
import struct
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

CMD_REGISTER      = 0x01
CMD_JOIN          = 0x02
CMD_OK            = 0x10
CMD_ERROR         = 0x11
CMD_DATA          = 0xFF
CMD_PING          = 0x20
CMD_PONG          = 0x21
CMD_PLAYER_JOINED = 0x30
CMD_PLAYER_LEFT   = 0x31
CMD_UDP           = 0x40  # UDP 数据包（通过 TCP 隧道）

MAX_PLAYERS_PER_ROOM = 8
IDLE_TIMEOUT = 120

FLAG_TERRACOTTA = 0x01
FLAG_WANT_UDP    = 0x02


def _gen_room_code() -> str:
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choice(chars) for _ in range(6))


# ── 协议读写 ────────────────────────────────────────────────────

async def _send_pkt(writer: asyncio.StreamWriter, cmd: int, data: bytes = b""):
    if cmd == CMD_DATA:
        pkt = struct.pack(">BH", cmd, len(data)) + data
    else:
        pkt = struct.pack(">BB", cmd, len(data)) + data
    writer.write(pkt)
    await writer.drain()


async def _read_pkt(reader: asyncio.StreamReader) -> Tuple[int, bytes]:
    hdr = await reader.readexactly(1)
    cmd = hdr[0]
    if cmd == CMD_DATA:
        lb = await reader.readexactly(2)
        dlen = struct.unpack(">H", lb)[0]
        data = await reader.readexactly(dlen) if dlen else b""
    else:
        lb = await reader.readexactly(1)
        dlen = lb[0]
        data = await reader.readexactly(dlen) if dlen else b""
    return cmd, data


# ── 房间管理 ────────────────────────────────────────────────────

class RelayRoom:
    def __init__(self, code: str, host_writer: asyncio.StreamWriter, host_flags: int = 0):
        self.code = code
        self.host_writer = host_writer
        self.host_flags = host_flags
        self.players: Dict[int, Tuple[asyncio.StreamReader, asyncio.StreamWriter, int]] = {}
        self._next_pid = 1
        self.udp_sessions: Dict[Tuple[str, int], int] = {}  # (ip, port) -> pid

    def add_player(self, reader, writer, flags: int = 0) -> int:
        pid = self._next_pid
        self._next_pid += 1
        self.players[pid] = (reader, writer, flags)
        return pid

    def remove_player(self, pid: int):
        self.players.pop(pid, None)

    @property
    def player_count(self) -> int:
        return len(self.players)

    @property
    def has_terracotta(self) -> bool:
        if self.host_flags & FLAG_TERRACOTTA:
            return True
        return any(f & FLAG_TERRACOTTA for (_, _, f) in self.players.values())

    @property
    def udp_enabled(self) -> bool:
        """没人用陶瓦 且 有人想要 UDP 时才开"""
        if self.has_terracotta:
            return False
        if self.host_flags & FLAG_WANT_UDP:
            return True
        return any(f & FLAG_WANT_UDP for (_, _, f) in self.players.values())


# ── 中继服务器 ──────────────────────────────────────────────────

class RelayServer:
    def __init__(self, host="0.0.0.0", port=25566, udp_port: Optional[int] = None):
        self.host = host
        self.port = port
        self.udp_port = udp_port or port + 1
        self._running = False
        self._server: Optional[asyncio.Server] = None
        self._rooms: Dict[str, RelayRoom] = {}
        # UDP 相关
        self._udp_transport: Optional[asyncio.DatagramTransport] = None
        self._udp_protocol: Optional["_UdpProtocol"] = None

    async def start(self):
        self._running = True
        self._server = await asyncio.start_server(self._handle_conn, self.host, self.port)
        logger.info(f"[RELAY] TCP 中继 {self.host}:{self.port}")
        # 启动 UDP 中继
        try:
            loop = asyncio.get_running_loop()
            self._udp_protocol = _UdpProtocol(self)
            self._udp_transport, _ = await loop.create_datagram_endpoint(
                lambda: self._udp_protocol,
                local_addr=(self.host, self.udp_port)
            )
            logger.info(f"[RELAY] UDP 中继 {self.host}:{self.udp_port}")
        except Exception as e:
            logger.warning(f"[RELAY] UDP 中继启动失败: {e}（禁用 UDP）")
            self._udp_transport = None

    async def serve_forever(self):
        await self.start()
        async with self._server:
            await self._server.serve_forever()

    async def stop(self):
        self._running = False
        if self._udp_transport:
            self._udp_transport.close()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        logger.info("[RELAY] 已停止")

    # ── 连接处理 ────────────────────────────────────────────────

    async def _handle_conn(self, reader, writer):
        addr = writer.get_extra_info("peername")
        logger.info(f"[RELAY] 新连接 {addr}")
        try:
            cmd, data = await asyncio.wait_for(_read_pkt(reader), timeout=15)
        except Exception:
            writer.close()
            return

        if cmd == CMD_REGISTER:
            await self._handle_host(reader, writer, data)
        elif cmd == CMD_JOIN:
            await self._handle_player(reader, writer, data)
        else:
            logger.warning(f"[RELAY] 未知 cmd=0x{cmd:02X}")
            writer.close()

    async def _handle_host(self, reader, writer, data: bytes):
        flags = data[0] if data else 0
        req_code = data[1:].decode("ascii", errors="ignore").strip().upper()

        if req_code and self._valid_code(req_code) and req_code not in self._rooms:
            code = req_code
        else:
            for _ in range(30):
                code = _gen_room_code()
                if code not in self._rooms:
                    break
            else:
                await _send_pkt(writer, CMD_ERROR, b"no slot")
                writer.close()
                return

        room = RelayRoom(code, writer, flags)
        self._rooms[code] = room
        udp_port = self.udp_port if room.udp_enabled else 0
        resp = code.encode("ascii") + struct.pack(">H", udp_port)
        await _send_pkt(writer, CMD_OK, resp)
        logger.info(f"[RELAY] 房间 {code} 已创建（陶瓦={room.has_terracotta}, UDP={udp_port or '禁用'}）")

        try:
            while self._running:
                try:
                    cmd, data = await asyncio.wait_for(_read_pkt(reader), timeout=IDLE_TIMEOUT)
                except asyncio.TimeoutError:
                    break
                if cmd == CMD_PING:
                    await _send_pkt(writer, CMD_PONG)
                elif cmd == CMD_DATA:
                    await self._relay_tcp_to_players(room, data)
                elif cmd == CMD_UDP:
                    # 房主通过 TCP 隧道发来的 UDP 数据，转发给对应玩家
                    if len(data) >= 2:
                        pid = struct.unpack(">H", data[:2])[0]
                        self._relay_udp_to_player(room, pid, data[2:])
        except Exception:
            pass
        finally:
            del self._rooms[code]
            logger.info(f"[RELAY] 房间 {code} 已关闭")
            writer.close()

    async def _handle_player(self, reader, writer, data: bytes):
        flags = data[0] if data else 0
        code = data[1:].decode("ascii", errors="ignore").strip().upper()
        room = self._rooms.get(code)
        if not room:
            await _send_pkt(writer, CMD_ERROR, b"room not found")
            writer.close()
            return
        if room.player_count >= MAX_PLAYERS_PER_ROOM:
            await _send_pkt(writer, CMD_ERROR, b"room full")
            writer.close()
            return

        pid = room.add_player(reader, writer, flags)
        udp_port = self.udp_port if room.udp_enabled else 0
        resp = bytes([pid]) + struct.pack(">H", udp_port)
        await _send_pkt(writer, CMD_OK, resp)
        logger.info(f"[RELAY] 玩家 {pid} 加入 {code}（陶瓦={bool(flags & FLAG_TERRACOTTA)}）")

        # 通知房主
        try:
            await _send_pkt(room.host_writer, CMD_PLAYER_JOINED, bytes([pid, flags]))
        except Exception:
            pass

        # 玩家 -> 房主 中继
        try:
            while self._running:
                try:
                    cmd, data = await asyncio.wait_for(_read_pkt(reader), timeout=IDLE_TIMEOUT)
                except asyncio.TimeoutError:
                    break
                if cmd == CMD_PING:
                    await _send_pkt(writer, CMD_PONG)
                elif cmd == CMD_DATA:
                    # 转发给房主，带 pid
                    try:
                        await _send_pkt(room.host_writer, CMD_DATA,
                                        struct.pack(">H", pid) + data)
                    except Exception:
                        break
                elif cmd == CMD_UDP:
                    # 玩家通过 TCP 隧道发来的 UDP 数据，转发给房主
                    try:
                        await _send_pkt(room.host_writer, CMD_UDP, data)
                    except Exception:
                        break
        except Exception:
            pass
        finally:
            room.remove_player(pid)
            logger.info(f"[RELAY] 玩家 {pid} 离开 {code}")
            try:
                await _send_pkt(room.host_writer, CMD_PLAYER_LEFT, bytes([pid]))
            except Exception:
                pass
            writer.close()

    # ── 数据中继 ──────────────────────────────────────────────

    async def _relay_tcp_to_players(self, room: RelayRoom, data: bytes):
        """房主发来的 TCP 数据，转发给对应玩家（data[0:2]=pid）"""
        if len(data) < 2:
            return
        pid = struct.unpack(">H", data[:2])[0]
        payload = data[2:]
        entry = room.players.get(pid)
        if entry:
            _, pw, _ = entry
            try:
                pw.write(payload)
                await pw.drain()
            except Exception:
                pass

    def _relay_udp_to_player(self, room: RelayRoom, pid: int, payload: bytes):
        """房主发来的 UDP 数据，通过 UDP 发给玩家"""
        if not self._udp_transport:
            return
        # 查找该 pid 最近的 UDP 来源地址
        for (ip, port), p in list(room.udp_sessions.items()):
            if p == pid:
                self._udp_transport.sendto(payload, (ip, port))
                return

    def register_udp_session(self, room_code: str, pid: int, addr: Tuple[str, int]):
        """玩家发来 UDP 包时注册 (addr -> pid) 映射"""
        room = self._rooms.get(room_code)
        if room:
            room.udp_sessions[addr] = pid

    # ── 工具 ──────────────────────────────────────────────────

    def _valid_code(self, code: str) -> bool:
        if len(code) == 6 and code.isalnum():
            return True
        if len(code) == 21 and code.startswith("U/") and "-" in code:
            return True
        return False

    @property
    def room_count(self) -> int:
        return len(self._rooms)


# ── UDP 协议处理 ────────────────────────────────────────────────

class _UdpProtocol(asyncio.DatagramProtocol):
    """处理发到中继 UDP 端口的数据包"""
    def __init__(self, server: RelayServer):
        self.server = server

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data: bytes, addr: Tuple[str, int]):
        """收到玩家的 UDP 包，需要找到对应房间和 pid，通过 TCP 隧道转发"""
        # 简化：遍历所有房间找匹配的 udp_sessions
        for room in self.server._rooms.values():
            if addr in room.udp_sessions:
                pid = room.udp_sessions[addr]
                # 通过 TCP 隧道发给房主: CMD_UDP + pid(2) + data
                asyncio.ensure_future(self._forward(room, pid, data))
                return

    async def _forward(self, room: RelayRoom, pid: int, data: bytes):
        try:
            pkt = struct.pack(">BH", CMD_UDP, 2 + len(data)) + struct.pack(">H", pid) + data
            room.host_writer.write(pkt)
            await room.host_writer.drain()
        except Exception:
            pass
