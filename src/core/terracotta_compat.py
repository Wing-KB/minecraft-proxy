"""
陶瓦联机 (Terracotta) 房间码兼容模块
陶瓦房间码格式: U/XXXX-XXXX-XXXX-XXXX (共21字符)
- 前缀: U/
- 16位 Base34 编码字符集: 0123456789ABCDEFGHJKLMNPQRSTUVWXYZ (排除 I 和 O)
- 分隔符: 每4位一个 '-'
- 校验: 解码后的 value 必须能被 7 整除

解析后可得:
  - network_name:  scaffolding-mc-XXXX-XXXX (前8位)
  - network_secret: XXXX-XXXX (后8位)
  - seed: 原始 u128 值
"""

import re
import secrets
import sys
import subprocess
from typing import Optional, Tuple


# 陶瓦使用的 Base34 字符集 (34 = 2*17, 排除易混淆的 I 和 O)
TERRACOTTA_CHARSET = "0123456789ABCDEFGHJKLMNPQRSTUVWXYZ"
TERRACOTTA_CHARSET_MAP = {c: i for i, c in enumerate(TERRACOTTA_CHARSET)}
TERRACOTTA_PREFIX = "U/"
TERRACOTTA_CODE_PATTERN = re.compile(
    r"^U/[0-9A-HJKMNP-Z]{4}-[0-9A-HJKMNP-Z]{4}-[0-9A-HJKMNP-Z]{4}-[0-9A-HJKMNP-Z]{4}$"
)
# 容错字符映射: I->1, O->0, i->1, o->0, l->1
_FAULT_TOLERANCE = {"I": "1", "O": "0", "i": "1", "o": "0", "l": "1"}


def _terracotta_char_to_val(c: str) -> Optional[int]:
    """将单个陶瓦字符转为 Base34 数值，支持容错"""
    if c in _FAULT_TOLERANCE:
        c = _FAULT_TOLERANCE[c]
    return TERRACOTTA_CHARSET_MAP.get(c.upper())


def parse_terracotta_code(code: str) -> Optional[Tuple[int, str, str]]:
    """
    解析陶瓦房间码，返回 (seed, network_name, network_secret)
    如果格式无效或校验失败，返回 None
    """
    code = code.strip()
    if not code:
        return None

    # 容错预处理
    normalized = ""
    for c in code:
        normalized += _FAULT_TOLERANCE.get(c, c)
    code = normalized

    if not TERRACOTTA_CODE_PATTERN.match(code):
        return None

    # 去掉前缀 U/ 和分隔符 -
    body = code[2:].replace("-", "")
    if len(body) != 16:
        return None

    # 陶瓦的编码是从低位到高位，解析时需逆序处理
    try:
        value = 0
        for ch in body:  # 从最低位到最高位
            v = _terracotta_char_to_val(ch)
            if v is None:
                return None
            value = value * 34 + v
    except Exception:
        return None

    # 校验: 必须是 7 的倍数
    if value == 0 or value % 7 != 0:
        return None

    # 反向推导 network_name 和 network_secret
    temp_value = value
    chars = []
    for _ in range(16):
        chars.append(TERRACOTTA_CHARSET[temp_value % 34])
        temp_value //= 34

    nc = chars[0:4] + ["-"] + chars[4:8]
    network_name = "scaffolding-mc-" + "".join(nc)
    sc = chars[8:12] + ["-"] + chars[12:16]
    network_secret = "".join(sc)

    return (value, network_name, network_secret)


def is_terracotta_code(code: str) -> bool:
    """判断一个字符串是否是有效的陶瓦房间码"""
    return parse_terracotta_code(code) is not None


def generate_terracotta_compatible_code() -> str:
    """生成一个陶瓦兼容的房间码 (U/XXXX-XXXX-XXXX-XXXX 格式)"""
    while True:
        raw = secrets.token_bytes(16)
        value = int.from_bytes(raw, "big") % (34 ** 16)
        value = value - (value % 7)
        if value == 0:
            continue

        chars = []
        v = value
        for _ in range(16):
            chars.append(TERRACOTTA_CHARSET[v % 34])
            v //= 34

        code_body = (
            chars[0] + chars[1] + chars[2] + chars[3] + "-"
            + chars[4] + chars[5] + chars[6] + chars[7] + "-"
            + chars[8] + chars[9] + chars[10] + chars[11] + "-"
            + chars[12] + chars[13] + chars[14] + chars[15]
        )
        return TERRACOTTA_PREFIX + code_body


