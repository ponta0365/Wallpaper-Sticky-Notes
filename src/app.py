import sys
import os
from PIL import Image, ImageDraw
from PySide6.QtCore import Qt, QTimer, QSize, QLockFile
from PySide6.QtGui import QIcon, QAction
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox
import src.db as db
import src.wallpaper as wp
from src.gui_input import QuickInputWindow
from src.gui_overlay import OverlayWindow
from src.gui_manage import ManageWindow
from src.hotkey import GlobalHotkeyThread

def create_default_icon_file():
    """アプリで利用するデフォルトのアイコン画像を動的に作成します。"""
    assets_dir = os.path.join(db.DB_DIR, "assets")
    os.makedirs(assets_dir, exist_ok=True)
    icon_path = os.path.join(assets_dir, "app_icon.png")
    
    if os.path.exists(icon_path):
        return icon_path
        
    # Pillowで付箋モチーフのアイコン(32x32)を生成
    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # 黄色の付箋
    draw.rounded_rectangle([2, 2, 30, 30], radius=4, fill=(255, 255, 200, 255), outline=(220, 220, 150, 255), width=1)
    # 少し暗い上部バー
    draw.rounded_rectangle([3, 3, 29, 9], radius=3, fill=(225, 225, 170, 255))
    draw.rectangle([3, 6, 29, 9], fill=(225, 225, 170, 255))
    
    # 罫線っぽいダミー線
    draw.line([6, 15, 26, 15], fill=(180, 180, 180, 255), width=1)
    draw.line([6, 20, 26, 20], fill=(180, 180, 180, 255), width=1)
    
    img.save(icon_path, "PNG")
    return icon_path

