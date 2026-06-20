"""
PyQt5 主窗口 —— 自动检测陶瓦联机
- 无需手动勾选，自动检测本地是否运行陶瓦/EasyTier
- 检测到陶瓦 → 自动禁用 UDP 中继（避免冲突）
- 未检测到陶瓦 → 自动启用 UDP 中继
"""

import sys
import asyncio
import threading
import logging
from typing import Optional

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QTabWidget, QGroupBox,
    QFormLayout, QSpinBox, QStatusBar, QTextEdit,
    QMessageBox
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QFont

logger = logging.getLogger(__name__)


# ── 异步桥 ─────────────────────────────────────────────

class AsyncBridge(QObject):
    status_signal  = pyqtSignal(str)
    code_signal    = pyqtSignal(str)
    count_signal   = pyqtSignal(int)
    error_signal   = pyqtSignal(str)
    ready_signal   = pyqtSignal()
    stopped_signal = pyqtSignal()
    terracotta_signal = pyqtSignal(bool, str)

    def __init__(self):
        super().__init__()
        self._loop = None
        self._thread = None
        self._server = None
        self._client = None

    def _ensure_loop(self):
        if self._loop is None or not self._loop.is_running():
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(
                target=self._loop.run_forever, daemon=True
            )
            self._thread.start()

    def start_host(self, relay_host, relay_port,
                   mc_host, mc_port,
                   requested_code=""):
        self._ensure_loop()
        asyncio.run_coroutine_threadsafe(
            self._run_host(relay_host, relay_port, mc_host, mc_port,
                           requested_code),
            self._loop
        )

    def start_player(self, relay_host, relay_port,
                    room_code, local_port):
        self._ensure_loop()
        asyncio.run_coroutine_threadsafe(
            self._run_player(relay_host, relay_port, room_code, local_port),
            self._loop
        )

    def stop_all(self):
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._stop(), self._loop)

    async def _run_host(self, relay_host, relay_port, mc_host, mc_port,
                        requested_code):
        from ..core.host_session import HostSession
        self._server = HostSession(
            relay_host=relay_host,
            relay_port=relay_port,
            mc_host=mc_host,
            mc_port=mc_port,
            on_status=lambda m: self.status_signal.emit(m),
            on_player_count=lambda n: self.count_signal.emit(n),
            on_room_code=lambda c: self.code_signal.emit(c),
            on_terracotta_detected=lambda f, s: self.terracotta_signal.emit(f, s),
        )
        try:
            code = await self._server.start(requested_code)
            self.code_signal.emit(code)
            await self._server.wait_until_stopped()
        except Exception as e:
            self.error_signal.emit(str(e))
        finally:
            self.stopped_signal.emit()
            self._server = None

    async def _run_player(self, relay_host, relay_port, room_code, local_port):
        from ..core.player_session import PlayerSession
        self._client = PlayerSession(
            relay_host=relay_host,
            relay_port=relay_port,
            room_code=room_code,
            local_host="127.0.0.1",
            local_port=local_port,
            on_status=lambda m: self.status_signal.emit(m),
            on_terracotta_detected=lambda f, s: self.terracotta_signal.emit(f, s),
        )
        try:
            await self._client.connect()
            self.ready_signal.emit()
            await self._client.start_local()
            await self._client.wait_until_stopped()
        except Exception as e:
            self.error_signal.emit(str(e))
        finally:
            self.stopped_signal.emit()
            self._client = None

    async def _stop(self):
        if self._server:
            await self._server.stop()
        if self._client:
            await self._client.stop()


# ── 主窗口 ────────────────────────────────────────────────

