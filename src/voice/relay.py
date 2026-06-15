"""
语音中继服务器
支持 UDP 语音数据传输 (Voice Chat Mod)
"""
import asyncio
import socket
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class VoiceRelayServer:
    """语音中继服务器"""
    
    PROTOCOL_MAGIC = b"VCAT"
    
    def __init__(self, host="0.0.0.0", port=24454):
        self.host = host
        self.port = port
        self._running = False
        self._socket: Optional[socket.socket] = None
        self._peers: Dict = {}
    
    async def start(self):
        """启动语音服务器"""
        self._running = True
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.setblocking(False)
        self._socket.bind((self.host, self.port))
        logger.info(f"语音中继服务器已启动: UDP {self.host}:{self.port}")
    
    async def stop(self):
        """停止服务器"""
        self._running = False
        if self._socket:
            self._socket.close()
