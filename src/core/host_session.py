"""
房主端核心逻辑（陶瓦兼容版）
协议:
  注册: [cmd=0x01] [data_len] [flags(1)] [可选: 房间码ASCII]
  回应: [cmd=0x10] [len] [房间码ASCII] [udp_port(2字节)]
  房主 flags: bit0=陶瓦, bit1=请求UDP
"""

import asyncio
import logging
import struct
from typing import Dict, Optional, Callable
from .relay_server import (
    CMD_OK, CMD_ERROR, CMD_DATA, CMD_PING, CMD_PONG,
    CMD_PLAYER_JOINED, CMD_PLAYER_LEFT, CMD_UDP,
    FLAG_TERRACOTTA, FLAG_WANT_UDP,
    _send_pkt, _read_pkt
)

logger = logging.getLogger(__name__)
RELAY_DEF_PORT = 25566
KA_INTERVAL = 30


class HostSession:
    def __init__(self, relay_host="127.0.0.1", relay_port=RELAY_DEF_PORT,
                 mc_host="127.0.0.1", mc_port=25565,
                 use_terracotta=False, want_udp=True,
                 on_status=None, on_player_count=None, on_room_code=None):
        self.relay_host = relay_host
        self.relay_port = relay_port
        self.mc_host = mc_host
        self.mc_port = mc_port
        self.use_terracotta = use_terracotta
        self.want_udp = want_udp
        self.on_status = on_status
        self.on_player_count = on_player_count
        self.on_room_code = on_room_code

        self._code = ""
        self._running = False
        self._rdr = None   # StreamReader
        self._wtr = None   # StreamWriter
        self._mc_writers: Dict[int, asyncio.StreamWriter] = {}
        self._pcount = 0
        self._stop_ev = asyncio.Event()
        self._tasks = []

    def _log(self, msg):
        logger.info(msg)
        if self.on_status:
            self.on_status(msg)

    @property
    def room_code(self):
        return self._code

    @property
    def player_count(self):
        return self._pcount

    async def start(self, requested_code="") -> str:
        self._log(f"连接中继 {self.relay_host}:{self.relay_port} ...")
        self._rdr, self._wtr = await asyncio.wait_for(
            asyncio.open_connection(self.relay_host, self.relay_port), timeout=10)

        flags = 0
        if self.use_terracotta:
            flags |= FLAG_TERRACOTTA
        if self.want_udp and not self.use_terracotta:
            flags |= FLAG_WANT_UDP

        # 构建注册包
        body = bytes([flags])
        if requested_code:
            body += requested_code.upper().encode("ascii")
        self._wtr.write(bytes([CMD_REGISTER, len(body)]) + body)
        await self._wtr.drain()

        cmd, data = await asyncio.wait_for(_read_pkt(self._rdr), timeout=10)
        if cmd != CMD_OK:
            raise RuntimeError(f"注册失败: {data.decode(errors='replace')}")

        # 解析回应: 房间码(变长) + UDP端口(2字节)
        # 找房间码和UDP端口的分界
        udp_port = 0
        code_bytes = data
        if len(data) >= 2:
            # 最后2字节可能是 UDP 端口
            maybe_port = struct.unpack(">H", data[-2:])[0]
            # 如果房间码是6位或21位陶瓦格式，则最后2字节是UDP端口
            code_part = data[:-2]
            if (len(code_part) == 6 and code_part.isalnum()) or \
               (len(code_part) == 21 and data[:2] == b"U/"):
                code_bytes = code_part
                udp_port = maybe_port

        self._code = code_bytes.decode("ascii").strip()
        self._running = True

        info = "陶瓦模式 | " if self.use_terracotta else ""
        udp_info = f"UDP中继端口: {udp_port}" if udp_port else "UDP: 禁用"
        self._log(f"房间已创建: {self._code} | {info}{udp_info}")
        if self.on_room_code:
            self.on_room_code(self._code)

        self._tasks = [
            asyncio.create_task(self._relay_loop()),
            asyncio.create_task(self._ka_loop()),
        ]
        return self._code

    async def stop(self):
        self._running = False
        self._stop_ev.set()
        for t in self._tasks:
            t.cancel()
        for w in list(self._mc_writers.values()):
            try: w.close()
            except: pass
        self._mc_writers.clear()
        if self._wtr:
            try: self._wtr.close()
            except: pass
        self._log("房主端已停止")

    async def wait_until_stopped(self):
        await self._stop_ev.wait()

    # ── 内部任务 ─────────────────────────────────────

    async def _ka_loop(self):
        while self._running:
            await asyncio.sleep(KA_INTERVAL)
            if not self._running: break
            try: await _send_pkt(self._wtr, CMD_PING)
            except: break

    async def _relay_loop(self):
        try:
            while self._running:
                try:
                    cmd, data = await asyncio.wait_for(
                        _read_pkt(self._rdr), timeout=120)
                except asyncio.TimeoutError:
                    self._log("中继超时断开"); break

                if cmd == CMD_PONG: pass
                elif cmd == CMD_PLAYER_JOINED:
                    pid = data[0] if data else 0
                    flags = data[1] if len(data) >= 2 else 0
                    info = "陶瓦用户" if flags & FLAG_TERRACOTTA else "普通用户"
                    asyncio.create_task(self._on_player_joined(pid, info))
                elif cmd == CMD_PLAYER_LEFT:
                    pid = data[0] if data else 0
                    self._on_player_left(pid)
                elif cmd == CMD_DATA:
                    # data[0:2]=pid(网络字节序)  data[2:]=payload
                    if len(data) >= 2:
                        pid = struct.unpack(">H", data[:2])[0]
                        await self._fwd_to_mc(pid, data[2:])
                elif cmd == CMD_UDP:
                    # 房主发来的 UDP 数据（通过TCP隧道）
                    if len(data) >= 2:
                        pid = struct.unpack(">H", data[:2])[0]
                        # TODO: 转发 UDP 给本地 MC
                else:
                    logger.debug(f"[HOST] 未知 cmd=0x{cmd:02X}")
        except Exception as e:
            self._log(f"中继断开: {e}")
        finally:
            self._running = False
            self._stop_ev.set()

    async def _on_player_joined(self, pid: int, info: str):
        self._log(f"玩家 {pid} 加入({info})，连接本地 MC {self.mc_host}:{self.mc_port} ...")
        try:
            r, w = await asyncio.wait_for(
                asyncio.open_connection(self.mc_host, self.mc_port), timeout=10)
        except Exception as e:
            self._log(f"连接本地MC失败(p{pid}): {e}"); return

        self._mc_writers[pid] = w
        self._pcount += 1
        if self.on_player_count: self.on_player_count(self._pcount)
        self._log(f"玩家 {pid} 已连接MC，开始中继")
        asyncio.create_task(self._mc_to_relay(pid, r))

    def _on_player_left(self, pid: int):
        self._log(f"玩家 {pid} 离开")
        w = self._mc_writers.pop(pid, None)
        if w:
            try: w.close()
            except: pass
        self._pcount = max(0, self._pcount - 1)
        if self.on_player_count: self.on_player_count(self._pcount)

    async def _fwd_to_mc(self, pid: int, data: bytes):
        w = self._mc_writers.get(pid)
        if w:
            try:
                w.write(data); await w.drain()
            except:
                self._on_player_left(pid)

    async def _mc_to_relay(self, pid: int, r: asyncio.StreamReader):
        try:
            while self._running and pid in self._mc_writers:
                d = await asyncio.wait_for(r.read(65536), timeout=60)
                if not d: break
                pkt = struct.pack(">BH", CMD_DATA, 2+len(d)) + struct.pack(">H", pid) + d
                self._wtr.write(pkt); await self._wtr.drain()
        except: pass
        finally:
            self._on_player_left(pid)
