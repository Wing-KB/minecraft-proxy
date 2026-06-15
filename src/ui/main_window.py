"""
PyQt5 主窗口
跨平台 GUI，支持 Windows、Linux、macOS
"""
import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QTabWidget, QGroupBox,
    QFormLayout, QComboBox, QSpinBox, QCheckBox, QListWidget,
    QStatusBar, QScrollArea, QTextEdit, QMessageBox
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont

class MainWindow(QMainWindow):
    """主窗口"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Minecraft 异地联机工具 v1.0")
        self.setMinimumSize(900, 650)
        
        self._mode = "idle"
        self._room_code = ""
        
        self._init_ui()
        self._init_status_bar()
        
        self._timer = QTimer()
        self._timer.timeout.connect(self._update_status)
        self._timer.start(1000)
    
    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
        self._create_home_tab()
        self._create_host_tab()
        self._create_join_tab()
        self._create_voice_tab()
        self._create_settings_tab()
    
    def _create_home_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setAlignment(Qt.AlignCenter)
        
        title = QLabel("🎮 Minecraft 异地联机工具")
        title.setFont(QFont("Microsoft YaHei", 24, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        subtitle = QLabel("支持 PCLCE / HMCL / FCL / ZCL 陶瓦联机")
        subtitle.setFont(QFont("Microsoft YaHei", 12))
        subtitle.setStyleSheet("color: gray;")
        layout.addWidget(subtitle)
        
        layout.addSpacing(30)
        
        btn_layout = QHBoxLayout()
        self.btn_host = QPushButton("🏠 创建房主\n作为房主创建房间")
        self.btn_host.setMinimumSize(180, 100)
        self.btn_host.clicked.connect(lambda: self.tabs.setCurrentIndex(1))
        btn_layout.addWidget(self.btn_host)
        
        self.btn_join = QPushButton("🔗 加入游戏\n输入房间码加入")
        self.btn_join.setMinimumSize(180, 100)
        self.btn_join.clicked.connect(lambda: self.tabs.setCurrentIndex(2))
        btn_layout.addWidget(self.btn_join)
        
        layout.addLayout(btn_layout)
        layout.addStretch()
        
        self.tabs.addTab(tab, "🏠 首页")
    
    def _create_host_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 服务器设置
        group = QGroupBox("服务器设置")
        form = QFormLayout()
        
        self.host_name = QLineEdit()
        self.host_name.setText("我的世界")
        form.addRow("房间名称:", self.host_name)
        
        self.host_port = QSpinBox()
        self.host_port.setRange(10000, 65535)
        self.host_port.setValue(25565)
        form.addRow("Minecraft 端口:", self.host_port)
        
        group.setLayout(form)
        layout.addWidget(group)
        
        # 房间信息
        room_group = QGroupBox("房间信息")
        room_layout = QVBoxLayout()
        
        self.room_code_label = QLabel("房间码: -")
        self.room_code_label.setFont(QFont("Consolas", 20, QFont.Bold))
        self.room_code_label.setAlignment(Qt.AlignCenter)
        self.room_code_label.setStyleSheet("color: #2196F3; background: #E3F2FD; padding: 15px; border-radius: 8px;")
        room_layout.addWidget(self.room_code_label)
        
        btn_row = QHBoxLayout()
        self.btn_copy = QPushButton("📋 复制房间码")
        self.btn_copy.clicked.connect(self._copy_code)
        btn_row.addWidget(self.btn_copy)
        
        self.btn_start = QPushButton("🚀 开始联机")
        self.btn_start.setStyleSheet("background: #4CAF50; color: white; padding: 10px;")
        self.btn_start.clicked.connect(self._start_host)
        btn_row.addWidget(self.btn_start)
        
        room_layout.addLayout(btn_row)
        room_group.setLayout(room_layout)
        layout.addWidget(room_group)
        
        # 玩家列表
        player_group = QGroupBox("已连接玩家")
        player_layout = QVBoxLayout()
        self.player_list = QListWidget()
        self.player_list.addItem("等待玩家加入...")
        player_layout.addWidget(self.player_list)
        player_group.setLayout(player_layout)
        layout.addWidget(player_group)
        
        layout.addStretch()
        self.tabs.addTab(tab, "🏠 房主模式")
    
    def _create_join_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        group = QGroupBox("加入房间")
        form = QFormLayout()
        
        self.join_code = QLineEdit()
        self.join_code.setPlaceholderText("输入 6 位房间码")
        self.join_code.setMaxLength(6)
        self.join_code.setFont(QFont("Consolas", 16))
        self.join_code.setAlignment(Qt.AlignCenter)
        form.addRow("房间码:", self.join_code)
        
        self.join_server = QLineEdit()
        self.join_server.setPlaceholderText("中继服务器地址")
        form.addRow("服务器地址:", self.join_server)
        
        self.join_name = QLineEdit()
        self.join_name.setText("玩家")
        form.addRow("玩家名称:", self.join_name)
        
        group.setLayout(form)
        layout.addWidget(group)
        
        self.btn_connect = QPushButton("🔗 连接")
        self.btn_connect.setStyleSheet("background: #2196F3; color: white; padding: 15px;")
        self.btn_connect.clicked.connect(self._connect)
        layout.addWidget(self.btn_connect)
        
        layout.addStretch()
        self.tabs.addTab(tab, "🔗 加入游戏")
    
    def _create_voice_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        group = QGroupBox("语音聊天设置")
        form = QFormLayout()
        
        self.voice_enabled = QCheckBox("启用语音聊天 (Voice Chat Mod)")
        self.voice_enabled.setChecked(True)
        form.addRow("", self.voice_enabled)
        
        self.voice_port = QSpinBox()
        self.voice_port.setRange(10000, 65535)
        self.voice_port.setValue(24454)
        form.addRow("UDP 端口:", self.voice_port)
        
        group.setLayout(form)
        layout.addWidget(group)
        
        self.voice_status = QLabel("🟢 就绪")
        self.voice_status.setFont(QFont("Microsoft YaHei", 12))
        layout.addWidget(self.voice_status)
        
        layout.addStretch()
        self.tabs.addTab(tab, "🎤 语音设置")
    
    def _create_settings_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        group = QGroupBox("关于")
        about = QLabel(
            "Minecraft 异地联机工具 v1.0\n\n"
            "支持 PCLCE / HMCL / FCL / ZCL 陶瓦联机协议\n"
            "内置 UDP 语音聊天支持\n\n"
            "基于 Python 3 + PyQt5 开发"
        )
        about.setAlignment(Qt.AlignCenter)
        layout.addWidget(about)
        
        self.tabs.addTab(tab, "⚙ 设置")
    
    def _init_status_bar(self):
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("就绪")
    
    def _copy_code(self):
        if self._room_code:
            QApplication.clipboard().setText(self._room_code)
            QMessageBox.information(self, "复制成功", f"房间码 {self._room_code} 已复制")
    
    def _start_host(self):
        import random
        chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        self._room_code = "".join(random.choice(chars) for _ in range(6))
        self.room_code_label.setText(f"房间码: {self._room_code}")
        self._mode = "host"
        self.status.showMessage(f"房间已创建: {self._room_code}")
    
    def _connect(self):
        code = self.join_code.text().upper()
        if len(code) == 6:
            self._room_code = code
            self._mode = "client"
            self.status.showMessage(f"正在连接到房间 {code}...")
    
    def _update_status(self):
        if self._mode == "host":
            self.status.showMessage(f"房主模式 | 房间: {self._room_code}")
        elif self._mode == "client" and self._room_code:
            self.status.showMessage(f"已连接到房间: {self._room_code}")

def run_ui():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei", 10))
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec_())
