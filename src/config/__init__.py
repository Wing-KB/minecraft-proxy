"""配置管理模块"""
import yaml
from dataclasses import dataclass, field

@dataclass
class NATConfig:
    enabled: bool = True
    stun_servers: list = field(default_factory=lambda: ["stun.l.google.com:19302"])
    timeout: int = 30
    retry_count: int = 3
    keepalive_interval: int = 25

@dataclass
class VoiceConfig:
    enabled: bool = True
    codec: str = "opus"
    sample_rate: int = 48000
    udp_port: int = 24454

@dataclass
class ProxyConfig:
    nat: NATConfig = field(default_factory=NATConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)

def load_config(path="config/config.yaml"):
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return ProxyConfig(
            nat=NATConfig(**data.get("nat", {})),
            voice=VoiceConfig(**data.get("voice", {})),
        )
    except:
        return ProxyConfig()

def print_banner():
    print("""
    ╔══════════════════════════════════════════════════════╗
    ║         Minecraft Cross-Region Proxy v1.0            ║
    ║     支持 PCLCE / HMCL / FCL / ZCL 陶瓦联机协议         ║
    ╚══════════════════════════════════════════════════════╝
    """)
