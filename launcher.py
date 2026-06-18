#!/usr/bin/env python3
"""
Minecraft Cross-Region Proxy
Minecraft 异地联机工具

用法:
  python launcher.py                          # GUI 模式（推荐）
  python launcher.py --relay-server           # 独立运行中继服务器
  python launcher.py --mode host              # 命令行房主
  python launcher.py --mode client            # 命令行玩家
  python launcher.py --terracotta            # 标记使用陶瓦联机
"""

import sys
import os
import asyncio
import argparse
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)


def main():
    parser = argparse.ArgumentParser(description="Minecraft 异地联机工具")
    parser.add_argument("--mode", choices=["host", "client"],
                        help="运行模式: host=房主, client=玩家")
    parser.add_argument("--relay-server", action="store_true",
                        help="启动独立中继服务器")
    parser.add_argument("--relay", default="",
                        help="中继服务器地址（host/client 模式必填）")
    parser.add_argument("--relay-port", type=int, default=25566,
                        help="中继服务器端口（默认 25566）")
    parser.add_argument("--mc-port", type=int, default=25565,
                        help="本地 Minecraft 端口（房主模式，默认 25565）")
    parser.add_argument("--local-port", type=int, default=25565,
                        help="本地监听端口（玩家模式，默认 25565）")
    parser.add_argument("--code", default="",
                        help="房间码（玩家模式必填，支持 6 位或陶瓦格式）")
    parser.add_argument("--bind", default="0.0.0.0",
                        help="中继服务器绑定地址（默认 0.0.0.0）")
    parser.add_argument("--terracotta", action="store_true",
                        help="标记本端使用陶瓦联机（房间内有人用时禁用 UDP）")
    parser.add_argument("--no-udp", action="store_true",
                        help="禁用 UDP 中继")
    parser.add_argument("--request-code", default="",
                        help="指定房间码（房主模式，可选）")
    args = parser.parse_args()

    # ── 独立中继服务器 ──
    if args.relay_server:
        _run_relay(args.bind, args.relay_port)
        return

    # ── 房主模式 ──
    if args.mode == "host":
        if not args.relay:
            print("错误: 请用 --relay 指定中继服务器地址")
            sys.exit(1)
        _run_host(
            relay=args.relay,
            relay_port=args.relay_port,
            mc_port=args.mc_port,
            use_terracotta=args.terracotta,
            enable_udp=not args.no_udp,
            requested_code=args.request_code,
        )
        return

    # ── 玩家模式 ──
    if args.mode == "client":
        if not args.relay:
            print("错误: 请用 --relay 指定中继服务器地址")
            sys.exit(1)
        if not args.code:
            print("错误: 请用 --code 指定房间码")
            sys.exit(1)
        _run_player(
            relay=args.relay,
            relay_port=args.relay_port,
            code=args.code,
            local_port=args.local_port,
            use_terracotta=args.terracotta,
            enable_udp=not args.no_udp,
        )
        return

    # ── GUI 模式（默认）──
    try:
        from src.ui.main_window import run_ui
        run_ui()
    except ImportError as e:
        print(f"错误: 无法加载 GUI ({e})")
        print("请安装依赖: pip install PyQt5")
        print("或使用命令行模式:")
        print("  中继服务器: python launcher.py --relay-server")
        print("  房主模式:   python launcher.py --mode host --relay <中继IP>")
        print("  玩家模式:   python launcher.py --mode client --relay <中继IP> --code <房间码>")
        sys.exit(1)


def _run_relay(bind: str, port: int):
    from src.core.relay_server import RelayServer
    print(f"中继服务器 {bind}:{port} 启动中...")
    async def _main():
        srv = RelayServer(bind, port)
        await srv.serve_forever()
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\n中继服务器已停止")


def _run_host(relay: str, relay_port: int, mc_port: int,
               use_terracotta: bool = False,
               enable_udp: bool = True,
               requested_code: str = ""):
    from src.core.host_session import HostSession
    print(f"房主模式: 中继={relay}:{relay_port}, MC={mc_port}, "
          f"陶瓦={use_terracotta}, UDP={enable_udp}")

    async def _main():
        session = HostSession(
            relay_host=relay,
            relay_port=relay_port,
            mc_host="127.0.0.1",
            mc_port=mc_port,
            use_terracotta=use_terracotta,
            enable_udp=enable_udp,
        )
        code = await session.start(requested_code)
        print(f"\n{'='*40}")
        print(f"  房间码: {code}")
        if use_terracotta:
            print(f"  ⚠️  已标记使用陶瓦联机，UDP 中继已禁用")
        print(f"  分享这个码给好友即可加入！")
        print(f"{'='*40}\n")
        await session.wait_until_stopped()

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\n房主端已停止")


def _run_player(relay: str, relay_port: int, code: str,
                local_port: int,
                use_terracotta: bool = False,
                enable_udp: bool = True):
    from src.core.player_session import PlayerSession
    print(f"玩家模式: 中继={relay}:{relay_port}, 房间={code}, "
          f"陶瓦={use_terracotta}, UDP={enable_udp}")

    async def _main():
        session = PlayerSession(
            relay_host=relay,
            relay_port=relay_port,
            room_code=code,
            local_host="127.0.0.1",
            local_port=local_port,
            use_terracotta=use_terracotta,
            enable_udp=enable_udp,
        )
        await session.connect()
        await session.start_local()
        print(f"\n{'='*40}")
        print(f"  已就绪！在 Minecraft 中连接 127.0.0.1:{local_port}")
        print(f"{'='*40}\n")
        await session.wait_until_stopped()

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\n玩家端已停止")


if __name__ == "__main__":
    main()
