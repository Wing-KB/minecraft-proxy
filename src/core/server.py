"""
Minecraft 代理服务器（房主端）
"""
import asyncio
import logging
import socket
import time
import random
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class ProxyServer:
    """Minecraft 代理服务器（房主端）"""
    
    def __init__(self, host="0.0.0.0", mc_port=25565, relay_port=25566,
                 voice_port=24454, player_name="Host", config=None):
        self.host = host
        self.mc_port = mc_port
        self.relay_port = relay_port
        self.voice_port = voice_port
        self.player_name = player_name
        self.config = config
        self._running = False
        self._room_code = ""
        self._connections: Dict = {}
        self._start_time = 0
    
    async def start(self):
        """启动代理服务器"""
        self._running = True
        self._start_time = time.time()
        self._room_code = self._generate_room_code()
        
        print_banner()
        logger.info(f"房间码: {self._room_code}")
        logger.info(f"Minecraft 端口: {self.mc_port}")
        logger.info(f"中继端口: {self.relay_port}")
        logger.info(f"语音端口: {self.voice_port}")
        
        await self._main_loop()
    
    async def _main_loop(self):
        """主循环"""
        while self._running:
            await asyncio.sleep(1)
            if time.time() - self._start_time > 10:
                uptime = int(time.time() - self._start_time)
                logger.info(f"运行中: {uptime}s | 连接: {len(self._connections)}")
    
    def _generate_room_code(self) -> str:
        chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        return "".join(random.choice(chars) for _ in range(6))
    
    async def stop(self):
        """停止服务器"""
        self._running = False
    
    @property
    def room_code(self) -> str:
        return self._room_code

from ..config import print_banner
