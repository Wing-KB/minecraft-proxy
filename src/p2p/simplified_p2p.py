"""
智能联机整合示例

展示如何根据对方客户端类型决定连接方式：
- 陶瓦联机 → 纯 TCP 中继
- 自己的客户端 → TCP + UDP 语音
"""
import asyncio
import socket
import struct
import logging
from dataclasses import dataclass
from typing import Optional

from .protocol_detector import ClientType, ProtocolDetector, UDPSpeechChannel, SmartConnection

logger = logging.getLogger(__name__)


@dataclass
class PeerInfo:
    """对端信息"""
    ip: str
    voice_port: int
    client_type: ClientType


class SimplifiedSmartP2P:
    """
    简化版智能 P2P 连接
    
    流程：
    1. TCP 连接到中继服务器
    2. 发送握手（包含自己的类型和语音端口）
    3. 接收对方握手，检测对方类型
    4. 如果是自己客户端 → 同时开启 UDP 语音
    5. 如果是陶瓦 → 仅 TCP 中继
    """
    
    MAGIC = b"MCPX"
    VOICE_MAGIC = b"MCPV"
    
    def __init__(self, name: str = "Player", voice_port: int = 24454):
        self.name = name
        self.voice_port = voice_port
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._voice_channel: Optional[UDPSpeechChannel] = None
        self.peer: Optional[PeerInfo] = None
    
    async def connect_to_relay(self, relay_host: str, relay_port: int, 
                                is_host: bool = False) -> bool:
        """
        连接到中继服务器
        
        Args:
            relay_host: 中继服务器地址
            relay_port: 中继服务器端口
            is_host: 是否是房主
        """
        try:
            # 1. TCP 连接
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(relay_host, relay_port),
                timeout=10
            )
            logger.info(f"[TCP] 已连接到 {relay_host}:{relay_port}")
            
            # 2. 发送握手
            await self._send_handshake(is_host)
            
            # 3. 接收对方握手
            self.peer = await self._receive_peer_handshake()
            
            if not self.peer:
                logger.warning("[TCP] 未收到对方握手")
                return False
            
            # 4. 根据对方类型决定是否开启语音
            if self.peer.client_type == ClientType.OUR_CLIENT:
                logger.info("[SMART] 对方是自己人，开启 UDP 语音...")
                await self._start_voice_channel()
            else:
                logger.info("[SMART] 对方是陶瓦联机，使用 TCP 中继")
            
            return True
            
        except Exception as e:
            logger.error(f"[TCP] 连接失败: {e}")
            return False
    
    async def _send_handshake(self, is_host: bool):
        """发送握手包"""
        # 握手格式:
        # MAGIC(4) + TYPE(1) + NAME_LEN(1) + NAME(N) + VOICE_PORT(2)
        name_bytes = self.name.encode("utf-8")[:32]
        
        handshake = struct.pack(
            ">4s BB B",
            self.MAGIC,
            0x01 if is_host else 0x02,  # 0x01=房主, 0x02=玩家
            len(name_bytes)
        ) + name_bytes + struct.pack(">H", self.voice_port)
        
        logger.info(f"[HANDSHAKE] 发送: name={self.name}, voice_port={self.voice_port}")
        self._writer.write(handshake)
        await self._writer.drain()
    
    async def _receive_peer_handshake(self) -> Optional[PeerInfo]:
        """接收并解析对方握手"""
        try:
            # 先读 MAGIC + TYPE + NAME_LEN
            header = await asyncio.wait_for(
                self._reader.readexactly(6), timeout=10
            )
            magic, peer_type, name_len = struct.unpack(">4s BB", header)
            
            # 检测魔数
            client_type = ProtocolDetector.detect(magic)
            
            # 读取昵称和语音端口
            rest = await asyncio.wait_for(
                self._reader.readexactly(name_len + 2), timeout=5
            )
            name = rest[:name_len].decode("utf-8", errors="ignore")
            voice_port = struct.unpack(">H", rest[name_len:])[0]
            
            logger.info(f"[HANDSHAKE] 收到: name={name}, voice={voice_port}, type={client_type.value}")
            
            return PeerInfo(
                ip="",  # TCP 连接已知对方 IP
                voice_port=voice_port,
                client_type=client_type
            )
            
        except asyncio.TimeoutError:
            logger.warning("[HANDSHAKE] 接收超时")
            return None
        except Exception as e:
            logger.error(f"[HANDSHAKE] 解析失败: {e}")
            return None
    
    async def _start_voice_channel(self):
        """开启 UDP 语音通道"""
        if not self.peer:
            return
        
        # 获取对方的 IP（从 TCP 连接）
        if self._writer:
            peer_addr = self._writer.get_extra_info("peername")
            peer_ip = peer_addr[0] if peer_addr else ""
        else:
            peer_ip = ""
        
        self._voice_channel = UDPSpeechChannel(
            local_port=self.voice_port,
            peer_ip=peer_ip,
            peer_port=self.peer.voice_port
        )
        
        await self._voice_channel.start()
        logger.info("[VOICE] ✓ UDP 语音通道已开启！")
    
    async def send_voice(self, audio_data: bytes):
        """发送语音数据"""
        if self._voice_channel:
            await self._voice_channel.send_audio(audio_data)
    
    async def disconnect(self):
        """断开所有连接"""
        if self._voice_channel:
            await self._voice_channel.stop()
        
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
        
        logger.info("[CLEANUP] 已断开所有连接")


