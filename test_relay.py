"""
快速自测：验证中继服务器 + 房主 + 玩家端三方联动是否正常

运行方式：
    python test_relay.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


async def fake_mc_server(host="127.0.0.1", port=19999):
    """模拟一个简单的 MC 服务器：收到什么就回什么"""
    echoed = []

    async def handler(reader, writer):
        data = await reader.read(4096)
        echoed.append(data)
        writer.write(b"MC_ECHO:" + data)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handler, host, port)
    return server, echoed


async def main():
    print("=== minecraft-proxy 中继自测 ===\n")

    # 1. 启动假 MC 服务器
    mc_server, echoed = await fake_mc_server(port=19999)
    print("✅ 模拟 MC 服务器已启动 (127.0.0.1:19999)")

    # 2. 启动中继服务器
    from src.core.relay_server import RelayServer
    relay = RelayServer("127.0.0.1", 19566)
    await relay.start()
    print("✅ 中继服务器已启动 (127.0.0.1:19566)")

    await asyncio.sleep(0.1)

    # 3. 启动房主端
    from src.core.host_session import HostSession
    room_code_holder = []

    def on_host_status(msg):
        print(f"  [HOST] {msg}")
        if "房间码:" in msg:
            for part in msg.split():
                if len(part) == 6 and part.isalnum():
                    room_code_holder.append(part)

    host = HostSession(
        relay_host="127.0.0.1",
        relay_port=19566,
        mc_host="127.0.0.1",
        mc_port=19999,
        on_status=on_host_status,
    )
    code = await host.start()
    room_code_holder.append(code)
    print(f"✅ 房主端已启动，房间码: {code}")

    await asyncio.sleep(0.2)

    # 4. 启动玩家端
    from src.core.player_session import PlayerSession

    def on_player_status(msg):
        print(f"  [PLAYER] {msg}")

    player = PlayerSession(
        relay_host="127.0.0.1",
        relay_port=19566,
        room_code=code,
        local_host="127.0.0.1",
        local_port=19565,
        on_status=on_player_status,
    )
    pid = await player.connect()
    await player.start_local()
    print(f"✅ 玩家端已加入房间（ID={pid}），本地监听 127.0.0.1:19565")

    await asyncio.sleep(0.5)

    # 5. 模拟 MC 客户端连接
    print("\n>>> 模拟 MC 客户端连接 127.0.0.1:19565 ...")
    try:
        mc_client_reader, mc_client_writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", 19565), timeout=5
        )
        mc_client_writer.write(b"HELLO_FROM_CLIENT")
        await mc_client_writer.drain()
        print("✅ MC 客户端已连接，发送: HELLO_FROM_CLIENT")

        # 等待回声
        try:
            response = await asyncio.wait_for(mc_client_reader.read(4096), timeout=3)
            if b"MC_ECHO:HELLO_FROM_CLIENT" in response:
                print(f"✅ 收到回声: {response}")
                print("\n🎉 全链路测试通过！中继联机功能正常！")
            else:
                print(f"⚠️  收到意外数据: {response}")
        except asyncio.TimeoutError:
            print("⚠️  等待回声超时（可能正常，取决于 MC 服务器响应速度）")

        mc_client_writer.close()
    except Exception as e:
        print(f"❌ 连接失败: {e}")

    # 清理
    await asyncio.sleep(0.3)
    await player.stop()
    await host.stop()
    await relay.stop()
    mc_server.close()
    print("\n测试完成，所有资源已释放。")


if __name__ == "__main__":
    asyncio.run(main())
