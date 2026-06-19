import sys
import os
import winreg
import subprocess
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent
from PySide6.QtWidgets import (
    QApplication, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QComboBox,
    QLineEdit, QCheckBox, QFormLayout, QMessageBox, QColorDialog,
    QInputDialog, QTextEdit, QFileDialog, QGroupBox
)
import src.db as db
import src.wallpaper as wp
from src.hotkey import test_hotkey_availability


def set_startup_registry(enabled):
    """Windowsのスタートアップレジストリを設定または解除します。"""
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    app_name = "WallpaperStickyNotes"
    
    if getattr(sys, 'frozen', False):
        exe_path = sys.executable
        cmd = f'"{exe_path}"'
    else:
        # スクリプト実行環境の場合
        python_exe = sys.executable
        if python_exe.endswith("python.exe"):
            python_exe = python_exe.replace("python.exe", "pythonw.exe")
        script_dir = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.abspath(os.path.join(script_dir, "app.py"))
        cmd = f'"{python_exe}" "{script_path}"'
        
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        if enabled:
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, cmd)
            print("Startup registry updated: ENABLED")
        else:
            try:
                winreg.DeleteValue(key, app_name)
                print("Startup registry updated: DISABLED")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception as e:
        print("Failed to update startup registry:", e)

def set_startup_shortcut(enabled):
    """Windowsのスタートアップフォルダにショートカットを追加または削除します。"""
    startup_dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), r"Microsoft\Windows\Start Menu\Programs\Startup")
    shortcut_path = os.path.join(startup_dir, "WallpaperStickyNotes.lnk")
    
    if enabled:
        if getattr(sys, 'frozen', False):
            target = sys.executable
            arguments = ""
        else:
            target = sys.executable
            if target.endswith("python.exe"):
                target = target.replace("python.exe", "pythonw.exe")
            script_dir = os.path.dirname(os.path.abspath(__file__))
            script_path = os.path.abspath(os.path.join(script_dir, "app.py"))
            arguments = f'"{script_path}"'
            
        cmd = f'$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut("{shortcut_path}"); $Shortcut.TargetPath = "{target}"; $Shortcut.Arguments = \'{arguments}\'; $Shortcut.WindowStyle = 7; $Shortcut.Save()'
        try:
            subprocess.run(["powershell", "-Command", cmd], capture_output=True, check=True)
            print("Startup shortcut updated: ENABLED")
        except Exception as e:
            print("Failed to update startup shortcut:", e)
    else:
        if os.path.exists(shortcut_path):
            try:
                os.remove(shortcut_path)
                print("Startup shortcut updated: DISABLED")
            except Exception as e:
                print("Failed to remove startup shortcut:", e)

