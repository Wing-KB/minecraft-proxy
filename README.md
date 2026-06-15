# Minecraft Cross-Region Proxy

Minecraft 异地联机工具，支持 PCLCE / HMCL / FCL / ZCL 陶瓦联机协议。

## 功能特性

- **NAT 打洞**: TCP/UDP 双协议 NAT 穿透
- **中继服务器**: 穿透失败时自动降级为中继模式
- **协议兼容**: PCLCE、HMCL、FCL、ZCL 陶瓦联机
- **UDP 语音**: 支持 Voice Chat Mod
- **跨平台 UI**: PyQt5 (Windows / Linux / macOS)

## 安装

```bash
pip install -r requirements.txt
```

## 运行

```bash
# GUI 模式
python launcher.py

# 命令行 - 房主
python launcher.py --mode server --port 25565 --name "我的世界"

# 命令行 - 玩家
python launcher.py --mode client --server 127.0.0.1 --code ABC123
```

## 许可证

MIT License
