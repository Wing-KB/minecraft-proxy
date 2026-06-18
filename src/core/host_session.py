"""
房主端核心逻辑
- 连接到中继服务器，注册房间
- 监听本地 Minecraft 服务器（127.0.0.1:mc_port）
- 每当中继服务器通知有玩家加入，就连一次本地 MC 服务器
  并将该玩家通道 <-> MC连接双向绑定

协议见 relay_server.py
"""
import asyncio
import logging
import struct
from typing import Dict, Optional, Callable
from .relay_server import (CMD_OK, CMD_ERROR, CMD_DATA, CMD_PING, CMD_PONG,
                            CMD_PLAYER_JOINED, CMD_PLAYER_LEFT,
                            _send_pkt, _read_pkt)

logger = logging.getLogger(__name__)

RELAY_DEFAULT_PORT = 25566
KEEPALIVE_INTERVAL = 30


class HostSession:
    """
    房主端会话
    
    用法:
        session = HostSession(relay_host, relay_port, mc_port)
        code = await session.start()          # 返回房间码
        await session.wait_until_stopped()
        await session.stop()
    """

    def __init__(self, relay_host: str, relay_port: int = RELAY_DEFAULT_PORT,
                 mc_host: str = "127.0.0.1", mc_port: int = 25565,
                 on_status: Optional[Callable[[str], None]] = None,
                 on_player_count: Optional[Callable[[int], None]] = None):
        self.relay_host = relay_host
        self.relay_port = relay_port
        self.mc_host = mc_host
        self.mc_port = mc_port
        self.on_status = on_status       # 状态文字回调
        self.on_player_count = on_player_count  # 玩家数变化回调

        self._room_code = ""
        self._running = False
        self._relay_reader: Optional[asyncio.StreamReader] = None
        self._relay_writer: Optional[asyncio.StreamWriter] = None
        # player_id -> mc_writer
        self._mc_writers: Dict[int, asyncio.StreamWriter] = {}
        self._player_count = 0
        self._stop_event = asyncio.Event()
        self._tasks = []

    def _emit(self, msg: str):
        logger.info(msg)
        if self.on_status:
            self.on_status(msg)

    def _emit_count(self):
        if self.on_player_count:
            self.on_player_count(self._player_count)

    @property
    def room_code(self) -> str:
        return self._room_code

    @property
    def player_count(self) -> int:
        return self._player_count

    async def start(self) -> str:
        """
        连接中继服务器，注册房间，返回房间码
        失败时抛出异常
        """
        self._emit(f"正在连接中继服务器 {self.relay_host}:{self.relay_port} ...")
        self._relay_reader, self._relay_writer = await asyncio.wait_for(
            asyncio.open_connection(self.relay_host, self.relay_port),
            timeout=10
        )

        # 发送注册请求
        self._relay_writer.write(bytes([0x01, 0x00]))  # CMD_REGISTER + empty data
        await self._relay_writer.drain()

        cmd, data = await asyncio.wait_for(_read_pkt(self._relay_reader), timeout=10)
        if cmd != CMD_OK:
            raise RuntimeError(f"注册失败: {data.decode(errors='ignore')}")

        self._room_code = data.decode("ascii").strip()
        self._running = True
        self._emit(f"房间已创建！房间码: {self._room_code}")

        # 启动后台任务
        t1 = asyncio.create_task(self._relay_loop())
        t2 = asyncio.create_task(self._keepalive_loop())
        self._tasks = [t1, t2]

        return self._room_code

    async def stop(self):
        self._running = False
        self._stop_event.set()
        for t in self._tasks:
            t.cancel()
        # 关闭所有 MC 连接
        for pid, w in list(self._mc_writers.items()):
            try:
                w.close()
            except Exception:
                pass
        self._mc_writers.clear()
        if self._relay_writer:
            try:
                self._relay_writer.close()
            except Exception:
                pass
        self._emit("房主端已停止")

    async def wait_until_stopped(self):
        await self._stop_event.wait()

    async def _keepalive_loop(self):
        """定期发送心跳，防止中继超时断开"""
        while self._running:
            await asyncio.sleep(KEEPALIVE_INTERVAL)
            if not self._running:
                break
            try:
                await _send_pkt(self._relay_writer, CMD_PING)
            except Exception:
                break

    async def _relay_loop(self):
        """主循环：处理中继服务器发来的消息"""
        try:
            while self._running:
                try:
                    cmd, data = await asyncio.wait_for(
                        _read_pkt(self._relay_reader), timeout=60
                    )
                except asyncio.TimeoutError:
                    self._emit("中继连接超时，断开")
                    break

                if cmd == CMD_PONG:
                    pass

                elif cmd == CMD_PLAYER_JOINED:
                    if data:
                        pid = data[0]
                        asyncio.create_task(self._on_player_joined(pid))

                elif cmd == CMD_PLAYER_LEFT:
                    if data:
                        pid = data[0]
                        self._on_player_left(pid)

                elif cmd == CMD_DATA:
                    # data[0]=pid, data[1:]=MC流量
                    if len(data) >= 1:
                        pid = data[0]
                        payload = data[1:]
                        await self._forward_to_mc(pid, payload)
                else:
                    logger.debug(f"[HOST] 未知 cmd=0x{cmd:02X}")

        except (asyncio.IncompleteReadError, ConnectionError, OSError) as e:
            self._emit(f"中继连接断开: {e}")
        finally:
            self._running = False
            self._stop_event.set()

    async def _on_player_joined(self, pid: int):
        """玩家加入：连接本地 MC 服务器"""
        self._emit(f"玩家 {pid} 加入，正在连接本地 MC {self.mc_host}:{self.mc_port} ...")
        try:
            mc_reader, mc_writer = await asyncio.wait_for(
                asyncio.open_connection(self.mc_host, self.mc_port),
                timeout=10
            )
        except Exception as e:
            self._emit(f"连接本地 MC 失败（玩家 {pid}）: {e}")
            # 告知中继这个玩家的通道挂了（发个空包即可，让玩家端超时）
            return

        self._mc_writers[pid] = mc_writer
        self._player_count += 1
        self._emit_count()
        self._emit(f"玩家 {pid} 已连接到本地 MC，开始中继")

        # 启动 MC -> 中继 转发任务
        asyncio.create_task(self._mc_to_relay(pid, mc_reader))

    def _on_player_left(self, pid: int):
        self._emit(f"玩家 {pid} 离开")
        w = self._mc_writers.pop(pid, None)
        if w:
            try:
                w.close()
            except Exception:
                pass
            self._player_count = max(0, self._player_count - 1)
            self._emit_count()

    async def _forward_to_mc(self, pid: int, data: bytes):
        """中继 -> MC 转发"""
        w = self._mc_writers.get(pid)
        if w:
            try:
                w.write(data)
                await w.drain()
            except Exception as e:
                logger.debug(f"[HOST] 转发到 MC 失败 pid={pid}: {e}")
                self._on_player_left(pid)

    async def _mc_to_relay(self, pid: int, mc_reader: asyncio.StreamReader):
        """持续读取 MC 服务器数据，打包发给中继"""
        try:
            while self._running and pid in self._mc_writers:
                data = await asyncio.wait_for(mc_reader.read(65536), timeout=60)
                if not data:
                    break
                # 发给中继，带 pid 前缀
                await _send_pkt(self._relay_writer, CMD_DATA, bytes([pid]) + data)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError,
                ConnectionError, OSError):
            pass
        finally:
            logger.info(f"[HOST] MC连接断开 pid={pid}")
            self._on_player_left(pid)
