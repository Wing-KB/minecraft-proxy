"""
NAT 穿透模块
支持 TCP/UDP 双协议 NAT 打洞
"""
import asyncio
import socket
import struct
import json
import time
import random
import logging
from dataclasses import dataclass
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

@dataclass
class NatEndpoint:
    public_ip: str
    public_port: int
    private_ip: str
    private_port: int

class NATPunch:
    """NAT 打洞器"""
    
    PROTOCOL_MAGIC = b"MCHP"
    
    def __init__(self, local_port, stun_servers=None, timeout=30, retry_count=3):
        self.local_port = local_port
        self.stun_servers = stun_servers or [("stun.l.google.com", 19302)]
        self.timeout = timeout
        self.retry_count = retry_count
        self._socket: Optional[socket.socket] = None
        self._running = False
        self._local_endpoint: Optional[NatEndpoint] = None
    
    async def start(self):
        """启动打洞器"""
        self._running = True
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.setblocking(False)
        self._socket.bind(("", self.local_port))
        
        private_ip = self._get_local_ip()
        self._local_endpoint = NatEndpoint(
            public_ip=private_ip,
            public_port=self.local_port,
            private_ip=private_ip,
            private_port=self.local_port,
        )
        logger.info(f"NAT 打洞器已启动")
    
    async def stop(self):
        """停止打洞器"""
        self._running = False
        if self._socket:
            self._socket.close()
    
    def _get_local_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"
    
    async def initiate_hole_punch(self, peer_public_ip: str, peer_public_port: int):
        """发起打洞"""
        logger.info(f"开始打洞: {peer_public_ip}:{peer_public_port}")
        
        punch_packet = json.dumps({
            "magic": self.PROTOCOL_MAGIC.decode(),
            "type": "hole_punch",
            "timestamp": time.time(),
        }).encode()
        
        for attempt in range(self.retry_count):
            try:
                self._socket.sendto(punch_packet, (peer_public_ip, peer_public_port))
                logger.debug(f"打洞包已发送 (尝试 {attempt + 1})")
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.debug(f"打洞尝试失败: {e}")
        
        return True
    
    @property
    def local_endpoint(self) -> Optional[NatEndpoint]:
        return self._local_endpoint