def generate_room_code(terracotta_format: bool = False) -> str:
    """
    生成房间码
    - terracotta_format=False: 6位大写字母数字 (原格式，向下兼容)
    - terracotta_format=True: 陶瓦兼容格式 U/XXXX-XXXX-XXXX-XXXX
    """
    if terracotta_format:
        return generate_terracotta_compatible_code()
    else:
        chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        return "".join(secrets.choice(chars) for _ in range(6))


# ── 自动检测陶瓦联机（EasyTier）───────────────────────────────────────────────────

def detect_terracotta() -> bool:
    """
    自动检测本地是否正在使用陶瓦联机（EasyTier）。
    检测方法（按优先级）:
      1. 检测 EasyTier 相关进程是否在运行
      2. 检测陶瓦配置文件是否存在
      3. 检测典型端口（11010/11011）是否被监听

    返回: True = 检测到陶瓦/EasyTier，False = 未检测到
    """
    if _detect_process():
        return True
    if _detect_config():
        return True
    if _detect_port():
        return True
    return False


def _detect_process() -> bool:
    """检测 EasyTier / 陶瓦 相关进程"""
    try:
        if sys.platform.startswith("win"):
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq easytier*", "/NH"],
                capture_output=True, text=True, timeout=5
            )
            if "easytier" in result.stdout.lower():
                return True
            result2 = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq terracotta*", "/NH"],
                capture_output=True, text=True, timeout=5
            )
            if "terracotta" in result2.stdout.lower():
                return True
        else:
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True, text=True, timeout=5
            )
            for keyword in ["easytier", "terracotta", "easytier-core"]:
                if keyword in result.stdout.lower():
                    return True
    except Exception:
        pass
    return False


def _detect_config() -> bool:
    """检测陶瓦 / EasyTier 配置文件是否存在"""
    try:
        if sys.platform.startswith("win"):
            import os
            user_home = os.path.expanduser("~")
            config_paths = [
                os.path.join(user_home, ".terracotta"),
                os.path.join(user_home, ".easytier"),
                os.path.join(user_home, "AppData", "Roaming", "Terracotta"),
            ]
        else:
            import os
            user_home = os.path.expanduser("~")
            config_paths = [
                os.path.join(user_home, ".terracotta"),
                os.path.join(user_home, ".easytier"),
                "/etc/easytier",
            ]
        for p in config_paths:
            if os.path.exists(p):
                return True
    except Exception:
        pass
    return False


def _detect_port() -> bool:
    """检测 EasyTier 典型端口（11010/11011）是否被监听"""
    try:
        if sys.platform.startswith("win"):
            result = subprocess.run(
                ["netstat", "-an"],
                capture_output=True, text=True, timeout=5
            )
            for port in ["11010", "11011", "22000"]:
                if ":" + port in result.stdout:
                    return True
        else:
            result = subprocess.run(
                ["ss", "-tuln"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                result = subprocess.run(
                    ["netstat", "-tuln"],
                    capture_output=True, text=True, timeout=5
                )
            for port in ["11010", "11011", "22000"]:
                if ":" + port in result.stdout:
                    return True
    except Exception:
        pass
    return False


def get_terracotta_status() -> str:
    """
    获取陶瓦检测状态的详细文字说明，用于 UI 显示。
    返回: 如 "已检测到大瓦 (EasyTier 进程中)" 或 "未检测到陶瓦"
    """
    try:
        if sys.platform.startswith("win"):
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq easytier*", "/NH"],
                capture_output=True, text=True, timeout=5
            )
            if "easytier" in result.stdout.lower():
                return "已检测到大瓦联机 (EasyTier 进程中)"
            result2 = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq terracotta*", "/NH"],
                capture_output=True, text=True, timeout=5
            )
            if "terracotta" in result2.stdout.lower():
                return "已检测到陶瓦联机 (Terracotta 进程中)"
        else:
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True, text=True, timeout=5
            )
            if "easytier" in result.stdout.lower():
                return "已检测到大瓦联机 (EasyTier 进程中)"
            if "terracotta" in result.stdout.lower():
                return "已检测到陶瓦联机 (Terracotta 进程中)"
    except Exception:
        pass

    if _detect_config():
        return "检测到陶瓦配置文件（未运行中）"
    if _detect_port():
        return "检测到陶瓦/EasyTier 端口（可能运行中）"
    return "未检测到陶瓦联机"