# ============ 简化版中继服务器 ============

class SimplifiedRelayServer:
    """
    简化版智能中继服务器
    
    自动识别客户端类型并路由
    """
    
    MAGIC = b"MCPX"
    
    def __init__(self, host="0.0.0.0", port=25566, voice_port=24454):
        self.host = host
        self.port = port
        self.voice_port = voice_port
        self._running = False
        self._server: Optional[asyncio.Server] = None
        
        # 等待配对的房主
        self._waiting_hosts = {}  # token -> host_info
    
    async def start(self):
        """启动服务器"""
        self._running = True
        self._server = await asyncio.start_server(
            self._handle_connection, self.host, self.port
        )
        logger.info(f"[RELAY] 智能中继已启动: {self.host}:{self.port}")
        logger.info("[RELAY] 支持自动检测: 自家客户端用 UDP 语音，陶瓦用 TCP 中继")
    
    async def stop(self):
        """停止服务器"""
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
    
    async def _handle_connection(self, reader, writer):
        """处理连接"""
        addr = writer.get_extra_info("peername")
        
        try:
            # 读取握手
            header = await asyncio.wait_for(reader.readexactly(6), timeout=10)
            magic, client_type, name_len = struct.unpack(">4s BB", header)
            
            # 检测类型
            our_client = (magic == self.MAGIC)
            
            # 读取剩余信息
            rest = await asyncio.wait_for(reader.readexactly(name_len + 2), timeout=5)
            name = rest[:name_len].decode("utf-8", errors="ignore")
            voice_port = struct.unpack(">H", rest[name_len:])[0]
            
            logger.info(f"[RELAY] {name} ({addr}) - {'自家客户端' if our_client else '陶瓦联机'}")
            
            if our_client:
                await self._handle_our_client(reader, writer, client_type, name, voice_port, addr)
            else:
                await self._handle_taowa_client(reader, writer, addr)
                
        except Exception as e:
            logger.error(f"[RELAY] 处理异常: {e}")
        finally:
            writer.close()
    
    async def _handle_our_client(self, reader, writer, client_type, name, voice_port, addr):
        """处理自家客户端"""
        if client_type == 0x01:  # 房主
            # 保存房主信息，等待玩家
            token = f"{addr[0]}:{voice_port}"
            self._waiting_hosts[token] = {
                "writer": writer,
                "name": name,
                "voice_port": voice_port,
                "addr": addr
            }
            logger.info(f"[RELAY] 房主 '{name}' 等待玩家加入...")
            
            # 房主保持连接
            try:
                while self._running:
                    await asyncio.sleep(1)
            except:
                pass
                
        else:  # 玩家
            # 找可用的房主配对
            if self._waiting_hosts:
                host_token = list(self._waiting_hosts.keys())[0]
                host_info = self._waiting_hosts.pop(host_token)
                
                # 交换双方信息
                peer_ip = addr[0]
                
                # 通知房主玩家信息
                self._notify_peer(
                    host_info["writer"],
                    0x10,  # 玩家加入
                    name, voice_port, peer_ip
                )
                
                # 通知玩家房主信息
                self._notify_peer(
                    writer,
                    0x11,  # 房主信息
                    host_info["name"], host_info["voice_port"], host_info["addr"][0]
                )
                
                logger.info(f"[RELAY] 配对成功: {host_info['name']} <-> {name}")
                logger.info(f"[RELAY] 双方可开启 UDP 语音！")
            else:
                logger.info(f"[RELAY] 暂无房主，等待中...")
    
    def _notify_peer(self, writer, msg_type, name, voice_port, peer_ip):
        """通知对方信息"""
        name_bytes = name.encode("utf-8")[:32]
        data = struct.pack(">4s BB B", self.MAGIC, msg_type, len(name_bytes))
        data += name_bytes + struct.pack(">H 4s", voice_port, socket.inet_aton(peer_ip))
        try:
            writer.write(data)
        except:
            pass
    
    async def _handle_taowa_client(self, reader, writer, addr):
        """处理陶瓦客户端 - 仅 TCP 中继"""
        logger.info(f"[RELAY] 陶瓦联机使用 TCP 中继模式")
        # 陶瓦协议直接透传，不需要额外处理
        try:
            while self._running:
                data = await reader.read(4096)
                if not data:
                    break
                # 这里应该转发到其他陶瓦客户端
        except:
            pass