class StickyNotesApp:
    """アプリケーション全体を統括するメインコントローラクラス。"""
    def __init__(self, qt_app):
        self.qt_app = qt_app
        
        # 自動終了を確実に防ぐための画面外透明ダミーウィンドウ
        from PySide6.QtWidgets import QWidget
        self.dummy_window = QWidget()
        self.dummy_window.setGeometry(-1000, -1000, 1, 1)
        self.dummy_window.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        self.dummy_window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.dummy_window.show()
        
        # 1. データベースとリソースの初期化
        db.init_db()
        self.icon_path = create_default_icon_file()
        
        # UIウィンドウの作成
        self.quick_input = None
        self.manage_window = None
        self.overlays = []
        self.overlay_editing_active = False
        
        # 2. システムトレイの常駐設定
        self.setup_tray_icon()
        
        # 3. グローバルホットキーの開始
        self.setup_hotkey()
        
        # 4. 常駐リマインダー監視タイマー
        self.setup_reminder_timer()
        
        # 5. オーバーレイの初期ロード
        self.setup_overlays()
        
        # 初回起動時の壁紙反映
        self.refresh_wallpaper()

    # --- トレイアイコン設定 ---

    def setup_tray_icon(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            print("System tray is not available. Showing management window directly.")
            QTimer.singleShot(1000, self.show_management)
            return
            
        self.tray_icon = QSystemTrayIcon(self.qt_app)
        self.tray_icon.setIcon(QIcon(self.icon_path))
        self.tray_icon.setToolTip("壁紙付箋アプリ")
        
        # コンテキストメニュー
        tray_menu = QMenu()
        tray_menu.setStyleSheet("""
            QMenu {
                background-color: #2D2D30;
                color: #F1F1F1;
                border: 1px solid #454545;
            }
            QMenu::item {
                padding: 6px 20px;
            }
            QMenu::item:selected {
                background-color: #007ACC;
            }
        """)
        
        self.quick_action = QAction("クイック入力 (Ctrl+Alt+N)", self.tray_icon)
        self.quick_action.triggered.connect(self.show_quick_input)
        tray_menu.addAction(self.quick_action)
        
        # トレイメニューから直接「編集モード」を切り替えられるアクション
        self.edit_mode_action = QAction("付箋を移動・編集する (編集モード)", self.tray_icon)
        self.edit_mode_action.setCheckable(True)
        self.edit_mode_action.triggered.connect(self.toggle_overlay_editing)
        tray_menu.addAction(self.edit_mode_action)
        
        manage_action = QAction("付箋管理画面...", self.tray_icon)
        manage_action.triggered.connect(self.show_management)
        tray_menu.addAction(manage_action)
        
        tray_menu.addSeparator()
        
        refresh_action = QAction("壁紙に即座に反映", self.tray_icon)
        refresh_action.triggered.connect(self.refresh_wallpaper)
        tray_menu.addAction(refresh_action)
        
        tray_menu.addSeparator()
        
        exit_action = QAction("終了", self.tray_icon)
        exit_action.triggered.connect(self.quit_app)
        tray_menu.addAction(exit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        
        # ダブルクリックで管理画面を開く
        self.tray_icon.activated.connect(self.handle_tray_activated)
        
        self.tray_icon.show()

    def handle_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger: # シングルクリック
            pass
        elif reason == QSystemTrayIcon.DoubleClick: # ダブルクリック
            self.show_management()

    # --- グローバルホットキー設定 ---

    def setup_hotkey(self):
        if hasattr(self, "hotkey_thread") and self.hotkey_thread is not None:
            try:
                self.hotkey_thread.stop()
            except Exception as e:
                print(f"Error stopping hotkey thread: {e}")

        self.hotkey_thread = GlobalHotkeyThread()
        self.hotkey_thread.activated.connect(self.show_quick_input)
        self.hotkey_thread.registration_status.connect(self.handle_hotkey_registration_status)
        self.hotkey_thread.start()

    def handle_hotkey_registration_status(self, original_key, registered_key):
        if not registered_key:
            if hasattr(self, "tray_icon"):
                self.tray_icon.showMessage(
                    "ホットキー登録失敗",
                    f"ホットキー '{original_key}' の登録に失敗しました。他のキーを試してください。",
                    QSystemTrayIcon.Warning,
                    5000
                )
            if hasattr(self, "quick_action"):
                self.quick_action.setText("クイック入力 (未登録)")
        elif registered_key != original_key:
            if hasattr(self, "tray_icon"):
                self.tray_icon.showMessage(
                    "ホットキー競合による代替登録",
                    f"'{original_key}' が競合したため、代替として '{registered_key}' で登録しました。",
                    QSystemTrayIcon.Information,
                    5000
                )
            if hasattr(self, "quick_action"):
                self.quick_action.setText(f"クイック入力 ({registered_key})")
        else:
            if hasattr(self, "quick_action"):
                self.quick_action.setText(f"クイック入力 ({registered_key})")

    # --- リマインダー設定 ---

    def setup_reminder_timer(self):
        self.reminder_timer = QTimer(self.qt_app)
        # 30秒ごとにDBを監視
        self.reminder_timer.timeout.connect(self.check_reminders)
        self.reminder_timer.start(30000)

    def check_reminders(self):
        """期限が来たリマインダーをクエリし、通知を出します。"""
        import sqlite3
        from datetime import datetime
        
        conn = db.get_db_connection()
        cursor = conn.cursor()
        now_str = datetime.now().isoformat()
        
        # status が active で、reminder_at が現在時刻以前のものをクエリ
        # ※未通知のもの (sqliteにはreminder_atのみ記録されているため、
        # 通知後に reminder_at をクリアするか、statusを更新して通知済フラグにするなどが必要)
        # ここでは、通知がトリガーされたら reminder_at を NULL に更新するか、
        # reminder_at は残しつつ、通知済フラグ（SQLite構造的に status または別フィールド）で管理したい。
        # メモデータ構造の z_index や pinned などを活かしつつ、シンプルにするため、
        # 「一度通知したら、そのメモの reminder_at を NULL に更新する（解除する）」のが最も確実。
        cursor.execute("""
            SELECT * FROM memos 
            WHERE status = 'active' 
              AND reminder_at IS NOT NULL 
              AND datetime(reminder_at) <= datetime(?)
        """, (now_str,))
        
        triggered_memos = cursor.fetchall()
        
        if triggered_memos:
            for row in triggered_memos:
                memo = dict(row)
                
                # 通知を表示
                self.tray_icon.showMessage(
                    "リマインダー通知",
                    memo["body"][:60] + "..." if len(memo["body"]) > 60 else memo["body"],
                    QSystemTrayIcon.Information,
                    10000 # 10秒表示
                )
                
                # 通知後はリマインダーを解除 (DB更新)
                cursor.execute("UPDATE memos SET reminder_at = NULL WHERE id = ?", (memo["id"],))
                
            conn.commit()
            
            # 通知によりDBが更新されたため、壁紙を再生成してリマインダーマークを消す
            self.refresh_wallpaper()
            
            # もし管理画面が開いていれば更新
            if self.manage_window and self.manage_window.isVisible():
                self.manage_window.manage_tab.load_data()
                
        conn.close()

    # --- オーバーレイ管理 ---

    def setup_overlays(self):
        """マルチモニターごとに透過オーバーレイウィンドウを作成します。"""
        # 既存オーバーレイをクリア
        for ov in self.overlays:
            ov.close()
            ov.deleteLater()
        self.overlays.clear()
        
        # モニター情報を取得して構築
        screens = self.qt_app.screens()
        for idx, screen in enumerate(screens):
            ov = OverlayWindow(idx, screen.geometry())
            ov.data_changed.connect(self.refresh_wallpaper)
            ov.edit_mode_requested.connect(self.toggle_overlay_editing)
            self.overlays.append(ov)
            
        self.apply_overlay_visibility()

    def apply_overlay_visibility(self):
        """設定モードに応じてオーバーレイ表示・非表示を制御。"""
        display_mode = db.get_setting("display_mode", "hybrid")
        
        for ov in self.overlays:
            # データベースから付箋をロード
            ov.load_memos()
            
            if display_mode == "overlay":
                # オーバーレイモードの場合、常に閲覧モード（クリック透過）で表示
                ov.set_edit_mode(False)
                ov.show()
                # 閲覧モードでも付箋を表示する
                for note in ov.notes:
                    note.setVisible(True)
            elif display_mode == "hybrid":
                # ハイブリッドモードの場合、通常時はオーバーレイを隠す（壁紙として描画されているため）
                # 編集に入ったときのみ表示（後述の toggle_overlay_editing で制御）
                if ov.is_edit_mode:
                    ov.show()
                else:
                    ov.hide()
            else: # wallpaper モード
                # 壁紙モードはオーバーレイ不使用
                ov.hide()

    def toggle_overlay_editing(self, enabled):
        """編集モード（管理画面やトレイメニューのスイッチ）と連携し、オーバーレイを操作可能にします。"""
        self.overlay_editing_active = enabled
        display_mode = db.get_setting("display_mode", "hybrid")
        
        # トレイメニューのチェック状態を同期
        if hasattr(self, "edit_mode_action"):
            self.edit_mode_action.setChecked(enabled)
            
        # 管理画面のボタン状態を同期
        if self.manage_window and self.manage_window.isVisible():
            self.manage_window.edit_mode_btn.setChecked(enabled)
            if enabled:
                self.manage_window.edit_mode_btn.setText("オーバーレイ編集終了")
                self.manage_window.edit_mode_btn.setStyleSheet("background-color: #007ACC; color: white;")
            else:
                self.manage_window.edit_mode_btn.setText("オーバーレイ編集開始")
                self.manage_window.edit_mode_btn.setStyleSheet("")
        
        # 編集モードに入る際に壁紙を一時的に復元（焼き込みを隠す）
        # 編集終了の際（enabled=False）に壁紙再描画が走るため、ここで同期をとります
        self.refresh_wallpaper()
        
        for ov in self.overlays:
            if enabled:
                # 編集モードに入る：表示させ、クリック可能にする
                ov.set_edit_mode(True)
                ov.show()
                # 付箋を表示
                for note in ov.notes:
                    note.setVisible(True)
            else:
                # 編集モード終了
                ov.set_edit_mode(False)
                
                # モードごとに最終表示を調整
                if display_mode == "hybrid":
                    # ハイブリッドモードなら編集終了後に非表示化（壁紙へ移行）
                    ov.hide()
                elif display_mode == "overlay":
                    # オーバーレイモードなら表示し続ける（クリック透過）
                    ov.show()
                    for note in ov.notes:
                        note.setVisible(True)
                else:
                    ov.hide()

    # --- アクション ---

    def show_quick_input(self):
        """クイック入力小窓を表示します。"""
        # 既存ウインドウがなければ作成
        if not self.quick_input:
            self.quick_input = QuickInputWindow()
            self.quick_input.submitted.connect(self.handle_quick_input_submit)
        
        self.quick_input.show()
        self.quick_input.activateWindow()

    def handle_quick_input_submit(self, text, reminder_at=None):
        default_color = db.get_setting("default_note_color", "#FFFFC8")
        
        # テキストの長さに合わせた自動サイズ計算
        from src.gui_overlay import calculate_auto_size
        w, h = calculate_auto_size(text)
        
        # データベースに保存 (モニター0＝メインモニター)
        db.add_memo(text, color=default_color, monitor_id="0", width=w, height=h, reminder_at=reminder_at)
        
        # 壁紙再生成
        self.refresh_wallpaper()
        
        # 管理画面があれば更新
        if self.manage_window and self.manage_window.isVisible():
            self.manage_window.manage_tab.load_data()

    def show_management(self):
        """管理画面を表示します。"""
        if not self.manage_window:
            self.manage_window = ManageWindow()
            self.manage_window.wallpaper_refresh_requested.connect(self.refresh_wallpaper)
            self.manage_window.overlay_toggle_requested.connect(self.toggle_overlay_editing)
            self.manage_window.settings_tab.config_changed.connect(self.handle_config_changed)

    def handle_config_changed(self):
        """設定が変更された際に呼び出されます。ホットキーの再起動などを行います。"""
        self.setup_hotkey()
            
        # 管理画面表示時に現在の編集モード状態を反映
        self.manage_window.edit_mode_btn.setChecked(self.overlay_editing_active)
        if self.overlay_editing_active:
            self.manage_window.edit_mode_btn.setText("オーバーレイ編集終了")
            self.manage_window.edit_mode_btn.setStyleSheet("background-color: #007ACC; color: white;")
        else:
            self.manage_window.edit_mode_btn.setText("オーバーレイ編集開始")
            self.manage_window.edit_mode_btn.setStyleSheet("")
            
        self.manage_window.show()
        self.manage_window.activateWindow()

    def refresh_wallpaper(self):
        """壁紙の再合成および再生成、オーバーレイ上の付箋の再ロードを行います。"""
        display_mode = db.get_setting("display_mode", "hybrid")
        
        # 1. 壁紙への反映が必要なモードの場合は壁紙をレンダリングして適用
        if display_mode in ("wallpaper", "hybrid"):
            if display_mode == "hybrid" and self.overlay_editing_active:
                # ハイブリッドモードでの編集中は、壁紙側の焼き込み付箋を一時的に消して
                # 操作可能になった実ウィジェットだけを目の前に見せる
                wp.restore_original_wallpaper()
            else:
                # 通常時はPillowを用いて壁紙に焼き込み
                wp.render_and_apply_wallpaper()
        else:
            # オーバーレイモード単体の場合は、壁紙には焼き込まないためオリジナルを復元
            wp.restore_original_wallpaper()

        # 2. オーバーレイ上の付箋ウィジェットを再ロード
        for ov in self.overlays:
            ov.load_memos()

    def quit_app(self):
        """アプリケーションを完全に終了します。壁紙を元に戻すかは確認。"""
        reply = QMessageBox.question(
            None, "アプリの終了", "壁紙をオリジナルの状態に復元して終了しますか？",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
        )
        
        if reply == QMessageBox.Cancel:
            return
            
        # ホットキースレッドの停止
        self.hotkey_thread.stop()
        
        # タイマーの停止
        self.reminder_timer.stop()
        
        if reply == QMessageBox.Yes:
            # 元の壁紙を復元
            wp.restore_original_wallpaper()
            
        self.tray_icon.hide()
        self.qt_app.quit()

def main():
    # WindowsでDPIスケーリングによるぼやけを防ぐ設定
    # Qt6ではデフォルトでHigh DPIスケーリングが有効ですが、Windowsシステムに対して明示的に宣言します。
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2) # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    app = QApplication(sys.argv)
    
    # 多重起動の防止
    lock_path = os.path.join(db.DB_DIR, "app.lock")
    global lock_file
    lock_file = QLockFile(lock_path)
    if not lock_file.tryLock(100):
        QMessageBox.warning(
            None,
            "多重起動の防止",
            "壁紙付箋アプリは既に起動しています。\n画面右下のシステムトレイ（▲マークの中など）にあるアイコンを確認してください。",
            QMessageBox.Ok
        )
        sys.exit(0)
    
    # 閉じるボタン等でアプリが終了しないようにする (トレイ常駐のため)
    app.setQuitOnLastWindowClosed(False)
    
    controller = StickyNotesApp(app)
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
