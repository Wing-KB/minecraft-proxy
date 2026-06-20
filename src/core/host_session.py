"""
房主端核心逻辑（自动检测陶瓦版）
- 自动检测本地是否使用陶瓦，无需手动勾选
- 检测到陶瓦 → 禁用 UDP 中继（避免冲突）
- 未检测到陶瓦 → 自动请求 UDP 中继

协议:
  注册: [cmd=0x01] [data_len] [flags(1)] [可选: 房间码ASCII]
  回应: [cmd=0x10] [len] [code_len(1)] [房间码ASCII] [udp_port(2)]
  flags: bit0=陶瓦, bit1=请求UDP
"""

import asyncio
import logging
import struct
from typing import Dict, Optional, Callable
from .terracotta_compat import detect_terracotta, get_terracotta_status
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
    """
    房主端会话。
    自动检测陶瓦状态，无需手动设置。
    """
    def __init__(self, relay_host="127.0.0.1", relay_port=RELAY_DEF_PORT,
                 mc_host="127.0.0.1", mc_port=25565,
                 on_status=None, on_player_count=None, on_room_code=None,
                 on_terracotta_detected=None):
        self.relay_host = relay_host
        self.relay_port = relay_port
        self.mc_host = mc_host
        self.mc_port = mc_port
        self.on_status = on_status
        self.on_player_count = on_player_count
        self.on_room_code = on_room_code
        self.on_terracotta_detected = on_terracotta_detected

        # 自动检测，不依赖外部传参
        self.use_terracotta = detect_terracotta()
        self.want_udp = not self.use_terracotta

        self._code = ""
        self._running = False
        self._rdr = None
        self._wtr = None
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

    @property
    def terracotta_status(self) -> str:
        return get_terracotta_status()

    async def start(self, requested_code="") -> str:
        # 每次启动都重新检测
        self.use_terracotta = detect_terracotta()
        self.want_udp = not self.use_terracotta

        tc_status = get_terracotta_status()
        self._log(f"陶瓦检测: {tc_status}")
        if self.on_terracotta_detected:
            self.on_terracotta_detected(self.use_terracotta, tc_status)

        self._log(f"连接中继 {self.relay_host}:{self.relay_port} ...")
        self._rdr, self._wtr = await asyncio.wait_for(
            asyncio.open_connection(self.relay_host, self.relay_port), timeout=10)

        flags = 0
        if self.use_terracotta:
            flags |= FLAG_TERRACOTTA
        if self.want_udp and not self.use_terracotta:
            flags |= FLAG_WANT_UDP

        body = bytes([flags])
        if requested_code:
            body += requested_code.upper().encode("ascii")
        self._wtr.write(bytes([CMD_REGISTER, len(body)]) + body)
        await self._wtr.drain()

        cmd, data = await asyncio.wait_for(_read_pkt(self._rdr), timeout=10)
        if cmd != CMD_OK:
            raise RuntimeError(f"注册失败: {data.decode(errors='replace')}")

        # 解析回应: [code_len(1)] [code ascii] [udp_port(2)]
        if len(data) < 3:
            raise RuntimeError("服务器回应格式错误")
        code_len = data[0]
        if len(data) < 1 + code_len + 2:
            raise RuntimeError("服务器回应格式错误（长度不足）")
        code_bytes = data[1:1+code_len]
        self._code = code_bytes.decode("ascii").strip()
        udp_port = struct.unpack(">H", data[1+code_len:1+code_len+2])[0]

        self._running = True

        info = "陶瓦模式 | " if self.use_terracotta else ""
        udp_info = f"UDP中继端口: {udp_port}" if udp_port else "UDP: 禁用（房间内有陶瓦用户）"
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
            try:
                w.close()
            except Exception:
                pass
        self._mc_writers.clear()
        if self._wtr:
            try:
                self._wtr.close()
            except Exception:
                pass
        self._log("房主端已停止")

    async def wait_until_stopped(self):
        await self._stop_ev.wait()

    # ── 内部任务 ─────────────────────────────────────

    async def _ka_loop(self):
        while self._running:
            await asyncio.sleep(KA_INTERVAL)
            if not self._running:
                break
            try:
                await _send_pkt(self._wtr, CMD_PING)
            except Exception:
                break

    async def _relay_loop(self):
        try:
            while self._running:
                try:
                    cmd, data = await asyncio.wait_for(
                        _read_pkt(self._rdr), timeout=120)
                except asyncio.TimeoutError:
                    self._log("中继超时断开")
                    break

                if cmd == CMD_PONG:
                    pass
                elif cmd == CMD_PLAYER_JOINED:
                    pid = data[0] if data else 0
                    flags = data[1] if len(data) >= 2 else 0
                    info = "陶瓦用户" if flags & FLAG_TERRACOTTA else "普通用户"
                    asyncio.create_task(self._on_player_joined(pid, info))
                elif cmd == CMD_PLAYER_LEFT:
                    pid = data[0] if data else 0
                    self._on_player_left(pid)
                elif cmd == CMD_DATA:
                    if len(data) >= 2:
                        pid = struct.unpack(">H", data[:2])[0]
                        await self._fwd_to_mc(pid, data[2:])
                elif cmd == CMD_UDP:
                    if len(data) >= 2:
                        pid = struct.unpack(">H", data[:2])[0]
                        logger.debug(f"[HOST] UDP数据来自玩家{pid}（长度{len(data)-2}）")
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
            self._log(f"连接本地MC失败(p{pid}): {e}")
            return

        self._mc_writers[pid] = w
        self._pcount += 1
        if self.on_player_count:
            self.on_player_count(self._pcount)
        self._log(f"玩家 {pid} 已连接MC，开始中继")
        asyncio.create_task(self._mc_to_relay(pid, r))

    def _on_player_left(self, pid: int):
        self._log(f"玩家 {pid} 离开")
        w = self._mc_writers.pop(pid, None)
        if w:
            try:
                w.close()
            except Exception:
                pass
        self._pcount = max(0, self._pcount - 1)
        if self.on_player_count:
            self.on_player_count(self._pcount)

    async def _fwd_to_mc(self, pid: int, data: bytes):
        w = self._mc_writers.get(pid)
        if w:
            try:
                w.write(data)
                await w.drain()
            except Exception:
                self._on_player_left(pid)

    async def _mc_to_relay(self, pid: int, r: asyncio.StreamReader):
        try:
            while self._running and pid in self._mc_writers:
                d = await asyncio.wait_for(r.read(65536), timeout=60)
                if not d:
                    break
                pkt = struct.pack(">BH", CMD_DATA, 2+len(d)) + struct.pack(">H", pid) + d
                self._wtr.write(pkt)
                await self._wtr.drain()
        except Exception:
            pass
        finally:
            self._on_player_left(pid)


# 协议常量（与 relay_server 保持一致，避免循环引用）
CMD_REGISTER = 0x01
CMD_JOIN = 0x02
