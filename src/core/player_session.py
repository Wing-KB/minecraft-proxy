"""
玩家端核心逻辑（陶瓦兼容版）
协议:
  加入: [cmd=0x02] [data_len] [flags(1)] [房间码ASCII]
  回应: [cmd=0x10] [len] [player_id(1)] [udp_port(2)]
"""

import asyncio
import logging
import struct
from typing import Optional, Callable
from .relay_server import (
    CMD_OK, CMD_ERROR, CMD_DATA, CMD_PING, CMD_PONG,
    CMD_PLAYER_JOINED, CMD_PLAYER_LEFT, CMD_UDP,
    FLAG_TERRACOTTA, FLAG_WANT_UDP,
    _send_pkt, _read_pkt
)

logger = logging.getLogger(__name__)
RELAY_DEF_PORT = 25566
KA_INTERVAL = 30


class PlayerSession:
    def __init__(self, relay_host="127.0.0.1", relay_port=RELAY_DEF_PORT,
                 room_code="", local_host="127.0.0.1", local_port=25565,
                 use_terracotta=False, want_udp=True,
                 on_status=None):
        self.relay_host = relay_host
        self.relay_port = relay_port
        self.room_code = room_code.upper().strip()
        self.local_host = local_host
        self.local_port = local_port
        self.use_terracotta = use_terracotta
        self.want_udp = want_udp
        self.on_status = on_status

        self._running = False
        self._pid = 0
        self._rdr = None
        self._wtr = None
        self._mc_writer = None
        self._local_srv = None
        self._udp_port = 0
        self._stop_ev = asyncio.Event()
        self._tasks = []

    def _log(self, msg):
        logger.info(msg)
        if self.on_status:
            self.on_status(msg)

    async def connect(self) -> int:
        self._log(f"连接中继 {self.relay_host}:{self.relay_port} ...")
        self._rdr, self._wtr = await asyncio.wait_for(
            asyncio.open_connection(self.relay_host, self.relay_port), timeout=10)

        flags = 0
        if self.use_terracotta:
            flags |= FLAG_TERRACOTTA
        if self.want_udp and not self.use_terracotta:
            flags |= FLAG_WANT_UDP

        body = bytes([flags]) + self.room_code.encode("ascii")
        self._wtr.write(bytes([CMD_JOIN, len(body)]) + body)
        await self._wtr.drain()

        cmd, data = await asyncio.wait_for(_read_pkt(self._rdr), timeout=10)
        if cmd == CMD_ERROR:
            raise RuntimeError(f"加入失败: {data.decode(errors='replace')}")
        if cmd != CMD_OK:
            raise RuntimeError(f"未知响应: 0x{cmd:02X}")

        self._pid = data[0] if data else 1
        self._udp_port = struct.unpack(">H", data[1:3])[0] if len(data) >= 3 else 0
        self._running = True

        info = "陶瓦模式 | " if self.use_terracotta else ""
        udp_info = f"UDP中继: 启用(端口{self._udp_port})" if self._udp_port else "UDP: 禁用"
        self._log(f"已加入 {self.room_code} (ID={self._pid}) | {info}{udp_info}")
        return self._pid

    async def start_local(self):
        t1 = asyncio.create_task(self._relay_loop())
        t2 = asyncio.create_task(self._ka_loop())
        self._tasks = [t1, t2]

        if self._udp_port and self.want_udp:
            t3 = asyncio.create_task(self._udp_listen())
            self._tasks.append(t3)

        self._local_srv = await asyncio.start_server(
            self._on_mc_connect, self.local_host, self.local_port)
        self._log(f"本地监听: {self.local_host}:{self.local_port}")
        self._log(f"请在 MC 中连接 {self.local_host}:{self.local_port}")

    async def stop(self):
        self._running = False
        self._stop_ev.set()
        for t in self._tasks:
            t.cancel()
        if self._local_srv:
            self._local_srv.close()
        if self._mc_writer:
            try: self._mc_writer.close()
            except: pass
        if self._wtr:
            try: self._wtr.close()
            except: pass
        self._log("玩家端已停止")

    async def wait_until_stopped(self):
        await self._stop_ev.wait()

    # ── 内部任务 ─────────────────────────────────────

    async def _ka_loop(self):
        while self._running:
            await asyncio.sleep(KA_INTERVAL)
            if not self._running: break
            try: await _send_pkt(self._wtr, CMD_PING)
            except: break

    async def _on_mc_connect(self, r, w):
        addr = w.get_extra_info("peername")
        self._log(f"MC客户端已连接 {addr}")
        if self._mc_writer:
            try: self._mc_writer.close()
            except: pass
        self._mc_writer = w
        asyncio.create_task(self._mc_to_relay(r))

    async def _mc_to_relay(self, r: asyncio.StreamReader):
        try:
            while self._running:
                d = await asyncio.wait_for(r.read(65536), timeout=60)
                if not d: break
                await _send_pkt(self._wtr, CMD_DATA, d)
        except: pass
        finally:
            self._log("MC客户端断开")
            self._mc_writer = None

    async def _relay_loop(self):
        try:
            while self._running:
                try:
                    cmd, data = await asyncio.wait_for(
                        _read_pkt(self._rdr), timeout=120)
                except asyncio.TimeoutError:
                    self._log("中继超时断开"); break

                if cmd == CMD_PONG: pass
                elif cmd == CMD_DATA:
                    if self._mc_writer:
                        try:
                            self._mc_writer.write(data)
                            await self._mc_writer.drain()
                        except: pass
                elif cmd == CMD_ERROR:
                    self._log(f"中继错误: {data.decode(errors='replace')}"); break
                else:
                    logger.debug(f"[PLAYER] 未知 cmd=0x{cmd:02X}")
        except Exception as e:
            self._log(f"中继断开: {e}")
        finally:
            self._running = False
            self._stop_ev.set()

    async def _udp_listen(self):
        """监听本地 UDP，转发给中继（简化版）"""
        loop = asyncio.get_running_loop()
        try:
            transport, _ = await loop.create_datagram_endpoint(
                lambda: _UdpClient(self),
                local_addr=(self.local_host, self.local_port + 1))
            self._log(f"UDP中继监听: {self.local_host}:{self.local_port+1}")
            await asyncio.sleep(999999)
        except asyncio.CancelledError:
            transport.close()
        except Exception as e:
            self._log(f"UDP中继启动失败: {e}")


class _UdpClient(asyncio.DatagramProtocol):
    def __init__(self, session):
        self.session = session
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        """本地MC发来UDP包，通过TCP隧道发给中继"""
        if self.session._wtr and self.session._running:
            asyncio.ensure_future(self._send(data))

    async def _send(self, data: bytes):
        try:
            # CMD_UDP + pid(2) + data
            pkt = struct.pack(">BH", CMD_UDP, 2+len(data)) + struct.pack(">H", self.session._pid) + data
            self.session._wtr.write(pkt)
            await self.session._wtr.drain()
        except: pass
