"""
真正可用的中继服务器
- 管理房间（房间码 -> 房主连接）
- 玩家加入时，将两条 TCP 连接双向绑定
- 支持多个玩家同时连接同一个房间（每个玩家独立通道）

协议格式（全部 big-endian）：
注册房间:  [1 字节 cmd=0x01] [6 字节 room_code ASCII]
加入房间:  [1 字节 cmd=0x02] [6 字节 room_code ASCII]
服务器回应: [1 字节 cmd=0x10=OK / 0x11=ERROR] [可选 1 字节 msg_len] [可选 msg]
流量包:   [1 字节 cmd=0xFF] [2 字节 data_len] [data]
"""
import asyncio
import logging
import random
import struct
from typing import Dict, Optional

logger = logging.getLogger(__name__)

CMD_REGISTER = 0x01
CMD_JOIN     = 0x02
CMD_OK       = 0x10
CMD_ERROR    = 0x11
CMD_DATA     = 0xFF
CMD_PING     = 0x20
CMD_PONG     = 0x21
CMD_PLAYER_JOINED = 0x30   # 通知房主有玩家连入
CMD_PLAYER_LEFT   = 0x31   # 通知房主玩家断开

MAX_PLAYERS_PER_ROOM = 8
IDLE_TIMEOUT = 120  # 2分钟无数据超时


def _gen_room_code() -> str:
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choice(chars) for _ in range(6))


async def _send_pkt(writer: asyncio.StreamWriter, cmd: int, data: bytes = b""):
    """发送一个协议包"""
    if cmd == CMD_DATA:
        # DATA包: cmd(1) + len(2) + data
        pkt = struct.pack(">BH", cmd, len(data)) + data
    else:
        # 其他包: cmd(1) + len(1) + data
        pkt = struct.pack(">BB", cmd, len(data)) + data
    writer.write(pkt)
    await writer.drain()


async def _read_pkt(reader: asyncio.StreamReader):
    """读取一个协议包，返回 (cmd, data) 或抛出 EOF"""
    hdr = await reader.readexactly(1)
    cmd = hdr[0]
    if cmd == CMD_DATA:
        len_b = await reader.readexactly(2)
        data_len = struct.unpack(">H", len_b)[0]
        data = await reader.readexactly(data_len) if data_len else b""
    else:
        len_b = await reader.readexactly(1)
        data_len = len_b[0]
        data = await reader.readexactly(data_len) if data_len else b""
    return cmd, data


class RelayRoom:
    """一个联机房间"""
    def __init__(self, code: str, host_writer: asyncio.StreamWriter):
        self.code = code
        self.host_writer = host_writer
        # player_id -> (reader, writer)
        self.players: Dict[int, tuple] = {}
        self._next_player_id = 1

    def add_player(self, reader, writer) -> int:
        pid = self._next_player_id
        self._next_player_id += 1
        self.players[pid] = (reader, writer)
        return pid

    def remove_player(self, pid: int):
        self.players.pop(pid, None)

    @property
    def player_count(self) -> int:
        return len(self.players)


