"""
Minecraft 代理服务器（房主端）—— 包装 HostSession
"""
import asyncio
import logging
from typing import Optional, Callable
from .host_session import HostSession

logger = logging.getLogger(__name__)


class ProxyServer:
    """Minecraft 代理服务器（房主端）"""

    def __init__(self, relay_host: str = "127.0.0.1",
                 relay_port: int = 25566,
                 mc_host: str = "127.0.0.1",
                 mc_port: int = 25565,
                 player_name: str = "Host",
                 on_status: Optional[Callable[[str], None]] = None,
                 on_player_count: Optional[Callable[[int], None]] = None,
                 # 旧参数兼容
                 host: str = "0.0.0.0",
                 port: int = 25565,
                 config=None):
        # 兼容旧接口
        if relay_host == "127.0.0.1" and host != "0.0.0.0":
            relay_host = host
        self.relay_host = relay_host
        self.relay_port = relay_port
        self.mc_host = mc_host
        self.mc_port = mc_port
        self.player_name = player_name

        self._session = HostSession(
            relay_host=relay_host,
            relay_port=relay_port,
            mc_host=mc_host,
            mc_port=mc_port,
            on_status=on_status,
            on_player_count=on_player_count,
        )

    async def start(self) -> str:
        """启动，返回房间码"""
        code = await self._session.start()
        return code

    async def stop(self):
        await self._session.stop()

    async def wait_until_stopped(self):
        await self._session.wait_until_stopped()

    @property
    def room_code(self) -> str:
        return self._session.room_code

    @property
    def player_count(self) -> int:
        return self._session.player_count


from ..config import print_banner
