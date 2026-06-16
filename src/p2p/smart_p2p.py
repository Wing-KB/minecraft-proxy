"""
智能 P2P 连接模块
- 先用 TCP 中继交换信息
- 检测到双方都是自己的客户端后
- 自动升级到 UDP 直连，省网费
"""
import asyncio
import socket
import struct
import json
import time
import random
import hashlib
import logging
from dataclasses import dataclass
from typing import Optional, Callable, Tuple
from enum import Enum

logger = logging.getLogger(__name__)

class ConnectionState(Enum):
    """连接状态"""
    INIT = "init"
    TCP_CONNECTED = "tcp_connected"
    HANDSHAKE_SENT = "handshake_sent"
    HANDSHAKE_RECEIVED = "handshake_received"
    PUNCHING = "punching"
    UDP_CONNECTED = "udp_connected"
    FAILED = "failed"


@dataclass
class PeerInfo:
    """对端信息"""
    peer_id: str
    public_ip: str
    public_port: int
    private_ip: str
    private_port: int
    handshake_token: bytes
    is_our_client: bool = False


class SmartP2P:
    """
    智能 P2P 连接器
    
    工作流程:
    1. TCP 连接到中继服务器
    2. 发送自定义握手包 (陶瓦不认识，但我们的客户端认得)
    3. 等待对方握手完成
    4. 同时开始 UDP 打洞
    5. 打洞成功 → 切换到 UDP 直连
    6. 关闭 TCP 连接，省网费！
    """
    
    # 魔数: "MCPX" = Minecraft Proxy eXtended
    MAGIC = b"MCPX"
    VERSION = 1
    
    # 握手超时 (秒)
    HANDSHAKE_TIMEOUT = 10
    PUNCH_TIMEOUT = 15
    
    def __init__(self, local_udp_port: int = 0, relay_host: str = "", 
                 relay_port: int = 25566, is_host: bool = False,
                 room_code: str = "", peer_name: str = ""):
        self.local_udp_port = local_udp_port
        self.relay_host = relay_host
        self.relay_port = relay_port
        self.is_host = is_host
        self.room_code = room_code
        self.peer_name = peer_name
        
        # 生成自己的握手 token
        self.my_token = self._generate_token()
        
        # 网络资源
        self._tcp_reader: Optional[asyncio.StreamReader] = None
        self._tcp_writer: Optional[asyncio.StreamWriter] = None
        self._udp_socket: Optional[socket.socket] = None
        
        # 状态
        self.state = ConnectionState.INIT
        self.peer_info: Optional[PeerInfo] = None
        self._punch_task: Optional[asyncio.Task] = None
        self._tcp_reader_task: Optional[asyncio.Task] = None
        
        # 回调
        self.on_udp_connected: Optional[Callable] = None
        self.on_failed: Optional[Callable] = None
        
        # UDP 直连成功后的回调
        self.udp_connected_event = asyncio.Event()
    
    def _generate_token(self) -> bytes:
        """生成随机握手 token"""
        data = f"{time.time()}-{random.random()}-{self.peer_name}".encode()
        return hashlib.sha256(data).digest()[:16]
    
    def _get_local_ip(self) -> Tuple[str, int]:
        """获取本机 IP"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip, 0  # 端口后面绑定时才知道
        except:
            return "127.0.0.1", 0
    
    async def connect_via_relay(self) -> bool:
        """
        通过中继服务器建立连接
        """
        try:
            # 1. TCP 连接到中继服务器
            logger.info(f"[TCP] 连接到中继服务器 {self.relay_host}:{self.relay_port}")
            self._tcp_reader, self._tcp_writer = await asyncio.wait_for(
                asyncio.open_connection(self.relay_host, self.relay_port),
                timeout=10
            )
            self.state = ConnectionState.TCP_CONNECTED
            
            # 2. 获取本机 NAT 信息 (通过 STUN 或 connect)
            local_ip, _ = self._get_local_ip()
            
            # 3. 发送自定义握手包
            await self._send_handshake(local_ip, self.local_udp_port)
            self.state = ConnectionState.HANDSHAKE_SENT
            
            # 4. 启动 UDP 打洞
            await self._start_udp_punch()
            
            # 5. 等待对方握手和 UDP 连接
            await self._wait_for_peer_handshake()
            
            return True
            
        except asyncio.TimeoutError:
            logger.warning("[TCP] 连接超时")
            self.state = ConnectionState.FAILED
            return False
        except Exception as e:
            logger.error(f"[TCP] 连接失败: {e}")
            self.state = ConnectionState.FAILED
            return False
    
    async def _send_handshake(self, local_ip: str, udp_port: int):
        """
        发送自定义握手包
        
        格式:
        ┌────────┬────────┬────────┬────────┬────────┬────────┬────────┬────────┐
        │ MAGIC (4) │ VERSION(1) │  TYPE   │ TOKEN(16) │  IP (4)   │ PORT (2) │ NAME(~) │
        │  "MCPX"   │    1     │ 0x01   │  随机   │ 公网IP  │ UDP端口 │ 昵称   │
        └────────┴────────┴────────┴────────┴────────┴────────┴────────┴────────┘
        """
        name_bytes = self.peer_name.encode("utf-8")[:32]
        
        # 构造握手包
        handshake = struct.pack(
            ">4sBBB 16s 4s H",
            self.MAGIC,           # 魔数 "MCPX"
            self.VERSION,         # 版本
            0x01 if self.is_host else 0x02,  # 类型: 0x01=房主, 0x02=玩家
            len(name_bytes),      # 昵称长度
            self.my_token,        # 16字节 token
            socket.inet_aton(local_ip),  # IP
            udp_port              # UDP 端口
        ) + name_bytes
        
        logger.info(f"[HANDSHAKE] 发送握手包 (token={self.my_token.hex()[:8]}...)")
        self._tcp_writer.write(handshake)
        await self._tcp_writer.drain()
    
    async def _receive_handshake(self) -> Optional[dict]:
        """
        接收并解析对方的握手包
        """
        try:
            # 先读取固定头部长度
            header = await asyncio.wait_for(
                self._tcp_reader.readexactly(26),
                timeout=self.HANDSHAKE_TIMEOUT
            )
            
            magic, version, msg_type, name_len, token, ip, port = struct.unpack(
                ">4sBBB 16s 4s H", header
            )
            
            # 验证魔数
            if magic != self.MAGIC:
                logger.warning(f"[HANDSHAKE] 对方不是我们的客户端 (magic={magic})")
                return None
            
            # 读取昵称
            name = await self._tcp_reader.readexactly(name_len)
            name = name.decode("utf-8", errors="ignore")
            
            peer_ip = socket.inet_ntoa(ip)
            
            peer_info = {
                "type": "host" if msg_type == 0x01 else "player",
                "token": token.hex(),
                "public_ip": peer_ip,
                "public_port": port,
                "name": name
            }
            
            logger.info(f"[HANDSHAKE] 收到对方握手: {peer_info}")
            return peer_info
            
        except asyncio.TimeoutError:
            logger.warning("[HANDSHAKE] 等待对方握手超时")
            return None
        except Exception as e:
            logger.error(f"[HANDSHAKE] 接收握手失败: {e}")
            return None
    
    async def _start_udp_punch(self):
        """启动 UDP 打洞"""
        self._punch_task = asyncio.create_task(self._udp_punch_loop())
    
    async def _udp_punch_loop(self):
        """
        UDP 打洞循环
        
        策略:
        1. 绑定 UDP 端口
        2. 持续向对方公网地址发送打洞包
        3. 同时监听对方发来的包
        4. 收到对方包 → 打洞成功！
        """
        try:
            self._udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._udp_socket.setblocking(False)
            self._udp_socket.bind(("", self.local_udp_port))
            
            # 获取实际绑定的端口
            _, actual_port = self._udp_socket.getsockname()
            if self.local_udp_port == 0:
                self.local_udp_port = actual_port
                logger.info(f"[UDP] 绑定到端口 {actual_port}")
            
            # 等待获取对方地址
            while not self.peer_info and self.state != ConnectionState.UDP_CONNECTED:
                await asyncio.sleep(0.1)
            
            if not self.peer_info:
                return
            
            target_ip = self.peer_info["public_ip"]
            target_port = self.peer_info["public_port"]
            
            logger.info(f"[UDP] 开始打洞 -> {target_ip}:{target_port}")
            self.state = ConnectionState.PUNCHING
            
            punch_data = struct.pack(
                ">4s B 16s",
                self.MAGIC,
                0x10,  # 打洞包类型
                self.my_token
            )
            
            # 持续打洞，直到收到对方包或超时
            deadline = time.time() + self.PUNCH_TIMEOUT
            
            while time.time() < deadline and self.state != ConnectionState.UDP_CONNECTED:
                try:
                    self._udp_socket.sendto(punch_data, (target_ip, target_port))
                    logger.debug(f"[UDP] 发送打洞包 -> {target_ip}:{target_port}")
                except Exception as e:
                    logger.debug(f"[UDP] 发送失败: {e}")
                
                # 尝试接收
                try:
                    data, addr = self._udp_socket.recvfrom(1024)
                    if self._verify_punch_response(data):
                        logger.info(f"[UDP] 打洞成功！直连 {addr}")
                        self.state = ConnectionState.UDP_CONNECTED
                        self.udp_connected_event.set()
                        await self._cleanup_tcp()
                        if self.on_udp_connected:
                            await self.on_udp_connected(addr)
                        return
                except BlockingIOError:
                    pass
                
                await asyncio.sleep(0.2)
            
            logger.warning("[UDP] 打洞超时，切换到中继模式")
            self.state = ConnectionState.FAILED
            if self.on_failed:
                self.on_failed()
                
        except Exception as e:
            logger.error(f"[UDP] 打洞异常: {e}")
            self.state = ConnectionState.FAILED
    
    def _verify_punch_response(self, data: bytes) -> bool:
        """验证打洞响应"""
        if len(data) < 21:
            return False
        magic, msg_type, token = struct.unpack(">4s B 16s", data[:21])
        return magic == self.MAGIC and token == self.my_token
    
    async def _wait_for_peer_handshake(self):
        """等待并处理对方握手"""
        peer_info = await self._receive_handshake()
        if peer_info:
            self.peer_info = PeerInfo(
                peer_id=peer_info["token"],
                public_ip=peer_info["public_ip"],
                public_port=peer_info["public_port"],
                private_ip=peer_info["public_ip"],
                private_port=peer_info["public_port"],
                handshake_token=peer_info["token"].encode(),
                is_our_client=True
            )
            self.state = ConnectionState.HANDSHAKE_RECEIVED
            logger.info(f"[P2P] 双方都是自己人，开始打洞！")
        else:
            logger.warning("[P2P] 对方不是我们的客户端，使用陶瓦协议")
    
    async def _cleanup_tcp(self):
        """清理 TCP 连接"""
        if self._tcp_writer:
            try:
                self._tcp_writer.close()
                await asyncio.wait_for(self._tcp_writer.wait_closed(), timeout=1)
            except:
                pass
        if self._tcp_reader_task:
            self._tcp_reader_task.cancel()
        logger.info("[TCP] 已断开中继连接，节省流量！")
    
    async def disconnect(self):
        """断开所有连接"""
        if self._punch_task:
            self._punch_task.cancel()
        await self._cleanup_tcp()
        if self._udp_socket:
            self._udp_socket.close()
        self.state = ConnectionState.INIT


class RelayServerExtended:
    """
    扩展版中继服务器
    支持智能握手和 UDP 打洞协调
    """
    
    MAGIC = b"MCPX"
    
    def __init__(self, host="0.0.0.0", port=25566):
        self.host = host
        self.port = port
        self._running = False
        self._server: Optional[asyncio.Server] = None
        
        # 房间管理
        self._rooms: dict = {}  # room_code -> {host: {...}, player: {...}}
        self._waiting_hosts: dict = {}  # host_id -> room_info
        
        # UDP 打洞协调
        self._stun_server = None  # STUN 服务器地址
        
    async def start(self):
        """启动扩展中继服务器"""
        self._running = True
        self._server = await asyncio.start_server(
            self._handle_connection, self.host, self.port
        )
        logger.info(f"[RELAY] 扩展中继服务器已启动: {self.host}:{self.port}")
        logger.info("[RELAY] 支持智能握手和 UDP 打洞协调")
    
    async def stop(self):
        """停止服务器"""
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
    
    async def _handle_connection(self, reader, writer):
        """处理连接"""
        addr = writer.get_extra_info("peername")
        logger.info(f"[RELAY] 新连接: {addr}")
        
        try:
            # 接收握手
            header = await asyncio.wait_for(
                reader.readexactly(26), timeout=10
            )
            
            magic, version, msg_type, name_len, token, ip, port = struct.unpack(
                ">4sBBB 16s 4s H", header
            )
            
            # 检查魔数
            if magic != self.MAGIC:
                # 不是我们的客户端，降级到普通陶瓦协议处理
                logger.info(f"[RELAY] 陶瓦客户端连接 {addr}")
                await self._handle_taowa_client(reader, writer, addr)
                return
            
            # 我们的客户端
            name = await reader.readexactly(name_len)
            peer_ip = socket.inet_ntoa(ip)
            peer_info = {
                "addr": addr,
                "writer": writer,
                "type": "host" if msg_type == 0x01 else "player",
                "token": token.hex(),
                "public_ip": peer_ip,
                "public_port": port,
                "name": name.decode("utf-8", errors="ignore")
            }
            
            logger.info(f"[RELAY] 收到握手: {peer_info['name']} ({peer_info['type']})")
            
            # 处理配对
            await self._handle_smart_pairing(peer_info)
            
        except asyncio.TimeoutError:
            logger.warning(f"[RELAY] {addr} 握手超时")
        except Exception as e:
            logger.error(f"[RELAY] 处理异常: {e}")
        finally:
            writer.close()
    
    async def _handle_smart_pairing(self, peer_info: dict):
        """
        智能配对逻辑
        
        1. 房主进来 → 等待玩家
        2. 玩家进来 → 找配对的房主，交换双方信息，触发打洞
        """
        if peer_info["type"] == "host":
            # 房主：记录并等待玩家
            host_id = peer_info["token"]
            self._waiting_hosts[host_id] = peer_info
            logger.info(f"[RELAY] 房主等待中: {host_id}")
            
            # TODO: 房主可以设置房间码
            # 等待玩家连接...
            
        else:
            # 玩家：找配对的房主
            # TODO: 这里需要房间码匹配逻辑
            for host_id, host_info in list(self._waiting_hosts.items()):
                # 找到房主，交换信息并触发打洞
                logger.info(f"[RELAY] 配对成功! {host_info['name']} <-> {peer_info['name']}")
                
                # 通知房主有玩家来了（带玩家信息）
                self._notify_host(host_info, peer_info)
                
                # 通知玩家房主信息
                self._notify_player(peer_info, host_info)
                
                # 从等待列表移除
                del self._waiting_hosts[host_id]
                break
    
    def _notify_host(self, host_info: dict, player_info: dict):
        """通知房主有玩家加入"""
        # 发送玩家信息给房主
        notify_data = struct.pack(
            ">4s B 16s 4s H",
            self.MAGIC,
            0x20,  # 玩家加入通知
            player_info["token"].encode(),
            socket.inet_aton(player_info["public_ip"]),
            player_info["public_port"]
        )
        try:
            host_info["writer"].write(notify_data)
        except:
            pass
    
    def _notify_player(self, player_info: dict, host_info: dict):
        """通知玩家房主信息"""
        notify_data = struct.pack(
            ">4s B 16s 4s H",
            self.MAGIC,
            0x21,  # 房主信息通知
            host_info["token"].encode(),
            socket.inet_aton(host_info["public_ip"]),
            host_info["public_port"]
        )
        try:
            player_info["writer"].write(notify_data)
        except:
            pass
    
    async def _handle_taowa_client(self, reader, writer, addr):
        """处理普通陶瓦客户端（降级模式）"""
        # 这里保持原有的陶瓦协议处理
        logger.info(f"[RELAY] 陶瓦客户端使用中继模式")
        # ... 原有逻辑
        pass
