#!/usr/bin/env python3
"""
Minecraft Cross-Region Proxy
=============================
Minecraft 异地联机工具
支持 PCLCE / HMCL / FCL / ZCL 陶瓦联机协议
"""

__version__ = "1.0.0"
__author__ = "KBWing"

from .core.server import ProxyServer
from .core.client import ProxyClient

__all__ = ["ProxyServer", "ProxyClient", "__version__"]
