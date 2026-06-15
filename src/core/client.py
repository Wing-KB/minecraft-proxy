"""客户端模块"""
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class ProxyClient:
    """Minecraft 代理客户端（玩家端）"""
    
    def __init__(self, server_host="", relay_port=25566, voice_port=24454,
                 player_name="Player", config=None):
        self.server_host = server_host
        self.relay_port = relay_port
        self.voice_port = voice_port
        self.player_name = player_name
        self.config = config
        self._connected = False
        self._room_code = ""
    
    async def connect(self, room_code=""):
        """连接到房间"""
        self._room_code = room_code.upper() if room_code else ""
        logger.info(f"连接到房间: {self._room_code}")
        self._connected = True
    
    async def disconnect(self):
        """断开连接"""
        self._connected = False
        logger.info("已断开连接")
    
    @property
    def is_connected(self) -> bool:
        return self._connected
    
    @property
    def room_code(self) -> str:
        return self._room_code
