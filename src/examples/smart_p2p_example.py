"""
智能 P2P 使用示例

运行方式:
    # 房主
    python -m src.examples.smart_p2p_example --mode host --relay your-server.com --port 25566
    
    # 玩家
    python -m src.examples.smart_p2p_example --mode player --relay your-server.com --port 25566 --room-code ABC123
"""
import asyncio
import argparse
import logging
import sys
import os

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.p2p.smart_p2p import SmartP2P, RelayServerExtended

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


async def run_host(relay_host: str, relay_port: int, udp_port: int):
    """运行房主"""
    logger.info("=" * 50)
    logger.info("  Minecraft 智能 P2P - 房主模式")
    logger.info("=" * 50)
    
    p2p = SmartP2P(
        local_udp_port=udp_port,
        relay_host=relay_host,
        relay_port=relay_port,
        is_host=True,
        peer_name="房主"
    )
    
    # 设置回调
    async def on_udp_connected(addr):
        logger.info("🎉 UDP 直连成功！")
        logger.info(f"   目标地址: {addr}")
        logger.info("   正在关闭 TCP 中继，节省网费中...")
    
    p2p.on_udp_connected = on_udp_connected
    
    logger.info(f"正在连接中继服务器 {relay_host}:{relay_port}...")
    
    success = await p2p.connect_via_relay()
    
    if success:
        logger.info("✅ 连接成功！等待玩家加入...")
        # 保持运行
        await asyncio.sleep(3600)
    else:
        logger.error("❌ 连接失败，切换到纯中继模式")
        # 可以在这里降级到陶瓦协议


async def run_player(relay_host: str, relay_port: int, room_code: str, udp_port: int):
    """运行玩家"""
    logger.info("=" * 50)
    logger.info("  Minecraft 智能 P2P - 玩家模式")
    logger.info("=" * 50)
    
    p2p = SmartP2P(
        local_udp_port=udp_port,
        relay_host=relay_host,
        relay_port=relay_port,
        is_host=False,
        room_code=room_code,
        peer_name="玩家"
    )
    
    # 设置回调
    async def on_udp_connected(addr):
        logger.info("🎉 UDP 直连成功！")
        logger.info(f"   直连到: {addr}")
        logger.info("   已断开 TCP 中继，省网费！✓")
    
    p2p.on_udp_connected = on_udp_connected
    
    logger.info(f"正在连接房间 {room_code}...")
    
    success = await p2p.connect_via_relay()
    
    if success:
        logger.info("✅ 已连接到房主！")
        # 保持运行
        await asyncio.sleep(3600)
    else:
        logger.error("❌ 无法直连，等待房主开启中继...")


async def run_relay_server(host: str, port: int):
    """运行智能中继服务器"""
    logger.info("=" * 50)
    logger.info("  Minecraft 智能中继服务器")
    logger.info("=" * 50)
    
    server = RelayServerExtended(host=host, port=port)
    await server.start()
    
    logger.info(f"服务器运行中: {host}:{port}")
    logger.info("按 Ctrl+C 停止")
    
    try:
        await asyncio.sleep(3600 * 24)
    except KeyboardInterrupt:
        logger.info("正在停止服务器...")
        await server.stop()


def main():
    parser = argparse.ArgumentParser(description="Minecraft 智能 P2P 示例")
    parser.add_argument("--mode", choices=["host", "player", "relay"], required=True,
                        help="运行模式: host(房主), player(玩家), relay(中继服务器)")
    parser.add_argument("--relay", default="127.0.0.1",
                        help="中继服务器地址")
    parser.add_argument("--port", type=int, default=25566,
                        help="中继服务器端口")
    parser.add_argument("--room-code", 
                        help="房间码 (玩家模式)")
    parser.add_argument("--udp-port", type=int, default=25567,
                        help="本地 UDP 端口")
    
    args = parser.parse_args()
    
    if args.mode == "relay":
        asyncio.run(run_relay_server("0.0.0.0", args.port))
    elif args.mode == "host":
        asyncio.run(run_host(args.relay, args.port, args.udp_port))
    elif args.mode == "player":
        if not args.room_code:
            parser.error("玩家模式需要指定 --room-code")
        asyncio.run(run_player(args.relay, args.port, args.room_code, args.udp_port))


if __name__ == "__main__":
    main()
