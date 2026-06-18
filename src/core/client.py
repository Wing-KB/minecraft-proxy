"""
Minecraft 代理客户端（玩家端）—— 包装 PlayerSession
"""
import asyncio
import logging
from typing import Optional, Callable
from .player_session import PlayerSession

logger = logging.getLogger(__name__)


class ProxyClient:
    """Minecraft 代理客户端（玩家端）"""

    def __init__(self, relay_host: str = "127.0.0.1",
                 relay_port: int = 25566,
                 local_port: int = 25565,
                 player_name: str = "Player",
                 on_status: Optional[Callable[[str], None]] = None,
                 # 旧参数兼容
                 server_host: str = "",
                 config=None):
        if relay_host == "127.0.0.1" and server_host:
            relay_host = server_host
        self.relay_host = relay_host
        self.relay_port = relay_port
        self.local_port = local_port
        self.player_name = player_name

        self._session: Optional[PlayerSession] = None
        self._on_status = on_status

    async def connect(self, room_code: str = "") -> bool:
        """
        连接到中继服务器并加入房间
        成功后开启本地监听
        返回是否成功
        """
        self._session = PlayerSession(
            relay_host=self.relay_host,
            relay_port=self.relay_port,
            room_code=room_code,
            local_port=self.local_port,
            on_status=self._on_status,
        )
        try:
            await self._session.connect()
            await self._session.start_local()
            return True
        except Exception as e:
            logger.error(f"[CLIENT] 连接失败: {e}")
            if self._on_status:
                self._on_status(f"连接失败: {e}")
            return False

    async def disconnect(self):
        if self._session:
            await self._session.stop()
            self._session = None

    async def wait_until_stopped(self):
        if self._session:
            await self._session.wait_until_stopped()

    @property
    def is_connected(self) -> bool:
        return self._session is not None and self._session._running

    @property
    def room_code(self) -> str:
        return self._session.room_code if self._session else ""
