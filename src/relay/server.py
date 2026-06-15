"""
中继服务器模块
用于 NAT 无法穿透时的Fallback方案
"""
import asyncio
import socket
import struct
import json
import time
import uuid
import logging
from typing import Dict, Set, Optional

logger = logging.getLogger(__name__)

class RelayServer:
    """中继服务器"""
    
    PROTOCOL_MAGIC = b"MRPX"
    
    def __init__(self, host="0.0.0.0", port=25566, max_connections=32):
        self.host = host
        self.port = port
        self.max_connections = max_connections
        self._running = False
        self._tcp_server: Optional[asyncio.Server] = None
        self._peers: Dict = {}
        self._rooms: Dict[str, Set] = {}
    
    async def start(self):
        """启动中继服务器"""
        self._running = True
        self._tcp_server = await asyncio.start_server(
            self._handle_connection, self.host, self.port
        )
        logger.info(f"中继服务器已启动: {self.host}:{self.port}")
    
    async def stop(self):
        """停止中继服务器"""
        self._running = False
        if self._tcp_server:
            self._tcp_server.close()
            await self._tcp_server.wait_closed()
    
    async def _handle_connection(self, reader, writer):
        """处理连接"""
        addr = writer.get_extra_info("peername")
        peer_id = str(uuid.uuid4())[:8]
        logger.info(f"新连接: {addr} (ID: {peer_id})")
        
        try:
            while self._running:
                data = await reader.read(4096)
                if not data:
                    break
                # 处理数据...
        except Exception as e:
            logger.debug(f"连接异常: {e}")
        finally:
            if peer_id in self._peers:
                del self._peers[peer_id]
            writer.close()
    
    def _generate_room_code(self) -> str:
        chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        return "".join(random.choice(chars) for _ in range(6))
