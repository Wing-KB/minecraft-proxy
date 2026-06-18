# Minecraft Cross-Region Proxy

Minecraft 异地联机工具 v2.0 —— 真正可用的 TCP 中继联机方案

支持 HMCL / PCL2 / BakaXL / 原版启动器，任何能连接 Minecraft 服务器的客户端均可使用。

## 原理

```
MC客户端 ──连─→ 127.0.0.1:25565（玩家端） ──→ 中继服务器 ──→ 房主端 ──→ MC服务器
```

- **中继服务器**：部署在有公网 IP 的机器上，负责转发流量
- **房主端**：开启本地 MC 服务器，运行房主程序，获得房间码，把房间码分享给好友
- **玩家端**：输入房间码，连上中继，在本地 127.0.0.1:25565 监听，MC 客户端连这里即可

## 安装

```bash
pip install -r requirements.txt
```

## 快速开始

### GUI 模式（推荐）

```bash
python launcher.py
```

### 命令行模式

**1. 启动中继服务器**（需要有公网 IP 的机器，或内网测试）

```bash
python launcher.py --relay-server --bind 0.0.0.0 --relay-port 25566
```

**2. 房主端**

```bash
python launcher.py --mode host --relay 中继服务器IP --relay-port 25566 --mc-port 25565
```

控制台会显示房间码，分享给好友。

**3. 玩家端**

```bash
python launcher.py --mode client --relay 中继服务器IP --relay-port 25566 --code ABCDEF --local-port 25565
```

成功后，在 Minecraft 中「多人游戏 → 直接连接」，输入 `127.0.0.1:25565` 即可进入。

## 使用步骤（图文说明）

1. **房主**：打开 MC，开启单人存档（允许局域网联机），或开好 MC 服务器
2. **房主**：GUI → 「房主模式」→ 填写中继服务器地址 → 点「开始联机」→ 等待房间码出现
3. **房主**：把房间码发给好友（如 `AB3C2D`）
4. **玩家**：GUI → 「加入游戏」→ 填写中继地址 + 房间码 → 点「加入游戏」
5. **玩家**：在 Minecraft 「多人游戏 → 直接连接」→ 输入 `127.0.0.1:25565`

## 架构说明

```
src/
├── core/
│   ├── relay_server.py   # 中继服务器（核心）
│   ├── host_session.py   # 房主端会话
│   ├── player_session.py # 玩家端会话
│   ├── server.py         # ProxyServer 包装
│   └── client.py         # ProxyClient 包装
└── ui/
    └── main_window.py    # PyQt5 GUI
```

## 协议说明

使用自定义的轻量二进制协议：

| 命令 | 值 | 说明 |
|------|-----|------|
| REGISTER | 0x01 | 房主注册房间 |
| JOIN | 0x02 | 玩家加入房间 |
| OK | 0x10 | 操作成功 |
| ERROR | 0x11 | 操作失败 |
| DATA | 0xFF | 转发的 MC 流量 |
| PING/PONG | 0x20/0x21 | 心跳保活 |

## 测试

```bash
python test_relay.py
```

## 注意事项

- **中继服务器需要公网 IP**：房主和玩家必须都能访问到中继服务器
- **防火墙**：确保中继端口（默认 25566）已开放
- **MC 服务器**：房主端的 MC 服务器需要在运行状态（单人开启局域网或独立服务器）
- **延迟**：取决于中继服务器与双方的网络距离

## 许可证

MIT License
