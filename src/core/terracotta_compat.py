"""
陶瓦联机 (Terracotta) 房间码兼容模块
陶瓦房间码格式: U/XXXX-XXXX-XXXX-XXXX  (共21字符)
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

    陶瓦房间码编码规则（从 Rust 代码逆向）:
    - 生成随机 u128，取模 34^16，再对齐到 7 的倍数
    - 从低位到高位依次取 Base34 的一位，逆序拼成 16 位字符串
    - 前8位 -> network_name (格式: scaffolding-mc-XXXX-XXXX)
    - 后8位 -> network_secret (格式: XXXX-XXXX)
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
    # body[0] 对应最低位，body[15] 对应最高位
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
    # 编码时: for i in 0..16: v = (value % 34); value /= 34
    #   code_char[i] = CHARS[v]
    #   if i < 8: network_name_char[i] = code_char[i]
    #   else:     network_secret_char[i-8] = code_char[i]
    # 注意: code 中字符顺序是逆序的 (低位在前)

    # 从 value 重新提取各位（低位在前 = body 的顺序）
    temp_value = value
    chars = []
    for _ in range(16):
        chars.append(TERRACOTTA_CHARSET[temp_value % 34])
        temp_value //= 34

    # chars[0..7] = 前8位 -> network_name
    nc = chars[0:4] + ["-"] + chars[4:8]
    network_name = "scaffolding-mc-" + "".join(nc)
    # chars[8..15] = 后8位 -> network_secret
    sc = chars[8:12] + ["-"] + chars[12:16]
    network_secret = "".join(sc)

    return (value, network_name, network_secret)


def is_terracotta_code(code: str) -> bool:
    """判断一个字符串是否是有效的陶瓦房间码"""
    return parse_terracotta_code(code) is not None


def generate_terracotta_compatible_code() -> str:
    """
    生成一个陶瓦兼容的房间码 (U/XXXX-XXXX-XXXX-XXXX 格式)
    可用于让熟悉陶瓦的用户更容易接受
    """
    while True:
        raw = secrets.token_bytes(16)
        value = int.from_bytes(raw, "big") % (34 ** 16)
        value = value - (value % 7)  # 对齐到 7 的倍数
        if value == 0:
            continue

        # 从低位到高位编码为 Base34 字符
        chars = []
        v = value
        for _ in range(16):
            chars.append(TERRACOTTA_CHARSET[v % 34])
            v //= 34

        # chars 现在是低位在前，按陶瓦格式加分隔符
        # 陶瓦格式: U/XXXX-XXXX-XXXX-XXXX
        # 注意: 陶瓦代码中是从 i=0..15 依次 push，并在 i==4,8,12 时加 '-'
        # 即: chars[0..3] + '-' + chars[4..7] + '-' + chars[8..11] + '-' + chars[12..15]
        # 但 chars 是低位在前，陶瓦显示时是逆序的吗？
        # 看陶瓦代码: for i in 0..16: v = CHARS[(value % 34) as usize]; value /= 34;
        #   if i == 4 || i == 8 || i == 12 { code.push('-'); }
        #   code.push(v);
        # 所以 code 字符串中，最低位在 index 0，最高位在 index 15+3=18 (加3个分隔符)
        # 即: code = [位0][位1][位2][位3]-[位4][位5][位6][位7]-[位8][位9][位10][位11]-[位12][位13][位14][位15]
        # 显示时从左到右是低位到高位

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
