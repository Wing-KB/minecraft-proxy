"""
中继服务器模块
支持智能握手和 UDP 打洞协调
"""
import asyncio
import socket
import struct
import random
import logging
from typing import Dict, Set, Optional

from ..p2p.smart_p2p import RelayServerExtended, SmartP2P

logger = logging.getLogger(__name__)


class RelayServer:
    """
    中继服务器 (兼容旧接口)
    
    新版本使用 RelayServerExtended 提供智能握手和 UDP 打洞支持
    """
    
    PROTOCOL_MAGIC = b"MRPX"
    
    def __init__(self, host="0.0.0.0", port=25566, max_connections=32):
        self.host = host
        self.port = port
        self.max_connections = max_connections
        self._running = False
        self._server: Optional[asyncio.Server] = None
        self._extended_server: Optional[RelayServerExtended] = None
        
        # 兼容旧属性
        self._peers: Dict = {}
        self._rooms: Dict[str, Set] = {}
        
        # 是否启用智能模式
        self.smart_mode = True
    
    async def start(self):
        """启动中继服务器"""
        self._running = True
        
        if self.smart_mode:
            # 使用扩展版服务器（支持智能握手）
            self._extended_server = RelayServerExtended(self.host, self.port)
            await self._extended_server.start()
            logger.info(f"[RELAY] 智能中继服务器已启动: {self.host}:{self.port}")
            logger.info("[RELAY] ✓ 智能握手  ✓ UDP 打洞协调  ✓ 自动省网费")
        else:
            # 使用旧版服务器（纯中继）
            self._server = await asyncio.start_server(
                self._handle_connection, self.host, self.port
            )
            logger.info(f"[RELAY] 基础中继服务器已启动: {self.host}:{self.port}")
    
    async def stop(self):
        """停止服务器"""
        self._running = False
        if self._extended_server:
            await self._extended_server.stop()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
    
    async def _handle_connection(self, reader, writer):
        """处理连接 (旧版)"""
        addr = writer.get_extra_info("peername")
        
        try:
            # 检查是否是智能客户端
            peek_data = await asyncio.wait_for(reader.readexactly(5), timeout=2)
            
            if peek_data[:4] == SmartP2P.MAGIC:
                logger.info(f"[RELAY] 检测到智能客户端 {addr}，使用增强模式")
                # 智能客户端由 RelayServerExtended 处理
                # 这里复用同一个端口，由 Extended 处理
            else:
                # 普通陶瓦客户端
                logger.info(f"[RELAY] 普通陶瓦客户端 {addr}")
                await self._handle_taowa_client(reader, writer, addr)
                
        except asyncio.TimeoutError:
            logger.debug(f"[RELAY] {addr} 协议检测超时")
        except Exception as e:
            logger.error(f"[RELAY] 连接处理异常: {e}")
        finally:
            writer.close()
    
    async def _handle_taowa_client(self, reader, writer, addr):
        """处理普通陶瓦客户端"""
        try:
            while self._running:
                data = await reader.read(4096)
                if not data:
                    break
                # 处理陶瓦协议数据...
        except Exception as e:
            logger.debug(f"[RELAY] 陶瓦连接异常: {e}")
    
    def _generate_room_code(self) -> str:
        chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        return "".join(random.choice(chars) for _ in range(6))