class HotkeyLineEdit(QLineEdit):
    """グローバルホットキー設定専用の入力欄。キー押下を直接キャプチャします。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("ショートカットキーを押してください... (ESCでクリア)")
        self.setReadOnly(True)
        self.setStyleSheet("""
            QLineEdit {
                background-color: #2D2D30;
                color: #F1F1F1;
                border: 1px solid #3F3F46;
                padding: 6px;
                border-radius: 4px;
            }
            QLineEdit:focus {
                border: 1px solid #007ACC;
                background-color: #1E1E1E;
            }
        """)

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        modifiers = event.modifiers()

        # ESCキーまたはBackspace/Deleteが押された場合はクリア
        if key in (Qt.Key_Escape, Qt.Key_Backspace, Qt.Key_Delete):
            self.setText("")
            self.clearFocus()
            return

        # 修飾キーのみが押された場合は無視
        if key in (Qt.Key_Control, Qt.Key_Alt, Qt.Key_Shift, Qt.Key_Meta):
            super().keyPressEvent(event)
            return

        # 修飾キーのパース
        parts = []
        if modifiers & Qt.ControlModifier:
            parts.append("Ctrl")
        if modifiers & Qt.AltModifier:
            parts.append("Alt")
        if modifiers & Qt.ShiftModifier:
            parts.append("Shift")
        if modifiers & Qt.MetaModifier:
            parts.append("Win")

        # 何かしらの修飾キーが押されていることを要求する（単一キーでのグローバルホットキー誤爆防止）
        if not parts:
            return

        # メインキーのパース
        key_str = ""
        if Qt.Key_A <= key <= Qt.Key_Z:
            key_str = chr(key)
        elif Qt.Key_0 <= key <= Qt.Key_9:
            key_str = chr(key)
        elif Qt.Key_F1 <= key <= Qt.Key_F12:
            key_str = f"F{key - Qt.Key_F1 + 1}"
        elif key == Qt.Key_Space:
            key_str = "SPACE"
        elif key == Qt.Key_Return or key == Qt.Key_Enter:
            key_str = "ENTER"
        elif key == Qt.Key_Tab:
            key_str = "TAB"
        else:
            # サポート外のキーは無視
            return

        parts.append(key_str)
        hotkey_str = "+".join(parts)
        self.setText(hotkey_str)
        self.clearFocus()

class ManageTab(QWidget):
    """メモ管理タブ。一覧表示、新規追加、編集、ステータス変更。"""
    data_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 上部アクションエリア
        action_layout = QHBoxLayout()
        self.add_btn = QPushButton("新規メモを追加", self)
        self.add_btn.clicked.connect(self.add_memo)
        action_layout.addWidget(self.add_btn)
        
        action_layout.addStretch()
        
        # フィルター用コンボボックス
        self.filter_label = QLabel("表示切替:", self)
        action_layout.addWidget(self.filter_label)
        self.filter_combo = QComboBox(self)
        self.filter_combo.addItems([
            "すべて",
            "表示中のみ",
            "一時非表示のみ",
            "完了のみ",
            "アーカイブのみ"
        ])
        self.filter_combo.currentIndexChanged.connect(self.load_data)
        action_layout.addWidget(self.filter_combo)
        
        self.refresh_btn = QPushButton("再読込", self)
        self.refresh_btn.clicked.connect(self.load_data)
        action_layout.addWidget(self.refresh_btn)
        
        layout.addLayout(action_layout)

        # メトリスト表示
        self.list_widget = QListWidget(self)
        self.list_widget.itemDoubleClicked.connect(self.edit_memo)
        
        # 右クリックコンテキストメニュー設定
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self.show_context_menu)
        
        layout.addWidget(self.list_widget)

        # 下部操作エリア
        btn_layout = QHBoxLayout()
        
        self.edit_btn = QPushButton("編集...", self)
        self.edit_btn.clicked.connect(lambda: self.edit_memo(self.list_widget.currentItem()))
        btn_layout.addWidget(self.edit_btn)

        self.complete_btn = QPushButton("完了 / 未完了", self)
        self.complete_btn.clicked.connect(self.toggle_complete)
        btn_layout.addWidget(self.complete_btn)

        self.delete_btn = QPushButton("削除", self)
        self.delete_btn.clicked.connect(self.delete_memo)
        btn_layout.addWidget(self.delete_btn)
        
        btn_layout.addStretch()
        
        layout.addLayout(btn_layout)
        
        self.load_data()

    def load_data(self):
        self.list_widget.clear()
        
        idx = self.filter_combo.currentIndex()
        filter_map = {
            0: "all",
            1: "active",
            2: "hidden",
            3: "completed",
            4: "archived"
        }
        status_filter = filter_map.get(idx, "all")
        memos = db.get_all_memos(status_filter)
        
        from datetime import datetime
        now = datetime.now()
        
        for memo in memos:
            # スヌーズ状態の判定
            is_snoozed = False
            if memo["status"] == "active" and memo.get("reminder_at") and memo.get("reminder_status") == "pending":
                try:
                    rem_dt = datetime.fromisoformat(memo["reminder_at"])
                    if rem_dt > now:
                        is_snoozed = True
                except Exception:
                    pass
            
            if is_snoozed:
                status_symbol = "💤 [スヌーズ]"
            elif memo["status"] == "active":
                status_symbol = "🟢 [表示中]"
            elif memo["status"] == "hidden":
                status_symbol = "👁️ [非表示]"
            elif memo["status"] == "completed":
                status_symbol = "⚪ [完了]"
            elif memo["status"] == "archived":
                status_symbol = "📦 [アーカイブ]"
            elif memo["status"] == "deleted":
                status_symbol = "🔴 [削除済]"
            else:
                status_symbol = f"❓ [{memo['status']}]"
            
            # メモのプレビュー
            body_preview = memo["body"].replace("\n", " ")
            if len(body_preview) > 30:
                body_preview = body_preview[:30] + "..."
                
            # リマインダー情報の構築
            reminder_str = ""
            if memo.get("reminder_at"):
                try:
                    rem_dt = datetime.fromisoformat(memo["reminder_at"])
                    time_part = rem_dt.strftime("%m/%d %H:%M")
                except Exception:
                    time_part = memo['reminder_at']
                
                if memo.get("reminder_status") == "notified":
                    notified_time = ""
                    if memo.get("reminded_at"):
                        try:
                            reminded_dt = datetime.fromisoformat(memo["reminded_at"])
                            notified_time = reminded_dt.strftime("%m/%d %H:%M")
                        except Exception:
                            notified_time = memo['reminded_at']
                    reminder_str = f"🕐[通知済: {time_part} (実績:{notified_time})]"
                else:
                    if is_snoozed:
                        reminder_str = f"🕐[スヌーズ中: {time_part}]"
                    else:
                        reminder_str = f"🕐[予定: {time_part}]"
            
            item_text = f"{status_symbol} {body_preview}  {reminder_str} (Monitor: {memo['monitor_id']})"
            item = QListWidgetItem(item_text)
            # メモIDをカスタムデータとして保持
            item.setData(Qt.UserRole, memo["id"])
            
            # ステータスごとに文字色をうっすら変えて視認性を上げる
            if is_snoozed:
                item.setForeground(QColor("#007ACC"))
            elif memo["status"] == "completed":
                item.setForeground(QColor("#777777"))
            elif memo["status"] == "hidden":
                item.setForeground(QColor("#A0A0A0"))
            elif memo["status"] == "archived":
                item.setForeground(QColor("#8A8A8A"))
            elif memo["status"] == "deleted":
                item.setForeground(QColor("#B33939"))
                
            self.list_widget.addItem(item)

    def add_memo(self):
        text, ok = QInputDialog.getMultiLineText(self, "新規メモ", "メモ内容を入力してください:")
        if ok and text.strip():
            default_color = db.get_setting("default_note_color", "#FFFFC8")
            
            # テキストの長さに合わせた自動サイズ計算
            from src.gui_overlay import calculate_auto_size
            w, h = calculate_auto_size(text.strip())
            
            db.add_memo(text.strip(), color=default_color, width=w, height=h)
            self.load_data()
            self.data_changed.emit()

    def edit_memo(self, item):
        if not item:
            return
        memo_id = item.data(Qt.UserRole)
        
        # dbから最新のメモ情報を取得
        conn = db.get_db_connection()
        memo = conn.execute("SELECT * FROM memos WHERE id = ?", (memo_id,)).fetchone()
        conn.close()
        
        if not memo:
            return
            
        text, ok = QInputDialog.getMultiLineText(self, "メモ編集", "内容を編集してください:", memo["body"])
        if ok and text.strip():
            # テキストの長さに合わせた自動サイズ計算
            from src.gui_overlay import calculate_auto_size
            w, h = calculate_auto_size(text.strip())
            
            db.update_memo(memo_id, body=text.strip(), width=w, height=h)
            self.load_data()
            self.data_changed.emit()

    def show_context_menu(self, pos):
        item = self.list_widget.itemAt(pos)
        if not item:
            return
        memo_id = item.data(Qt.UserRole)
        
        # dbから最新のメモ情報を取得
        conn = db.get_db_connection()
        memo = conn.execute("SELECT status FROM memos WHERE id = ?", (memo_id,)).fetchone()
        conn.close()
        
        if not memo:
            return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #2D2D30;
                color: #F1F1F1;
                border: 1px solid #454545;
                padding: 4px;
            }
            QMenu::item {
                padding: 4px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #007ACC;
            }
        """)

        edit_act = menu.addAction("編集...")
        edit_act.triggered.connect(lambda: self.edit_memo(item))
        menu.addSeparator()

        # ステータス変更のアクション
        status = memo["status"]
        
        if status != "active":
            show_act = menu.addAction("🟢 表示中（アクティブ）にする")
            show_act.triggered.connect(lambda: self.update_memo_status(memo_id, "active"))
            
        if status != "hidden":
            hide_act = menu.addAction("👁️ 一時非表示にする")
            hide_act.triggered.connect(lambda: self.update_memo_status(memo_id, "hidden"))
            
        snooze_act = menu.addAction("💤 明日に送る（午前9時に再表示）")
        snooze_act.triggered.connect(lambda: self.snooze_to_tomorrow(memo_id))

        if status != "completed":
            complete_act = menu.addAction("⚪ 完了にする")
            complete_act.triggered.connect(lambda: self.update_memo_status(memo_id, "completed"))
        else:
            reactivate_act = menu.addAction("🟢 未完了に戻す")
            reactivate_act.triggered.connect(lambda: self.update_memo_status(memo_id, "active"))

        if status != "archived":
            archive_act = menu.addAction("📦 アーカイブする")
            archive_act.triggered.connect(lambda: self.update_memo_status(memo_id, "archived"))

        menu.addSeparator()
        delete_act = menu.addAction("❌ 削除")
        delete_act.triggered.connect(self.delete_memo)

        menu.exec(self.list_widget.mapToGlobal(pos))

    def update_memo_status(self, memo_id, new_status):
        if new_status == "active":
            # アクティブにする場合は、スヌーズ等も解除して即座に表示されるようにする
            db.update_memo(memo_id, status="active", reminder_status="notified")
        else:
            db.update_memo(memo_id, status=new_status)
        self.load_data()
        self.data_changed.emit()

    def snooze_to_tomorrow(self, memo_id):
        from datetime import datetime, timedelta
        # 明日の午前9時
        tomorrow_9am = (datetime.now() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        db.update_memo(memo_id, status="active", reminder_at=tomorrow_9am.isoformat(), reminder_status="pending", reminded_at=None)
        self.load_data()
        self.data_changed.emit()

    def toggle_complete(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        memo_id = item.data(Qt.UserRole)
        
        conn = db.get_db_connection()
        memo = conn.execute("SELECT status FROM memos WHERE id = ?", (memo_id,)).fetchone()
        conn.close()
        
        if not memo:
            return
            
        new_status = "active" if memo["status"] == "completed" else "completed"
        self.update_memo_status(memo_id, new_status)

    def delete_memo(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        memo_id = item.data(Qt.UserRole)
        
        conn = db.get_db_connection()
        memo = conn.execute("SELECT status FROM memos WHERE id = ?", (memo_id,)).fetchone()
        conn.close()
        
        if not memo:
            return
            
        if memo["status"] == "deleted":
            # 既に削除済みの場合は完全にDBから削除
            reply = QMessageBox.question(
                self, "完全削除", "このメモをデータベースから完全に消去しますか？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                conn = db.get_db_connection()
                conn.execute("DELETE FROM memos WHERE id = ?", (memo_id,))
                conn.commit()
                conn.close()
        else:
            # 論理削除
            db.update_memo(memo_id, status="deleted")
            
        self.load_data()
        self.data_changed.emit()


class SettingsTab(QWidget):
    """設定タブ。アプリ全体の動作設定。"""
    config_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        form_layout = QFormLayout()
        form_layout.setSpacing(12)

        # 1. 表示モード
        self.mode_combo = QComboBox(self)
        self.mode_combo.addItems(["ハイブリッドモード", "壁紙モード", "オーバーレイモード"])
        self.mode_combo.currentIndexChanged.connect(self.save_settings)
        form_layout.addRow("表示モード:", self.mode_combo)

        # 新規付箋の配置ルール
        self.layout_combo = QComboBox(self)
        self.layout_combo.addItems([
            "斜めにずらす（デフォルト）",
            "縦に並べる",
            "横に並べる",
            "右端から並べる",
            "左端から並べる"
        ])
        self.layout_combo.currentIndexChanged.connect(self.save_settings)
        form_layout.addRow("新規付箋の配置ルール:", self.layout_combo)

        # 2. グローバルホットキー
        self.hotkey_edit = HotkeyLineEdit(self)
        self.hotkey_edit.editingFinished.connect(self.save_settings)
        form_layout.addRow("クイック入力ホットキー:", self.hotkey_edit)

        # 3. デフォルト色
        color_layout = QHBoxLayout()
        self.color_preview = QWidget(self)
        self.color_preview.setFixedSize(24, 24)
        self.color_preview.setStyleSheet("border: 1px solid #555; border-radius: 4px;")
        color_layout.addWidget(self.color_preview)
        
        self.color_btn = QPushButton("色を選択...", self)
        self.color_btn.clicked.connect(self.pick_default_color)
        color_layout.addWidget(self.color_btn)
        color_layout.addStretch()
        
        form_layout.addRow("付箋のデフォルトカラー:", color_layout)

        # 4. スタートアップ自動起動
        startup_layout = QHBoxLayout()
        self.startup_check = QCheckBox("Windows起動時に自動実行する", self)
        self.startup_check.stateChanged.connect(self.save_settings)
        startup_layout.addWidget(self.startup_check)
        
        self.startup_method_combo = QComboBox(self)
        self.startup_method_combo.addItems(["レジストリ登録（推奨）", "スタートアップフォルダ"])
        self.startup_method_combo.currentIndexChanged.connect(self.save_settings)
        startup_layout.addWidget(self.startup_method_combo)
        startup_layout.addStretch()
        
        form_layout.addRow("自動起動:", startup_layout)

        layout.addLayout(form_layout)
        layout.addSpacing(10)

        # アクションボタンエリア
        btn_layout = QHBoxLayout()
        
        self.restore_btn = QPushButton("元の壁紙を復元する", self)
        self.restore_btn.clicked.connect(self.restore_wallpaper)
        btn_layout.addWidget(self.restore_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # 5. データ管理エリア
        data_group = QGroupBox("データ管理", self)
        data_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #3F3F46;
                border-radius: 6px;
                margin-top: 15px;
                padding: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
                color: #007ACC;
            }
        """)
        data_layout = QHBoxLayout(data_group)
        data_layout.setSpacing(10)
        data_layout.setContentsMargins(10, 15, 10, 10)
        
        self.export_btn = QPushButton("データをエクスポート...", data_group)
        self.export_btn.clicked.connect(self.export_data)
        data_layout.addWidget(self.export_btn)
        
        self.import_btn = QPushButton("データをインポート...", data_group)
        self.import_btn.clicked.connect(self.import_data)
        data_layout.addWidget(self.import_btn)
        
        self.clear_btn = QPushButton("すべての付箋を初期化", data_group)
        self.clear_btn.setStyleSheet("background-color: #D83B01; color: white; border: 1px solid #E84C10;")
        self.clear_btn.clicked.connect(self.clear_notes)
        data_layout.addWidget(self.clear_btn)
        
        layout.addWidget(data_group)

        layout.addStretch()

        self.load_settings()

    def load_settings(self):
        # 表示モード
        mode = db.get_setting("display_mode", "hybrid")
        mode_idx = 0 if mode == "hybrid" else 1 if mode == "wallpaper" else 2
        self.mode_combo.setCurrentIndex(mode_idx)

        # 配置ルール
        layout_dir = db.get_setting("layout_direction", "diagonal")
        dir_map = {"diagonal": 0, "vertical": 1, "horizontal": 2, "from_right": 3, "from_left": 4}
        self.layout_combo.setCurrentIndex(dir_map.get(layout_dir, 0))

        # ホットキー
        self.hotkey_edit.setText(db.get_setting("hotkey", "Ctrl+Alt+N"))

        # デフォルトカラー
        color_hex = db.get_setting("default_note_color", "#FFFFC8")
        self.color_preview.setStyleSheet(f"background-color: {color_hex}; border: 1px solid #555; border-radius: 4px;")

        # スタートアップ
        startup = db.get_setting("startup_enabled", False)
        self.startup_check.setChecked(startup)
        
        # スタートアップの登録方法
        method = db.get_setting("startup_method", "registry")
        self.startup_method_combo.setCurrentIndex(0 if method == "registry" else 1)
        self.startup_method_combo.setEnabled(startup)

    def save_settings(self):
        # 表示モードの保存
        mode_map = {0: "hybrid", 1: "wallpaper", 2: "overlay"}
        db.set_setting("display_mode", mode_map.get(self.mode_combo.currentIndex(), "hybrid"))

        # 配置ルールの保存
        dir_map_rev = {0: "diagonal", 1: "vertical", 2: "horizontal", 3: "from_right", 4: "from_left"}
        db.set_setting("layout_direction", dir_map_rev.get(self.layout_combo.currentIndex(), "diagonal"))

        # ホットキーの保存
        hotkey = self.hotkey_edit.text().strip()
        old_hotkey = db.get_setting("hotkey", "Ctrl+Alt+N")
        if not hotkey:
            hotkey = "Ctrl+Alt+N"
            self.hotkey_edit.setText(hotkey)

        if hotkey != old_hotkey:
            if test_hotkey_availability(hotkey):
                db.set_setting("hotkey", hotkey)
            else:
                QMessageBox.warning(
                    self,
                    "ホットキー競合警告",
                    f"ホットキー '{hotkey}' は他のアプリと競合しているか、Windowsにより予約されているため使用できません。\n別のキーの組み合わせを試してください。",
                    QMessageBox.Ok
                )
                self.hotkey_edit.setText(old_hotkey)
                hotkey = old_hotkey

        # スタートアップ設定の保存 ＆ レジストリ/フォルダ反映
        startup_enabled = self.startup_check.isChecked()
        self.startup_method_combo.setEnabled(startup_enabled)
        
        method_map = {0: "registry", 1: "folder"}
        method = method_map.get(self.startup_method_combo.currentIndex(), "registry")
        
        db.set_setting("startup_enabled", startup_enabled)
        db.set_setting("startup_method", method)
        
        # 一度両方の設定をクリーンアップ
        set_startup_registry(False)
        set_startup_shortcut(False)
        
        if startup_enabled:
            if method == "registry":
                set_startup_registry(True)
            else:
                set_startup_shortcut(True)

        self.config_changed.emit()

    def pick_default_color(self):
        current_hex = db.get_setting("default_note_color", "#FFFFC8")
        color = QColorDialog.getColor(QColor(current_hex), self, "デフォルト背景色を選択")
        if color.isValid():
            db.set_setting("default_note_color", color.name())
            self.color_preview.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #555; border-radius: 4px;")
            self.config_changed.emit()

    def restore_wallpaper(self):
        reply = QMessageBox.question(
            self, "壁紙復元", "バックアップされたオリジナルの壁紙に戻しますか？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            wp.restore_original_wallpaper()
            QMessageBox.information(self, "完了", "オリジナルの壁紙を復元しました。")

    def export_data(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "付箋・設定データをエクスポート", "wallpaper_sticky_notes.json", "JSON Files (*.json)"
        )
        if file_path:
            try:
                db.export_data(file_path)
                QMessageBox.information(self, "完了", f"データをエクスポートしました:\n{os.path.basename(file_path)}")
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"エクスポートに失敗しました:\n{e}")

    def import_data(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "付箋・設定データをインポート", "", "JSON Files (*.json)"
        )
        if file_path:
            # 取り込み方法の確認ダイアログ
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("インポート方法の選択")
            msg_box.setText("データのインポート方法を選択してください。")
            msg_box.setInformativeText("「追加」: 現在ある付箋を残したまま新しくインポートします。\n「上書き」: 現在ある付箋をすべて消去したあとにインポートします。")
            
            append_btn = msg_box.addButton("追加してインポート", QMessageBox.YesRole)
            overwrite_btn = msg_box.addButton("上書きしてインポート", QMessageBox.NoRole)
            cancel_btn = msg_box.addButton("キャンセル", QMessageBox.RejectRole)
            
            msg_box.exec()
            
            if msg_box.clickedButton() == cancel_btn:
                return
                
            mode = "overwrite" if msg_box.clickedButton() == overwrite_btn else "append"
            
            try:
                db.import_data(file_path, mode=mode)
                self.load_settings() # 設定の再読込
                self.config_changed.emit() # 壁紙の再生成シグナルをトリガー
                QMessageBox.information(self, "完了", "データのインポートが完了しました。")
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"インポートに失敗しました:\n{e}")

    def clear_notes(self):
        reply = QMessageBox.question(
            self, "付箋の初期化", "現在登録されているすべての付箋を消去（初期化）しますか？\nこの操作は元に戻せません。",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                db.clear_all_memos(physical=True) # 完全にクリア
                self.config_changed.emit() # 壁紙再生成
                QMessageBox.information(self, "完了", "すべての付箋を初期化しました。")
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"初期化に失敗しました:\n{e}")


class ManageWindow(QWidget):
    """管理画面のメインウィンドウ。タブで管理画面と設定画面を切り替え。"""
    wallpaper_refresh_requested = Signal()
    overlay_toggle_requested = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("壁紙付箋アプリ - 管理パネル")
        self.resize(600, 450)
        self.setStyleSheet("""
            QWidget {
                background-color: #1E1E1E;
                color: #D4D4D4;
                font-family: "Segoe UI", "Meiryo";
            }
            QTabWidget::pane {
                border: 1px solid #2D2D30;
                background-color: #1E1E1E;
            }
            QTabBar::tab {
                background-color: #2D2D30;
                padding: 8px 16px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #1E1E1E;
                border-bottom: 2px solid #007ACC;
            }
            QPushButton {
                background-color: #2D2D30;
                color: #D4D4D4;
                border: 1px solid #3F3F46;
                padding: 6px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #3F3F46;
            }
            QPushButton:pressed {
                background-color: #007ACC;
                color: white;
            }
            QListWidget {
                background-color: #252526;
                border: 1px solid #2D2D30;
                border-radius: 4px;
                padding: 5px;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #2D2D30;
            }
            QListWidget::item:selected {
                background-color: #0975C4;
                color: white;
            }
        """)
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)

        # タブコントロール
        self.tabs = QTabWidget(self)
        
        self.manage_tab = ManageTab(self)
        self.manage_tab.data_changed.connect(self.handle_data_change)
        self.tabs.addTab(self.manage_tab, "付箋一覧")
        
        self.settings_tab = SettingsTab(self)
        self.settings_tab.config_changed.connect(self.handle_data_change)
        self.tabs.addTab(self.settings_tab, "アプリ設定")
        
        main_layout.addWidget(self.tabs)

        # 最下部クイックアクション
        control_layout = QHBoxLayout()
        
        # オーバーレイ編集切り替えボタン
        self.edit_mode_btn = QPushButton("オーバーレイ編集開始", self)
        self.edit_mode_btn.setCheckable(True)
        self.edit_mode_btn.clicked.connect(self.toggle_edit_mode)
        control_layout.addWidget(self.edit_mode_btn)

        # 壁紙即座に再生成ボタン
        self.apply_wp_btn = QPushButton("壁紙に即座に反映", self)
        self.apply_wp_btn.clicked.connect(self.wallpaper_refresh_requested.emit)
        control_layout.addWidget(self.apply_wp_btn)
        
        control_layout.addStretch()
        
        self.close_btn = QPushButton("閉じる", self)
        self.close_btn.clicked.connect(self.close)
        control_layout.addWidget(self.close_btn)

        main_layout.addLayout(control_layout)

    def handle_data_change(self):
        # データの変更があったら、壁紙を再生成して適用するシグナルを送る
        self.wallpaper_refresh_requested.emit()

    def toggle_edit_mode(self, checked):
        if checked:
            self.edit_mode_btn.setText("オーバーレイ編集終了")
            self.edit_mode_btn.setStyleSheet("background-color: #007ACC; color: white;")
            self.overlay_toggle_requested.emit(True)
        else:
            self.edit_mode_btn.setText("オーバーレイ編集開始")
            self.edit_mode_btn.setStyleSheet("")
            self.overlay_toggle_requested.emit(False)
            # 編集が終わったら、配置を壁紙に反映
            self.wallpaper_refresh_requested.emit()

    def show_event(self, event):
        """表示されるたびにデータを再ロード。"""
        super().showEvent(event)
        self.manage_tab.load_data()
        self.settings_tab.load_settings()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    db.init_db()
    
    win = ManageWindow()
    win.show()
    
    sys.exit(app.exec())
