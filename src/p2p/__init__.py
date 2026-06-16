"""
P2P 模块

包含:
- nat_punch: 基础 NAT 打洞
- protocol_detector: 协议检测（陶瓦 vs 自家客户端）
- simplified_p2p: 简化版智能 P2P（根据客户端类型决定连接方式）
"""
from .nat_punch import NATPunch, NatEndpoint
from .protocol_detector import (
    ClientType, 
    ProtocolDetector, 
    UDPSpeechChannel, 
    SmartConnection,
    RelayProtocolRouter
)
from .simplified_p2p import (
    SimplifiedSmartP2P,
    SimplifiedRelayServer
)

__all__ = [
    "NATPunch", "NatEndpoint",
    "ClientType", "ProtocolDetector", "UDPSpeechChannel", "SmartConnection", "RelayProtocolRouter",
    "SimplifiedSmartP2P", "SimplifiedRelayServer",
]
