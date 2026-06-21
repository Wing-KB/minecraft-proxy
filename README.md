# Minecraft 异地联机工具

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.8+-green.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)

让不在同一局域网的 Minecraft Java 版玩家也能一起联机，无需公网 IP、无需繁琐的端口映射。

本项目提供**中继服务器** + **房主端** + **玩家端** 完整方案，基于 TCP 中继实现跨网联机，并兼容[陶瓦联机 (Terracotta)](https://github.com/burningtnt/Terracotta) 房间码格式。

---

## 目录

- [原理](#原理)
- [快速开始](#快速开始)
- [使用方式](#使用方式)
- [陶瓦联机兼容](#陶瓦联机兼容)
- [UDP 中继](#udp-中继)
- [命令行用法](#命令行用法)
- [协议说明](#协议说明)
- [构建 & 开发](#构建--开发)
- [常见问题](#常见问题)

---

## 原理

```
┌─────────┐     TCP 中继      ┌────────────┐    本地 TCP    ┌─────────────┐
│  MC 玩家  │ ─────────────→ │  中继服务器   │ ──────────→ │  房主端       │ ───→ │  MC 服务器   │
│ (127.0.0.1)│  ←────────────  │  (公网 IP)  │ ←──────────  │  (本工具)    │ ←──  │  (本地)     │
└─────────┘    中继流量      └────────────┘    中继流量    └─────────────┘      MC 流量  └─────────────┘
```

1. **房主**开启本地 MC 服务器，运行本工具「房主模式」，连接到中继服务器，获得**房间码**
2. **玩家**运行本工具「玩家模式」，输入房间码，连接到同一中继服务器
3. 本工具在玩家本地开启 `127.0.0.1:25565` 监听，MC 客户端直接连这个地址即可进入游戏

> 中继服务器需要部署在**有公网 IP 的机器**上（云主机、友人的公网机器等）。

---

## 快速开始

### 方式一：下载发布包（推荐）

前往 [Releases](https://github.com/Wing-KB/minecraft-proxy/releases) 页面下载对应平台的可执行文件，解压即用。

### 方式二：从源码运行

```bash
git clone https://github.com/Wing-KB/minecraft-proxy.git
cd minecraft-proxy

# 安装依赖
pip install -r requirements.txt

# 运行 GUI
python launcher.py
```

---

## 使用方式

### 第一步：部署中继服务器

在一台有公网 IP 的机器上运行：

```bash
# 方式 A：命令行启动中继
python launcher.py --relay-server --bind 0.0.0.0 --relay-port 25566

# 方式 B：GUI 中切换到「中继服务器」选项卡，点击「启动中继服务器」
```

> 确保防火墙放行 TCP 端口（默认 `25566`，UDP 端口 `25567` 可选）。

### 第二步：房主创建房间

1. 开启 Minecraft 服务器（默认端口 `25565`）
2. 打开本工具，切换到「房主模式」
3. 填写中继服务器 IP 和端口，点击「开始联机」
4. 将获得的**房间码**发给好友

### 第三步：玩家加入

1. 打开本工具，切换到「加入游戏」
2. 填写中继服务器 IP、端口，输入房间码
3. 点击「加入游戏」
4. 打开 Minecraft → 多人游戏 → 直接连接 → 输入 `127.0.0.1`

---

## 陶瓦联机兼容

本工具支持识别[陶瓦联机 (Terracotta)](https://github.com/burningtnt/Terracotta) 的房间码格式：

| 格式 | 示例 | 说明 |
|------|------|------|
| 本工具默认 | `AB3C2D` | 6 位，简单好记 |
| 陶瓦兼容 | `U/8F2K-3M7Q-1X9Z-5N4J` | 21 位，与陶瓦格式一致 |

### 陶瓦标记与 UDP 行为

当房间内**有任意一名用户使用陶瓦联机**时：
- 自动禁用 UDP 中继（陶瓦基于 EasyTier P2P VPN，无需额外 UDP 映射）
- 其他玩家仍可正常通过本工具 TCP 中继联机

当房间内**无人使用陶瓦**时：
- 自动在中继服务器开启 UDP 中继端口（默认 TCP 端口 +1）
- 用于转发 MC 的 UDP 流量（如 LAN 发现包等）

---

## UDP 中继

> ⚠️ UDP 中继为实验性功能，当前版本仅作框架支持。

Minecraft 的「打开到局域网」功能使用 UDP 广播来发现本地游戏。跨网环境下此功能失效，开启 UDP 中继可部分恢复此能力。

| 条件 | UDP 中继状态 |
|------|-------------|
| 房间内有人使用陶瓦 | ❌ 禁用（陶瓦 P2P 已覆盖） |
| 无人使用陶瓦，且房主/玩家请求 UDP | ✅ 启用（中继端口 = TCP 端口 + 1） |

---

## 命令行用法

```bash
# 启动 GUI（默认）
python launcher.py

# 启动独立中继服务器
python launcher.py --relay-server --bind 0.0.0.0 --relay-port 25566

# 房主模式（命令行）
python launcher.py --mode host --relay <中继IP> --relay-port 25566 --mc-port 25565

# 玩家模式（命令行）
python launcher.py --mode client --relay <中继IP> --relay-port 25566 --code AB3C2D --local-port 25565
```

### 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--mode` | 运行模式：`host` / `client` | GUI |
| `--relay` | 中继服务器地址 | （必填） |
| `--relay-port` | 中继服务器端口 | `25566` |
| `--mc-port` | 本地 MC 端口（房主） | `25565` |
| `--local-port` | 本地监听端口（玩家） | `25565` |
| `--code` | 房间码（玩家模式必填） | — |
| `--bind` | 中继绑定地址 | `0.0.0.0` |
| `--terracotta` | 标记本端使用陶瓦联机 | `false` |

---

## 协议说明

中继服务器与客户端之间使用自定义二进制协议（全部 Big-Endian）：

| 命令 | 方向 | 格式 |
|------|------|------|
| `0x01` REGISTER | 房主→中继 | `[flags(1)] [可选:房间码]` |
| `0x02` JOIN | 玩家→中继 | `[flags(1)] [房间码ASCII]` |
| `0x10` OK | 中继→客户端 | `[房间码ASCII] [UDP端口(2)]` |
| `0x11` ERROR | 中继→客户端 | `[错误信息ASCII]` |
| `0xFF` DATA | 双向 | `[目标PID(2)] [payload]` |
| `0x20` PING | 双向 | 心跳请求 |
| `0x21` PONG | 双向 | 心跳回应 |
| `0x30` PLAYER_JOINED | 中继→房主 | `[PID(1)] [flags(1)]` |
| `0x31` PLAYER_LEFT | 中继→房主 | `[PID(1)]` |
| `0x40` UDP | 双向 | `[PID(2)] [UDP payload]` |

**flags 字段**（1 字节）：
- `bit 0` = `1`：本端使用陶瓦联机
- `bit 1` = `1`：本端请求 UDP 中继

---

## 构建 & 开发

### 依赖

```
PyQt5>=5.15
asyncio  # Python 3.8+ 内置
```

### 运行测试

```bash
# 运行单元测试（需先启动本地中继）
python test_relay.py
```

### 打包为可执行文件

```bash
pip install pyinstaller
pyinstaller --onefile --windowed launcher.py
```

---

## 常见问题

### Q: 中继服务器必须公网 IP 吗？

是的。中继服务器需要被房主和所有玩家访问。如果没有公网 IP 的机器，可以使用：
- 云主机（腾讯云/阿里云等，最低配即可）
- 友人的公网机器
- 使用免费的第三方中继（需自行部署）

### Q: 和陶瓦联机有什么区别？

| | 本工具 | 陶瓦联机 |
|--|--------|----------|
| 原理 | TCP 中继（需中继服务器） | P2P VPN（EasyTier） |
| 需要公网服务器 | ✅ 是 | ❌ 否（部分场景） |
| 延迟 | 取决于中继服务器 | 更优（直连） |
| 房间码格式 | 6 位 或 陶瓦格式 | `U/XXXX-XXXX-XXXX-XXXX` |
| 适合场景 | 有公网服务器、好友房间固定 | 无公网 IP、临时联机 |

### Q: 支持基岩版（手机版）吗？

当前仅支持 Java 版。基岩版协议不同，需要额外适配。

### Q: 延迟高怎么办？

- 选择地理位置更近的中继服务器
- 房主和玩家尝试使用陶瓦联机（P2P 直连延迟更低）
- 检查本地网络上行带宽

---

## 开源协议

[MIT License](LICENSE)

## 致谢

- [陶瓦联机 (Terracotta)](https://github.com/burningtnt/Terracotta) — 房间码格式参考
- [EasyTier](https://github.com/EasyTier/EasyTier) — P2P VPN 方案

## 贡献

Issue 和 Pull Request 均欢迎！

---

>📌 **注意**：本项目与陶瓦联机为独立项目，房间码格式兼容仅为方便用户，两者底层实现不同。
>
> ---
(注：该项目为WorkBuddy AI生成，仅限中国用户使用)