class RelayServer:
    """中继服务器主类"""

    def __init__(self, host="0.0.0.0", port=25566):
        self.host = host
        self.port = port
        self._running = False
        self._server: Optional[asyncio.Server] = None
        self._rooms: Dict[str, RelayRoom] = {}  # code -> RelayRoom

    async def start(self):
        self._running = True
        self._server = await asyncio.start_server(
            self._handle_connection, self.host, self.port
        )
        logger.info(f"[RELAY] 中继服务器已启动 {self.host}:{self.port}")

    async def serve_forever(self):
        """持续运行，直到 stop() 被调用"""
        await self.start()
        async with self._server:
            await self._server.serve_forever()

    async def stop(self):
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        logger.info("[RELAY] 中继服务器已停止")

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter):
        addr = writer.get_extra_info("peername")
        logger.info(f"[RELAY] 新连接 {addr}")
        try:
            cmd, data = await asyncio.wait_for(_read_pkt(reader), timeout=15)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError):
            logger.warning(f"[RELAY] {addr} 握手超时或断开")
            writer.close()
            return

        if cmd == CMD_REGISTER:
            await self._handle_host(reader, writer, addr)
        elif cmd == CMD_JOIN:
            code = data.decode("ascii", errors="ignore").strip().upper()
            await self._handle_player(reader, writer, addr, code)
        else:
            logger.warning(f"[RELAY] {addr} 未知命令 0x{cmd:02X}")
            writer.close()

    async def _handle_host(self, reader, writer, addr):
        """处理房主注册"""
        # 生成唯一房间码
        for _ in range(20):
            code = _gen_room_code()
            if code not in self._rooms:
                break
        else:
            await _send_pkt(writer, CMD_ERROR, b"no room slot")
            writer.close()
            return

        room = RelayRoom(code, writer)
        self._rooms[code] = room
        logger.info(f"[RELAY] 房间创建: {code} (房主 {addr})")

        # 回告房间码
        await _send_pkt(writer, CMD_OK, code.encode("ascii"))

        try:
            while self._running:
                try:
                    cmd, data = await asyncio.wait_for(
                        _read_pkt(reader), timeout=IDLE_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    logger.info(f"[RELAY] 房间 {code} 空闲超时，关闭")
                    break

                if cmd == CMD_PING:
                    await _send_pkt(writer, CMD_PONG)
                elif cmd == CMD_DATA:
                    # 广播给所有玩家 —— 但这里不对，data里需要含player_id前缀
                    # 格式: data[0]=player_id(1字节) data[1:]=payload
                    if len(data) >= 1:
                        pid = data[0]
                        payload = data[1:]
                        if pid in room.players:
                            _, pw = room.players[pid]
                            try:
                                await _send_pkt(pw, CMD_DATA, payload)
                            except Exception:
                                pass
                else:
                    logger.debug(f"[RELAY] 房主发来未知 cmd=0x{cmd:02X}")
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            logger.info(f"[RELAY] 房间 {code} 关闭，踢出所有玩家")
            del self._rooms[code]
            # 关闭所有玩家连接
            for pid, (pr, pw) in list(room.players.items()):
                try:
                    pw.close()
                except Exception:
                    pass
            writer.close()

    async def _handle_player(self, reader, writer, addr, code: str):
        """处理玩家加入"""
        if code not in self._rooms:
            await _send_pkt(writer, CMD_ERROR, b"room not found")
            writer.close()
            return

        room = self._rooms[code]
        if room.player_count >= MAX_PLAYERS_PER_ROOM:
            await _send_pkt(writer, CMD_ERROR, b"room full")
            writer.close()
            return

        pid = room.add_player(reader, writer)
        logger.info(f"[RELAY] 玩家 {addr} 加入房间 {code}，分配 ID={pid}")

        # 告知玩家成功，返回 player_id
        await _send_pkt(writer, CMD_OK, bytes([pid]))

        # 通知房主有新玩家
        try:
            await _send_pkt(room.host_writer, CMD_PLAYER_JOINED, bytes([pid]))
        except Exception:
            pass

        # 开始中继：玩家 -> 中继 -> 房主（带 pid 前缀）
        try:
            while self._running:
                try:
                    cmd, data = await asyncio.wait_for(
                        _read_pkt(reader), timeout=IDLE_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    break

                if cmd == CMD_PING:
                    await _send_pkt(writer, CMD_PONG)
                elif cmd == CMD_DATA:
                    # 转发给房主，前缀 player_id
                    try:
                        await _send_pkt(room.host_writer, CMD_DATA,
                                        bytes([pid]) + data)
                    except Exception:
                        break
                else:
                    logger.debug(f"[RELAY] 玩家 {pid} 发来未知 cmd=0x{cmd:02X}")
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            room.remove_player(pid)
            logger.info(f"[RELAY] 玩家 {pid} 离开房间 {code}")
            try:
                await _send_pkt(room.host_writer, CMD_PLAYER_LEFT, bytes([pid]))
            except Exception:
                pass
            writer.close()

    @property
    def room_count(self) -> int:
        return len(self._rooms)

    def get_room_info(self) -> list:
        return [{"code": c, "players": r.player_count}
                for c, r in self._rooms.items()]
