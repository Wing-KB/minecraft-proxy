#!/usr/bin/env python3
"""
Minecraft Cross-Region Proxy
Minecraft 异地联机工具 v2.0

用法:
  python launcher.py                          # GUI 模式
  python launcher.py --relay-server           # 独立运行中继服务器
  python launcher.py --mode host              # 命令行房主（需配合 --relay 和 --mc-port）
  python launcher.py --mode client            # 命令行玩家（需配合 --relay 和 --code）
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
    parser = argparse.ArgumentParser(description="Minecraft 异地联机工具 v2.0")
    parser.add_argument("--mode", choices=["server", "host", "client", "player"],
                        help="运行模式: host=房主, client=玩家")
    parser.add_argument("--relay-server", "--relay_server", action="store_true",
                        help="启动独立中继服务器")
    parser.add_argument("--relay", default="",
                        help="中继服务器地址（host/client 模式必填）")
    parser.add_argument("--relay-port", "--relay_port", type=int, default=25566,
                        help="中继服务器端口（默认 25566）")
    parser.add_argument("--mc-port", "--mc_port", type=int, default=25565,
                        help="本地 Minecraft 端口（房主模式，默认 25565）")
    parser.add_argument("--local-port", "--local_port", type=int, default=25565,
                        help="本地监听端口（玩家模式，默认 25565）")
    parser.add_argument("--code", default="",
                        help="房间码（玩家模式必填）")
    parser.add_argument("--bind", default="0.0.0.0",
                        help="中继服务器绑定地址（默认 0.0.0.0）")
    args = parser.parse_args()

    # ── 独立中继服务器 ──
    if args.relay_server:
        _run_relay(args.bind, args.relay_port)
        return

    # ── 房主模式 ──
    if args.mode in ("server", "host"):
        if not args.relay:
            print("错误: 请用 --relay 指定中继服务器地址")
            sys.exit(1)
        _run_host(args.relay, args.relay_port, args.mc_port)
        return

    # ── 玩家模式 ──
    if args.mode in ("client", "player"):
        if not args.relay:
            print("错误: 请用 --relay 指定中继服务器地址")
            sys.exit(1)
        if not args.code:
            print("错误: 请用 --code 指定房间码")
            sys.exit(1)
        _run_player(args.relay, args.relay_port, args.code, args.local_port)
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
        print("  房主模式:   python launcher.py --mode host --relay <中继IP> --mc-port 25565")
        print("  玩家模式:   python launcher.py --mode client --relay <中继IP> --code ABCDEF")
        sys.exit(1)


def _run_relay(bind: str, port: int):
    from src.core.relay_server import RelayServer
    from src.config import print_banner
    print_banner()
    print(f"中继服务器 {bind}:{port} 启动中...")

    async def _main():
        srv = RelayServer(bind, port)
        await srv.serve_forever()

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\n中继服务器已停止")


def _run_host(relay: str, relay_port: int, mc_port: int):
    from src.core.host_session import HostSession
    from src.config import print_banner
    print_banner()

    def _on_status(msg):
        print(f"[HOST] {msg}")

    async def _main():
        session = HostSession(
            relay_host=relay,
            relay_port=relay_port,
            mc_port=mc_port,
            on_status=_on_status,
            on_player_count=lambda n: print(f"[HOST] 在线玩家: {n}"),
        )
        code = await session.start()
        print(f"\n{'='*40}")
        print(f"  房间码: {code}")
        print(f"  分享这个码给好友即可加入！")
        print(f"{'='*40}\n")
        await session.wait_until_stopped()

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\n房主端已停止")


def _run_player(relay: str, relay_port: int, code: str, local_port: int):
    from src.core.player_session import PlayerSession
    from src.config import print_banner
    print_banner()

    def _on_status(msg):
        print(f"[PLAYER] {msg}")

    async def _main():
        session = PlayerSession(
            relay_host=relay,
            relay_port=relay_port,
            room_code=code,
            local_port=local_port,
            on_status=_on_status,
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
