#!/usr/bin/env python3
"""
Minecraft Cross-Region Proxy
Minecraft 异地联机工具
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Minecraft 异地联机工具")
    parser.add_argument("--gui", "-g", action="store_true", help="GUI 模式")
    parser.add_argument("--mode", choices=["server", "client"], help="运行模式")
    parser.add_argument("--port", type=int, default=25565, help="端口")
    parser.add_argument("--server", help="服务器地址")
    parser.add_argument("--code", help="房间码")
    parser.add_argument("--name", default="Player", help="玩家名称")
    args = parser.parse_args()
    
    if args.gui or args.mode is None:
        try:
            from src.ui.main_window import run_ui
            run_ui()
        except ImportError:
            print("错误: PyQt5 未安装，请运行: pip install PyQt5")
            sys.exit(1)
    else:
        from src.core.server import ProxyServer
        from src.core.client import ProxyClient
        import asyncio
        
        async def run():
            if args.mode == "server":
                server = ProxyServer(port=args.port, player_name=args.name)
                await server.start()
            else:
                client = ProxyClient(server_host=args.server or "127.0.0.1",
                                    player_name=args.name)
                await client.connect(args.code)
        
        asyncio.run(run())

if __name__ == "__main__":
    main()
