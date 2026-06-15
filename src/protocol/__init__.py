"""陶瓦协议模块"""
from .base import BaseProtocol, ProtocolType

__all__ = ["BaseProtocol", "ProtocolType"]

from enum import Enum

class ProtocolType(Enum):
    PCLCE = "pclce"
    HMCL = "hmcl"
    FCL = "fcl"
    ZCL = "zcl"

class BaseProtocol:
    """协议基类"""
    PROTOCOL_MAGIC = b"MCAT"
    
    def __init__(self):
        import uuid
        self.player_id = str(uuid.uuid4())
    
    def generate_room_code(self) -> str:
        import random
        chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        return "".join(random.choice(chars) for _ in range(6))