class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Minecraft 异地联机工具")
        self.setMinimumSize(900, 660)

        self._bridge = AsyncBridge()
        self._bridge.status_signal.connect(self._on_status)
        self._bridge.code_signal.connect(self._on_room_code_received)
        self._bridge.count_signal.connect(self._on_player_count)
        self._bridge.error_signal.connect(self._on_error)
        self._bridge.ready_signal.connect(self._on_player_ready)
        self._bridge.stopped_signal.connect(self._on_session_stopped)
        self._bridge.terracotta_signal.connect(self._on_terracotta_detected)

        self._mode = "idle"
        self._room_code = ""
        self._player_count = 0

        self._init_ui()
        self._init_status_bar()

        self._timer = QTimer()
        self._timer.timeout.connect(self._update_status_bar)
        self._timer.start(1000)

    # ── UI 构建 ──────────────────────────────────────────

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self._create_host_tab()
        self._create_join_tab()
        self._create_relay_tab()
        self._create_log_tab()
        self._create_about_tab()

    def _create_host_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        g1 = QGroupBox("本地 Minecraft 服务器")
        f1 = QFormLayout()
        self.host_mc_host = QLineEdit("127.0.0.1")
        f1.addRow("MC 地址:", self.host_mc_host)
        self.host_mc_port = QSpinBox()
        self.host_mc_port.setRange(1024, 65535)
        self.host_mc_port.setValue(25565)
        f1.addRow("MC 端口:", self.host_mc_port)
        g1.setLayout(f1)
        layout.addWidget(g1)

        g2 = QGroupBox("中继服务器")
        f2 = QFormLayout()
        self.host_relay = QLineEdit()
        self.host_relay.setPlaceholderText("中继服务器 IP 或域名")
        f2.addRow("中继地址:", self.host_relay)
        self.host_relay_port = QSpinBox()
        self.host_relay_port.setRange(1024, 65535)
        self.host_relay_port.setValue(25566)
        f2.addRow("中继端口:", self.host_relay_port)
        g2.setLayout(f2)
        layout.addWidget(g2)

        # 陶瓦检测状态（自动，无需勾选）
        g_opt = QGroupBox("联机状态（自动检测）")
        opt_layout = QVBoxLayout()
        self.host_terracotta_label = QLabel("正在检测陶瓦联机状态...")
        self.host_terracotta_label.setFont(QFont("Microsoft YaHei", 10))
        opt_layout.addWidget(self.host_terracotta_label)
        g_opt.setLayout(opt_layout)
        layout.addWidget(g_opt)

        self.host_req_code = QLineEdit()
        self.host_req_code.setPlaceholderText("可选：指定房间码（6位 或 陶瓦格式 U/XXXX-...）")
        self.host_req_code.setMaxLength(21)
        layout.addWidget(QLabel("指定房间码（可选）:"))
        layout.addWidget(self.host_req_code)

        g3 = QGroupBox("房间码（创建后分享给好友）")
        room_layout = QVBoxLayout()
        self.room_code_label = QLabel("——")
        self.room_code_label.setFont(QFont("Consolas", 28, QFont.Bold))
        self.room_code_label.setAlignment(Qt.AlignCenter)
        self.room_code_label.setStyleSheet(
            "color: #1976D2; background: #E3F2FD; padding: 18px; "
            "border-radius: 8px; letter-spacing: 6px;"
        )
        room_layout.addWidget(self.room_code_label)

        btn_row = QHBoxLayout()
        self.btn_copy_code = QPushButton("📋 复制房间码")
        self.btn_copy_code.setEnabled(False)
        self.btn_copy_code.clicked.connect(self._copy_code)
        btn_row.addWidget(self.btn_copy_code)

        self.btn_start_host = QPushButton("🚀 开始联机")
        self.btn_start_host.setStyleSheet(
            "background: #4CAF50; color: white; padding: 10px; font-size: 14px;"
        )
        self.btn_start_host.clicked.connect(self._start_host)
        btn_row.addWidget(self.btn_start_host)

        self.btn_stop_host = QPushButton("⏹ 停止")
        self.btn_stop_host.setEnabled(False)
        self.btn_stop_host.setStyleSheet("background: #f44336; color: white; padding: 10px;")
        self.btn_stop_host.clicked.connect(self._stop_session)
        btn_row.addWidget(self.btn_stop_host)

        room_layout.addLayout(btn_row)
        g3.setLayout(room_layout)
        layout.addWidget(g3)

        g4 = QGroupBox("已连接玩家")
        player_layout = QVBoxLayout()
        self.player_count_label = QLabel("等待玩家加入...")
        self.player_count_label.setFont(QFont("Microsoft YaHei", 11))
        player_layout.addWidget(self.player_count_label)
        g4.setLayout(player_layout)
        layout.addWidget(g4)

        layout.addStretch()
        self.tabs.addTab(tab, "🏠 房主模式")

    def _create_join_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        g1 = QGroupBox("加入联机房间")
        f1 = QFormLayout()

        self.join_code = QLineEdit()
        self.join_code.setPlaceholderText("输入房间码（6位 或 陶瓦格式 U/XXXX-...）")
        self.join_code.setMaxLength(21)
        self.join_code.setFont(QFont("Consolas", 16))
        self.join_code.setAlignment(Qt.AlignCenter)
        f1.addRow("房间码:", self.join_code)

        self.join_relay = QLineEdit()
        self.join_relay.setPlaceholderText("中继服务器 IP 或域名")
        f1.addRow("中继地址:", self.join_relay)

        self.join_relay_port = QSpinBox()
        self.join_relay_port.setRange(1024, 65535)
        self.join_relay_port.setValue(25566)
        f1.addRow("中继端口:", self.join_relay_port)

        self.join_local_port = QSpinBox()
        self.join_local_port.setRange(1024, 65535)
        self.join_local_port.setValue(25565)
        f1.addRow("本地监听端口:", self.join_local_port)

        g1.setLayout(f1)
        layout.addWidget(g1)

        # 陶瓦检测状态（自动，无需勾选）
        g_opt = QGroupBox("联机状态（自动检测）")
        opt_layout = QVBoxLayout()
        self.join_terracotta_label = QLabel("正在检测陶瓦联机状态...")
        self.join_terracotta_label.setFont(QFont("Microsoft YaHei", 10))
        opt_layout.addWidget(self.join_terracotta_label)
        g_opt.setLayout(opt_layout)
        layout.addWidget(g_opt)

        self.join_status_label = QLabel("")
        self.join_status_label.setAlignment(Qt.AlignCenter)
        self.join_status_label.setFont(QFont("Microsoft YaHei", 11))
        layout.addWidget(self.join_status_label)

        btn_row = QHBoxLayout()
        self.btn_connect = QPushButton("🔗 加入游戏")
        self.btn_connect.setStyleSheet(
            "background: #2196F3; color: white; padding: 12px; font-size: 14px;"
        )
        self.btn_connect.clicked.connect(self._start_player)
        btn_row.addWidget(self.btn_connect)

        self.btn_stop_player = QPushButton("⏹ 断开")
        self.btn_stop_player.setEnabled(False)
        self.btn_stop_player.setStyleSheet("background: #f44336; color: white; padding: 12px;")
        self.btn_stop_player.clicked.connect(self._stop_session)
        btn_row.addWidget(self.btn_stop_player)
        layout.addLayout(btn_row)

        tip = QLabel(
            "💡 加入成功后，在 Minecraft 中选择「多人游戏 → 直接连接」\n"
            "   输入 127.0.0.1（端口即上方「本地监听端口」）即可进入"
        )
        tip.setStyleSheet("color: #555; background: #fffde7; padding: 10px; border-radius: 4px;")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        layout.addStretch()
        self.tabs.addTab(tab, "🔗 加入游戏")

    def _create_relay_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        g1 = QGroupBox("内置中继服务器（需运行在有公网 IP 的机器上）")
        f1 = QFormLayout()
        self.relay_bind = QLineEdit("0.0.0.0")
        f1.addRow("监听地址:", self.relay_bind)
        self.relay_port_spin = QSpinBox()
        self.relay_port_spin.setRange(1024, 65535)
        self.relay_port_spin.setValue(25566)
        f1.addRow("TCP 端口:", self.relay_port_spin)
        g1.setLayout(f1)
        layout.addWidget(g1)

        btn_row = QHBoxLayout()
        self.btn_start_relay = QPushButton("▶ 启动中继服务器")
        self.btn_start_relay.setStyleSheet("background: #FF9800; color: white; padding: 10px;")
        self.btn_start_relay.clicked.connect(self._start_relay)
        btn_row.addWidget(self.btn_start_relay)

        self.btn_stop_relay = QPushButton("⏹ 停止中继")
        self.btn_stop_relay.setEnabled(False)
        self.btn_stop_relay.clicked.connect(self._stop_relay)
        btn_row.addWidget(self.btn_stop_relay)
        layout.addLayout(btn_row)

        self.relay_status_label = QLabel("中继服务器未运行")
        self.relay_status_label.setFont(QFont("Microsoft YaHei", 11))
        layout.addWidget(self.relay_status_label)

        tip = QLabel(
            "💡 如果你有公网 IP，可以在这里启动中继服务器让好友连接。\n"
            "   UDP 中继端口 = TCP 端口 + 1（如 TCP=25566 则 UDP=25567）\n"
            "   房间内有陶瓦用户时，UDP 中继自动禁用"
        )
        tip.setStyleSheet("color: #555; background: #fffde7; padding: 10px; border-radius: 4px;")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        layout.addStretch()
        self.tabs.addTab(tab, "🖥 中继服务器")

    def _create_log_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setStyleSheet("background: #1e1e1e; color: #d4d4d4;")
        layout.addWidget(self.log_text)
        self.tabs.addTab(tab, "📋 日志")

    def _create_about_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setAlignment(Qt.AlignCenter)

        about = QLabel(
            "Minecraft 异地联机工具\n\n"
            "基于 TCP 中继的异地联机方案，支持陶瓦联机房间码格式\n"
            "自动检测本地陶瓦联机状态，无需手动设置\n\n"
            "使用步骤：\n"
            "① 房主：确保 MC 服务器已开启，填写中继地址，点击「开始联机」\n"
            "   获得房间码后分享给好友\n"
            "② 玩家：填写中继地址和房间码，点击「加入游戏」\n"
            "   在 MC 中连接 127.0.0.1:25565 即可进入\n\n"
            "GitHub: Wing-KB/minecraft-proxy\n"
            "陶瓦联机: burningtnt/Terracotta"
        )
        about.setAlignment(Qt.AlignCenter)
        about.setFont(QFont("Microsoft YaHei", 10))
        about.setWordWrap(True)
        layout.addWidget(about)

        self.tabs.addTab(tab, "ℹ 关于")

    def _init_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

    # ── 事件处理 ──────────────────────────────────────────

    def _start_host(self):
        relay = self.host_relay.text().strip()
        if not relay:
            QMessageBox.warning(self, "配置错误", "请填写中继服务器地址")
            return
        self._mode = "host"
        self.btn_start_host.setEnabled(False)
        self.btn_stop_host.setEnabled(True)
        self.room_code_label.setText("连接中...")
        self._append_log(
            f"启动房主模式 → 中继: {relay}:{self.host_relay_port.value()}"
        )
        self._bridge.start_host(
            relay_host=relay,
            relay_port=self.host_relay_port.value(),
            mc_host=self.host_mc_host.text().strip() or "127.0.0.1",
            mc_port=self.host_mc_port.value(),
            requested_code=self.host_req_code.text().strip(),
        )

    def _start_player(self):
        relay = self.join_relay.text().strip()
        code = self.join_code.text().strip()
        if not relay:
            QMessageBox.warning(self, "配置错误", "请填写中继服务器地址")
            return
        if not code:
            QMessageBox.warning(self, "配置错误", "请输入房间码")
            return
        if len(code) != 6 and not code.startswith("U/"):
            QMessageBox.warning(
                self, "格式错误",
                "房间码格式不正确\n"
                "支持格式：6 位字母数字（如 AB3C2D）\n"
                "或陶瓦格式（如 U/8F2K-3M7Q-1X9Z-5N4J）"
            )
            return

        self._mode = "player"
        self.btn_connect.setEnabled(False)
        self.btn_stop_player.setEnabled(True)
        self.join_status_label.setText("正在连接...")
        self._append_log(f"加入房间 {code} → 中继: {relay}:{self.join_relay_port.value()}")
        self._bridge.start_player(
            relay_host=relay,
            relay_port=self.join_relay_port.value(),
            room_code=code,
            local_port=self.join_local_port.value(),
        )

    def _stop_session(self):
        self._bridge.stop_all()

    def _copy_code(self):
        if self._room_code:
            QApplication.clipboard().setText(self._room_code)
            self.status_bar.showMessage(f"房间码 {self._room_code} 已复制！", 3000)

    # 内置中继
    def _start_relay(self):
        bind = self.relay_bind.text().strip() or "0.0.0.0"
        port = self.relay_port_spin.value()
        self._bridge._ensure_loop()
        asyncio.run_coroutine_threadsafe(
            self._run_relay(bind, port), self._bridge._loop
        )
        self.relay_status_label.setText(f"🟢 中继服务器运行中: {bind}:{port}")
        self.btn_start_relay.setEnabled(False)
        self.btn_stop_relay.setEnabled(True)
        self._append_log(f"内置中继服务器已启动: {bind}:{port}")

    def _stop_relay(self):
        if hasattr(self, '_relay_server_obj') and self._relay_server_obj:
            asyncio.run_coroutine_threadsafe(
                self._relay_server_obj.stop(), self._bridge._loop
            )
        self.relay_status_label.setText("中继服务器未运行")
        self.btn_start_relay.setEnabled(True)
        self.btn_stop_relay.setEnabled(False)
        self._append_log("内置中继服务器已停止")

    async def _run_relay(self, bind, port):
        from ..core.relay_server import RelayServer
        self._relay_server_obj = RelayServer(bind, port)
        await self._relay_server_obj.serve_forever()

    # ── 信号槽 ────────────────────────────────────────

    def _on_status(self, msg: str):
        self._append_log(msg)
        self.status_bar.showMessage(msg)
        if self._mode == "player":
            self.join_status_label.setText(msg)

    def _on_room_code_received(self, code: str):
        self._room_code = code
        self.room_code_label.setText(code)
        self.btn_copy_code.setEnabled(True)
        self.status_bar.showMessage(f"房间已就绪！房间码: {code}")
        self._append_log(f"✅ 房间码: {code}，等待好友加入")

    def _on_player_count(self, n: int):
        self._player_count = n
        self.player_count_label.setText(
            f"无玩家连接" if n == 0 else f"当前玩家数: {n}"
        )

    def _on_error(self, msg: str):
        self._append_log(f"❌ 错误: {msg}")
        QMessageBox.critical(self, "错误", msg)
        self._reset_ui()

    def _on_player_ready(self):
        port = self.join_local_port.value()
        msg = f"✅ 连接成功！请在 Minecraft 中连接 127.0.0.1:{port}"
        self.join_status_label.setText(msg)
        self.join_status_label.setStyleSheet("color: green;")
        self._append_log(msg)

    def _on_session_stopped(self):
        self._append_log("会话已结束")
        self._reset_ui()

    def _on_terracotta_detected(self, detected, status):
        """陶瓦检测结果的 UI 回调（房主端和玩家端共用）"""
        color = "#4CAF50" if detected else "#757575"
        icon = "✅" if detected else "❌"
        text = f"{icon} {status}"
        if self._mode == "host" or self.tabs.currentIndex() == 0:
            self.host_terracotta_label.setText(text)
            self.host_terracotta_label.setStyleSheet(f"color: {color}; padding: 4px;")
        if self._mode == "player" or self.tabs.currentIndex() == 1:
            self.join_terracotta_label.setText(text)
            self.join_terracotta_label.setStyleSheet(f"color: {color}; padding: 4px;")

    def _reset_ui(self):
        self._mode = "idle"
        self.btn_start_host.setEnabled(True)
        self.btn_stop_host.setEnabled(False)
        self.room_code_label.setText("——")
        self._room_code = ""
        self.btn_copy_code.setEnabled(False)
        self.player_count_label.setText("等待玩家加入...")
        self.btn_connect.setEnabled(True)
        self.btn_stop_player.setEnabled(False)
        self.join_status_label.setText("")
        self.join_status_label.setStyleSheet("")

    def _append_log(self, msg: str):
        self.log_text.append(msg)

    def _update_status_bar(self):
        if self._mode == "host" and self._room_code:
            self.status_bar.showMessage(
                f"房主模式 | 房间: {self._room_code} | 玩家: {self._player_count}"
            )

    def closeEvent(self, event):
        self._bridge.stop_all()
        event.accept()


# ── Qt 日志处理器 ─────────────────────────────────────────

class _QtLogHandler(logging.Handler):
    def __init__(self, callback):
        super().__init__()
        self._cb = callback

    def emit(self, record):
        try:
            self._cb(self.format(record))
        except Exception:
            pass


def run_ui():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei", 10))

    window = MainWindow()

    handler = _QtLogHandler(window._append_log)
    handler.setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)

    window.show()
    sys.exit(app.exec_())
