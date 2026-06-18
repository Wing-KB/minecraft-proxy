"""
玩家端核心逻辑
- 连接中继服务器，加入指定房间码
- 在本地开监听 127.0.0.1:local_port（默认 25565）
- MC 客户端连 127.0.0.1:local_port 即可进入游戏
- 只允许一个 MC 客户端同时连接（单玩家对应单个中继通道）
"""
import asyncio
import logging
from typing import Optional, Callable
from .relay_server import (CMD_OK, CMD_ERROR, CMD_DATA, CMD_PING, CMD_PONG,
                            _send_pkt, _read_pkt)

logger = logging.getLogger(__name__)

RELAY_DEFAULT_PORT = 25566
KEEPALIVE_INTERVAL = 30


class PlayerSession:
    """
    玩家端会话

    用法:
        session = PlayerSession(relay_host, relay_port, room_code, local_port)
        await session.connect()      # 建立中继连接，验证房间码
        await session.start_local()  # 启动本地监听，MC 客户端连 127.0.0.1:local_port
        await session.wait_until_stopped()
        await session.stop()
    """

    def __init__(self, relay_host: str, relay_port: int = RELAY_DEFAULT_PORT,
                 room_code: str = "",
                 local_host: str = "127.0.0.1", local_port: int = 25565,
                 on_status: Optional[Callable[[str], None]] = None):
        self.relay_host = relay_host
        self.relay_port = relay_port
        self.room_code = room_code.upper().strip()
        self.local_host = local_host
        self.local_port = local_port
        self.on_status = on_status

        self._running = False
        self._player_id = 0
        self._relay_reader: Optional[asyncio.StreamReader] = None
        self._relay_writer: Optional[asyncio.StreamWriter] = None
        self._mc_writer: Optional[asyncio.StreamWriter] = None  # 本地 MC 客户端连接
        self._local_server: Optional[asyncio.Server] = None
        self._stop_event = asyncio.Event()
        self._tasks = []

    def _emit(self, msg: str):
        logger.info(msg)
        if self.on_status:
            self.on_status(msg)

    async def connect(self) -> int:
        """
        连接中继服务器并加入房间
        返回分配的 player_id（>0 表示成功）
        失败时抛出异常
        """
        self._emit(f"正在连接中继服务器 {self.relay_host}:{self.relay_port} ...")
        self._relay_reader, self._relay_writer = await asyncio.wait_for(
            asyncio.open_connection(self.relay_host, self.relay_port),
            timeout=10
        )

        # 发送加入请求，携带房间码
        code_bytes = self.room_code.encode("ascii")
        self._relay_writer.write(bytes([0x02, len(code_bytes)]) + code_bytes)
        await self._relay_writer.drain()

        cmd, data = await asyncio.wait_for(_read_pkt(self._relay_reader), timeout=10)
        if cmd == CMD_ERROR:
            raise RuntimeError(f"加入房间失败: {data.decode(errors='ignore')}")
        if cmd != CMD_OK:
            raise RuntimeError(f"未知响应: 0x{cmd:02X}")

        self._player_id = data[0] if data else 1
        self._running = True
        self._emit(f"成功加入房间 {self.room_code}（玩家 ID={self._player_id}）")
        return self._player_id

    async def start_local(self):
        """
        启动本地监听，等待 MC 客户端连接
        同时启动中继数据接收循环
        """
        # 启动中继接收任务
        t1 = asyncio.create_task(self._relay_loop())
        t2 = asyncio.create_task(self._keepalive_loop())
        self._tasks = [t1, t2]

        # 启动本地监听
        self._local_server = await asyncio.start_server(
            self._on_mc_client_connected,
            self.local_host, self.local_port
        )
        self._emit(
            f"本地监听已开启：{self.local_host}:{self.local_port}\n"
            f"请在 Minecraft 中连接 {self.local_host}:{self.local_port}"
        )

    async def stop(self):
        self._running = False
        self._stop_event.set()
        for t in self._tasks:
            t.cancel()
        if self._local_server:
            self._local_server.close()
        if self._mc_writer:
            try:
                self._mc_writer.close()
            except Exception:
                pass
        if self._relay_writer:
            try:
                self._relay_writer.close()
            except Exception:
                pass
        self._emit("玩家端已停止")

    async def wait_until_stopped(self):
        await self._stop_event.wait()

    async def _keepalive_loop(self):
        while self._running:
            await asyncio.sleep(KEEPALIVE_INTERVAL)
            if not self._running:
                break
            try:
                await _send_pkt(self._relay_writer, CMD_PING)
            except Exception:
                break

    async def _on_mc_client_connected(self, mc_reader: asyncio.StreamReader,
                                       mc_writer: asyncio.StreamWriter):
        """本地有 MC 客户端连进来了"""
        addr = mc_writer.get_extra_info("peername")
        self._emit(f"MC 客户端已连接 {addr}，开始中继游戏数据...")

        if self._mc_writer:
            # 踢掉旧的
            try:
                self._mc_writer.close()
            except Exception:
                pass
        self._mc_writer = mc_writer

        # 启动 MC客户端 -> 中继 转发
        asyncio.create_task(self._mc_to_relay(mc_reader))

    async def _mc_to_relay(self, mc_reader: asyncio.StreamReader):
        """读取 MC 客户端数据，发给中继"""
        try:
            while self._running:
                data = await asyncio.wait_for(mc_reader.read(65536), timeout=60)
                if not data:
                    break
                await _send_pkt(self._relay_writer, CMD_DATA, data)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError,
                ConnectionError, OSError):
            pass
        finally:
            self._emit("MC 客户端断开连接")
            self._mc_writer = None

    async def _relay_loop(self):
        """接收中继服务器转发来的 MC 服务器数据，写入 MC 客户端"""
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
                elif cmd == CMD_DATA:
                    if self._mc_writer:
                        try:
                            self._mc_writer.write(data)
                            await self._mc_writer.drain()
                        except Exception:
                            pass
                elif cmd == CMD_ERROR:
                    self._emit(f"中继错误: {data.decode(errors='ignore')}")
                    break
                else:
                    logger.debug(f"[PLAYER] 未知 cmd=0x{cmd:02X}")

        except (asyncio.IncompleteReadError, ConnectionError, OSError) as e:
            self._emit(f"中继连接断开: {e}")
        finally:
            self._running = False
            self._stop_event.set()
