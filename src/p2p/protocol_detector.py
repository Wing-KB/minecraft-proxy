"""
智能协议检测和 UDP 语音模块

工作原理：
1. TCP 握手时检测对方是什么客户端
2. 如果是陶瓦联机 → 纯 TCP 中继
3. 如果是自己的客户端 → 额外开启 UDP 语音通道

语音 MOD (Voice Chat) 通常用同一个端口，所以直接复用即可
"""
import asyncio
import socket
import struct
import logging
from typing import Optional, Callable
from enum import Enum

logger = logging.getLogger(__name__)


class ClientType(Enum):
    """客户端类型"""
    UNKNOWN = "unknown"
    TAOWA = "taowa"          # 陶瓦联机
    OUR_CLIENT = "our_client"  # 自己的客户端


class ProtocolDetector:
    """
    协议检测器
    
    通过 TCP 握手包的前几个字节判断对方是什么客户端
    """
    
    # 我们的魔数
    OUR_MAGIC = b"MCPX"
    
    # 陶瓦联机的魔数 (PCLCE/HMCL/FCL/ZCL)
    TAOWA_MAGIC = b"\x0a\x00\x00\x00"  # 或其他已知的陶瓦魔数
    
    @classmethod
    def detect(cls, first_bytes: bytes) -> ClientType:
        """
        检测客户端类型
        
        Args:
            first_bytes: TCP 连接的前几个字节
            
        Returns:
            ClientType 枚举
        """
        if len(first_bytes) < 4:
            return ClientType.UNKNOWN
        
        # 检测我们的魔数
        if first_bytes[:4] == cls.OUR_MAGIC:
            return ClientType.OUR_CLIENT
        
        # 陶瓦联机有特定的握手特征
        # PCLCE 协议通常以特定字节开头
        if first_bytes[:2] in (b"\xFE", b"\xCA", b"\xCC"):
            return ClientType.TAOWA
        
        # 其他情况保守处理
        return ClientType.TAOWA


class UDPSpeechChannel:
    """
    UDP 语音通道
    
    用于自己客户端之间的语音通信
    陶瓦联机不需要这个
    """
    
    MAGIC = b"MCPV"  # Minecraft Voice Protocol
    
    def __init__(self, local_port: int, peer_ip: str, peer_port: int):
        self.local_port = local_port
        self.peer_ip = peer_ip
        self.peer_port = peer_port
        self._socket: Optional[socket.socket] = None
        self._running = False
        self._receive_task: Optional[asyncio.Task] = None
        
        # 回调
        self.on_audio_data: Optional[Callable[[bytes], None]] = None
    
    async def start(self) -> bool:
        """
        启动 UDP 语音通道
        
        Returns:
            是否启动成功
        """
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.setblocking(False)
            self._socket.bind(("", self.local_port))
            
            self._running = True
            self._receive_task = asyncio.create_task(self._receive_loop())
            
            logger.info(f"[VOICE] UDP 语音通道已开启 {self.local_port} -> {self.peer_ip}:{self.peer_port}")
            return True
            
        except Exception as e:
            logger.error(f"[VOICE] 启动 UDP 语音失败: {e}")
            return False
    
    async def stop(self):
        """停止语音通道"""
        self._running = False
        
        if self._receive_task:
            self._receive_task.cancel()
        
        if self._socket:
            self._socket.close()
        
        logger.info("[VOICE] UDP 语音通道已关闭")
    
    async def send_audio(self, audio_data: bytes):
        """
        发送音频数据
        
        封包格式:
        ┌────────┬────────┐
        │ MAGIC  │ DATA   │
        │ "MCPV" │ 音频   │
        └────────┴────────┘
        """
        if not self._socket or not self._running:
            return
        
        packet = self.MAGIC + audio_data
        try:
            self._socket.sendto(packet, (self.peer_ip, self.peer_port))
        except Exception as e:
            logger.debug(f"[VOICE] 发送音频失败: {e}")
    
    async def _receive_loop(self):
        """接收音频数据循环"""
        while self._running:
            try:
                data, addr = await asyncio.sock_recv(self._socket, 4096)
                
                # 验证魔数
                if len(data) > 4 and data[:4] == self.MAGIC:
                    audio_data = data[4:]
                    if self.on_audio_data:
                        self.on_audio_data(audio_data)
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"[VOICE] 接收音频异常: {e}")
            
            await asyncio.sleep(0)  # 让出控制权


class SmartConnection:
    """
    智能连接管理器
    
    根据对方客户端类型决定是否开启 UDP 语音
    """
    
    def __init__(self, voice_port: int = 24454):
        self.voice_port = voice_port
        self.client_type = ClientType.UNKNOWN
        self.voice_channel: Optional[UDPSpeechChannel] = None
        
        # 对方信息
        self.peer_ip = ""
        self.peer_voice_port = 0
    
    async def handle_tcp_handshake(self, first_bytes: bytes, 
                                    peer_info: Optional[dict] = None) -> ClientType:
        """
        处理 TCP 握手，检测客户端类型
        
        Args:
            first_bytes: TCP 握手的前几个字节
            peer_info: 解析出的对方信息（如果是我们自己的客户端）
            
        Returns:
            客户端类型
        """
        self.client_type = ProtocolDetector.detect(first_bytes)
        
        if self.client_type == ClientType.OUR_CLIENT and peer_info:
            # 保存对方信息，准备开启 UDP 语音
            self.peer_ip = peer_info.get("public_ip", "")
            self.peer_voice_port = peer_info.get("voice_port", self.voice_port)
            
            logger.info(f"[SMART] 检测到自己的客户端，准备开启语音...")
            
        elif self.client_type == ClientType.TAOWA:
            logger.info(f"[SMART] 检测到陶瓦联机，仅使用 TCP 中继")
        
        return self.client_type
    
    async def start_voice_if_needed(self) -> bool:
        """
        如果是自家客户端，开启 UDP 语音
        
        Returns:
            是否成功开启语音
        """
        if self.client_type != ClientType.OUR_CLIENT:
            logger.info("[SMART] 非自家客户端，跳过语音通道")
            return False
        
        if not self.peer_ip or not self.peer_voice_port:
            logger.warning("[SMART] 缺少对方语音信息，无法开启")
            return False
        
        self.voice_channel = UDPSpeechChannel(
            local_port=self.voice_port,
            peer_ip=self.peer_ip,
            peer_port=self.peer_voice_port
        )
        
        success = await self.voice_channel.start()
        
        if success:
            logger.info("[SMART] ✓ UDP 语音已开启！节省流量！")
        else:
            logger.warning("[SMART] UDP 语音开启失败")
        
        return success
    
    async def stop(self):
        """停止所有连接"""
        if self.voice_channel:
            await self.voice_channel.stop()
            self.voice_channel = None


# ============ 中继服务器端的协议检测 ============

class RelayProtocolRouter:
    """
    中继服务器协议路由器
    
    根据客户端类型分发到不同的处理逻辑
    """
    
    def __init__(self, taowa_handler, our_client_handler):
        """
        Args:
            taowa_handler: 陶瓦客户端处理器
            our_client_handler: 自家客户端处理器
        """
        self.taowa_handler = taowa_handler
        self.our_client_handler = our_client_handler
    
    async def route(self, reader, writer):
        """
        根据协议类型路由连接
        """
        addr = writer.get_extra_info("peername")
        
        try:
            # 读取握手包头部用于检测
            first_bytes = await asyncio.wait_for(
                reader.readexactly(4), timeout=5
            )
            
            client_type = ProtocolDetector.detect(first_bytes)
            
            logger.info(f"[RELAY] {addr} -> {client_type.value}")
            
            if client_type == ClientType.OUR_CLIENT:
                # 我们的客户端，支持 UDP 语音
                await self.our_client_handler.handle(reader, writer, first_bytes)
            else:
                # 陶瓦联机，纯 TCP 中继
                await self.taowa_handler.handle(reader, writer, first_bytes)
                
        except Exception as e:
            logger.error(f"[RELAY] 协议检测失败: {e}")
            writer.close()
