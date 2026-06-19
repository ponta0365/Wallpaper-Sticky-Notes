import sys
from PySide6.QtCore import Qt, Signal, QPoint, QRect, QSize, QDateTime, QTime, QEvent
from PySide6.QtGui import QColor, QFont, QPalette, QBrush, QPainter, QCursor, QAction, QTextDocument, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QMenu, QColorDialog, 
    QGraphicsDropShadowEffect, QPlainTextEdit, QDialog, 
    QVBoxLayout, QHBoxLayout, QPushButton, QDateTimeEdit
)
import src.db as db
import ctypes
from ctypes import wintypes
from src.wallpaper import parse_color_string

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020

def set_window_click_through(hwnd, enabled):
    """Win32 APIを使用して、直接ウィンドウのクリック透過スタイルを設定します。"""
    try:
        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if enabled:
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT)
        else:
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style & ~WS_EX_TRANSPARENT)
        # 属性変更を反映 (SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)
    except Exception as e:
        print(f"Failed to set Win32 click through: {e}")

def calculate_auto_size(text, font_family="Meiryo", font_size=12):
    """テキストの長さに応じて、付箋の最適な幅と高さを計算します。"""
    doc = QTextDocument()
    doc.setDocumentMargin(0) # デフォルトマージンを排除
    font = QFont(font_family, font_size)
    doc.setDefaultFont(font)
    doc.setPlainText(text)
    
    # 物理配置に基づく定数
    padding_x = 16     # 左右余白 (8px * 2)
    padding_y = 12     # 上下余白 (6px * 2)
    header_h = 12      # ヘッダー高さ
    footer_h = 22      # フッター高さ
    
    max_width = 280
    min_width = 120    # 短いテキスト用
    
    ideal_w = doc.idealWidth() + padding_x
    width = max(min_width, min(max_width, int(ideal_w)))
    
    # 折り返し時の高さを算出
    doc.setTextWidth(width - padding_x)
    text_height = int(doc.size().height())
    
    height = text_height + padding_y + header_h + footer_h
    return width, height

class ReminderDialog(QDialog):
    """リマインダー（通知予定日時）を設定するダイアログ。"""
    def __init__(self, current_dt_str=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("リマインダー設定")
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.init_ui(current_dt_str)
        self.setStyleSheet("""
            QDialog {
                background-color: #2D2D30;
                color: #F1F1F1;
            }
            QLabel {
                color: #F1F1F1;
                font-family: "Segoe UI", "Meiryo";
                font-size: 12px;
            }
            QDateTimeEdit {
                background-color: #3F3F46;
                color: #F1F1F1;
                border: 1px solid #555555;
                padding: 4px;
                border-radius: 4px;
            }
            QPushButton {
                background-color: #007ACC;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #1C97EA;
            }
            QPushButton#cancelBtn {
                background-color: #555555;
            }
            QPushButton#cancelBtn:hover {
                background-color: #666666;
            }
            QPushButton#deleteBtn {
                background-color: #D83B01;
            }
            QPushButton#deleteBtn:hover {
                background-color: #E84C10;
            }
        """)

    def init_ui(self, current_dt_str):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)

        layout.addWidget(QLabel("通知する日時を設定してください："))

        # 日時入力エディタ
        self.dt_edit = QDateTimeEdit(self)
        self.dt_edit.setCalendarPopup(True)
        self.dt_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        
        if current_dt_str:
            try:
                self.dt_edit.setDateTime(QDateTime.fromString(current_dt_str, Qt.ISODate))
            except Exception:
                self.dt_edit.setDateTime(QDateTime.currentDateTime().addSecs(3600)) # 1時間後
        else:
            # デフォルトは今日の日付と現在の時刻（秒以下は0にリセット）
            now = QDateTime.currentDateTime()
            time = now.time()
            default_dt = QDateTime(now.date(), QTime(time.hour(), time.minute(), 0))
            self.dt_edit.setDateTime(default_dt)
            
        layout.addWidget(self.dt_edit)

        # ボタンエリア
        btn_layout = QHBoxLayout()
        
        # 削除ボタン (設定済みの場合のみ表示)
        self.delete_btn = QPushButton("解除", self)
        self.delete_btn.setObjectName("deleteBtn")
        self.delete_btn.clicked.connect(self.handle_delete)
        if not current_dt_str:
            self.delete_btn.setEnabled(False)
            self.delete_btn.setStyleSheet("background-color: #444444; color: #888888;")
        btn_layout.addWidget(self.delete_btn)
        
        btn_layout.addStretch()

        self.cancel_btn = QPushButton("キャンセル", self)
        self.cancel_btn.setObjectName("cancelBtn")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        self.ok_btn = QPushButton("設定", self)
        self.ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.ok_btn)

        layout.addLayout(btn_layout)

    def handle_delete(self):
        self.done(2)  # 特別なコード2で返す (解除を示す)

    def get_datetime_str(self):
        return self.dt_edit.dateTime().toString(Qt.ISODate)


class StickyNoteWidget(QWidget):
    """個別付箋ウィジェット。ドラッグ移動、リサイズ、インプレース編集、コンテキストメニューに対応。"""
    data_changed = Signal()  # DBデータが変更されたことを親ウィンドウへ通知

    def __init__(self, memo_data, parent=None):
        super().__init__(parent)
        self.memo_data = memo_data
        self.drag_position = QPoint()
        self.in_resize = False
        self.is_editing = False
        
        self.init_ui()

    def init_ui(self):
        # スタイルシートによる背景色描画を有効にする (カスタムQWidgetで背景を描画するために必須)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        # テキストの長さに合わせてサイズを自動計算し強制適用
        font_sz = self.memo_data.get("font_size", 12)
        w, h = calculate_auto_size(self.memo_data["body"], font_size=font_sz)
        self.memo_data["width"] = w
        self.memo_data["height"] = h
        db.update_memo(self.memo_data["id"], width=w, height=h)

        # 初期座標とサイズ設定 (論理座標)
        self.setGeometry(
            self.memo_data["x"], 
            self.memo_data["y"], 
            w, 
            h
        )
        
        # 影効果
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(10)
        shadow.setOffset(2, 2)
        shadow.setColor(QColor(0, 0, 0, 80))
        self.setGraphicsEffect(shadow)

        # メインレイアウト
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # ヘッダーバー (ドラッグ移動のつまみとなる)
        self.header_bar = QWidget(self)
        self.header_bar.setFixedHeight(12)
        self.layout.addWidget(self.header_bar)

        # コンテンツ表示用ラベル
        self.text_label = QLabel(self)
        self.text_label.setWordWrap(True)
        self.text_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.text_label.setStyleSheet("padding: 6px 8px; color: #1E1E1E;")
        self.layout.addWidget(self.text_label)

        # インプレース編集用テキストエディタ (初期状態は非表示)
        self.editor = QPlainTextEdit(self)
        self.editor.setVisible(False)
        self.editor.installEventFilter(self)
        self.layout.addWidget(self.editor)

        # フッターコントロール（右下の時刻ボタン）
        self.footer_widget = QWidget(self)
        self.footer_widget.setFixedHeight(22)
        self.footer_layout = QHBoxLayout(self.footer_widget)
        self.footer_layout.setContentsMargins(5, 0, 5, 2)
        self.footer_layout.setSpacing(5)
        self.footer_layout.addStretch()
        
        self.reminder_btn = QPushButton("🕐", self.footer_widget)
        self.reminder_btn.clicked.connect(self.set_reminder)
        self.reminder_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 0, 0, 15);
                color: #202020;
                border: none;
                border-radius: 4px;
                padding: 1px 6px;
                font-family: "Segoe UI", "Meiryo";
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: rgba(0, 0, 0, 30);
            }
        """)
        self.footer_layout.addWidget(self.reminder_btn)
        self.layout.addWidget(self.footer_widget)

        # 外す（削除）ボタンの初期化
        self.remove_btn = QPushButton("外す", self)
        self.remove_btn.setVisible(False)
        self.remove_btn.clicked.connect(self.delete_note)
        self.remove_btn.setStyleSheet("""
            QPushButton {
                background-color: #D83B01;
                color: white;
                border: 1px solid #E84C10;
                border-radius: 4px;
                font-family: "Segoe UI", "Meiryo";
                font-size: 11px;
                font-weight: bold;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background-color: #E84C10;
            }
        """)

        # 更新
        self.update_style()
        self.update_content()

    def update_style(self):
        """付箋の背景色とヘッダーの色を設定します。"""
        bg_hex = self.memo_data["color"]
        r, g, b, a = parse_color_string(bg_hex)
        a_f = a / 255.0
        
        # 輝度を計算してテキスト色を自動反転 (明るい背景なら黒文字、暗い背景なら白文字)
        luminance = 0.299 * r + 0.587 * g + 0.114 * b
        if luminance < 140:
            text_color_hex = "#F1F1F1"
        else:
            text_color_hex = "#1E1E1E"
        
        # ヘッダーは背景色より少し暗くする
        hr, hg, hb = max(0, r - 30), max(0, g - 30), max(0, b - 30)
        
        # 文字サイズを取得
        font_sz = self.memo_data.get("font_size", 12)
        
        # QWidgetの背景色設定 (スタイルシート)
        self.setStyleSheet(f"""
            StickyNoteWidget {{
                background-color: rgba({r}, {g}, {b}, {a_f});
                border-radius: 8px;
            }}
            QLabel {{
                font-family: "Segoe UI", "Meiryo";
                font-size: {font_sz}px;
                color: {text_color_hex};
            }}
        """)
        
        self.text_label.setStyleSheet(f"padding: 6px 8px; color: {text_color_hex}; font-size: {font_sz}px;")
        
        # エディタの文字色も合わせる
        self.editor.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: transparent;
                border: none;
                color: {text_color_hex};
                font-family: "Segoe UI", "Meiryo";
                font-size: {font_sz}px;
                padding: 6px 8px;
            }}
        """)
        
        self.header_bar.setStyleSheet(f"""
            QWidget {{
                background-color: rgba({hr}, {hg}, {hb}, {a_f});
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }}
        """)

    def update_content(self):
        """テキストラベルとフッター（時刻ボタン）の更新。"""
        body = self.memo_data["body"]
        # reminder_status が 'pending' の場合のみ通知予定日時を表示
        reminder = self.memo_data.get("reminder_at") if self.memo_data.get("reminder_status") == "pending" else None
        
        self.text_label.setText(body)
        self.editor.setPlainText(body)
        
        # 輝度を計算してボタンの色を最適化
        bg_hex = self.memo_data["color"]
        r, g, b, _ = parse_color_string(bg_hex)
        luminance = 0.299 * r + 0.587 * g + 0.114 * b
        
        # 時刻ボタンの表示変更
        if reminder:
            try:
                time_str = QDateTime.fromString(reminder, Qt.ISODate).toString("HH:mm")
            except Exception:
                time_str = reminder
            self.reminder_btn.setText(f"🕐 {time_str}")
            if luminance < 140:
                self.reminder_btn.setStyleSheet("""
                    QPushButton {
                        background-color: rgba(255, 255, 255, 40);
                        color: #FFFFFF;
                        border: 1px solid rgba(255, 255, 255, 60);
                        border-radius: 4px;
                        padding: 1px 6px;
                        font-family: "Segoe UI", "Meiryo";
                        font-size: 11px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: rgba(255, 255, 255, 60);
                    }
                """)
            else:
                self.reminder_btn.setStyleSheet("""
                    QPushButton {
                        background-color: rgba(0, 122, 204, 30);
                        color: #007ACC;
                        border: 1px solid rgba(0, 122, 204, 50);
                        border-radius: 4px;
                        padding: 1px 6px;
                        font-family: "Segoe UI", "Meiryo";
                        font-size: 11px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: rgba(0, 122, 204, 50);
                    }
                """)
        else:
            self.reminder_btn.setText("🕐")
            if luminance < 140:
                self.reminder_btn.setStyleSheet("""
                    QPushButton {
                        background-color: rgba(255, 255, 255, 25);
                        color: #F1F1F1;
                        border: none;
                        border-radius: 4px;
                        padding: 1px 6px;
                        font-family: "Segoe UI", "Meiryo";
                        font-size: 11px;
                    }
                    QPushButton:hover {
                        background-color: rgba(255, 255, 255, 45);
                    }
                """)
            else:
                self.reminder_btn.setStyleSheet("""
                    QPushButton {
                        background-color: rgba(0, 0, 0, 15);
                        color: #404040;
                        border: none;
                        border-radius: 4px;
                        padding: 1px 6px;
                        font-family: "Segoe UI", "Meiryo";
                        font-size: 11px;
                    }
                    QPushButton:hover {
                        background-color: rgba(0, 0, 0, 30);
                    }
                """)

    # --- ドラッグ移動 ＆ リサイズ ---

    def mousePressEvent(self, event):
        # 閲覧モード中に付箋がクリックされたら編集モードへの移行を要求する
        if hasattr(self.parentWidget(), "is_edit_mode") and not self.parentWidget().is_edit_mode:
            if event.button() == Qt.LeftButton:
                self.parentWidget().request_edit_mode()
                event.accept()
                return

        # 「外す」ボタンが表示されている場合は、それ以外のクリックでボタンを隠す
        if self.remove_btn.isVisible():
            if not self.remove_btn.geometry().contains(event.pos()):
                self.remove_btn.setVisible(False)
                event.accept()
                return

        if event.button() == Qt.LeftButton:
            # 右下角付近をクリックした場合はリサイズモードへ
            # リサイズグリップサイズ: 15px
            rect = self.rect()
            if event.pos().x() >= rect.width() - 15 and event.pos().y() >= rect.height() - 15:
                self.in_resize = True
                # カーソル変更
                self.setCursor(Qt.SizeBDiagCursor)
            else:
                self.in_resize = False
                # ドラッグ開始位置を記録 (ローカル座標を保存)
                self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                self.setCursor(Qt.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            if self.in_resize:
                # リサイズ処理
                new_w = max(100, event.pos().x())
                new_h = max(80, event.pos().y())
                self.resize(new_w, new_h)
            else:
                # 移動処理 (親ウィンドウ内)
                new_top_left = event.globalPosition().toPoint() - self.drag_position
                
                # 親ウィンドウの境界内で移動制限 (はみ出し防止)
                parent_rect = self.parentWidget().rect()
                x = max(0, min(new_top_left.x(), parent_rect.width() - self.width()))
                y = max(0, min(new_top_left.y(), parent_rect.height() - self.height()))
                
                self.move(x, y)
            event.accept()
        else:
            # マウスカーソルが右下角にある時はリサイズカーソルに変える
            rect = self.rect()
            if event.pos().x() >= rect.width() - 15 and event.pos().y() >= rect.height() - 15:
                self.setCursor(Qt.SizeBDiagCursor)
            else:
                self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        self.setCursor(Qt.ArrowCursor)
        if event.button() == Qt.LeftButton:
            # 移動・サイズ変更後にDBへ位置情報を保存
            x, y = self.x(), self.y()
            w, h = self.width(), self.height()
            
            # 前の値と変わっていたら更新
            if (x != self.memo_data["x"] or y != self.memo_data["y"] or 
                w != self.memo_data["width"] or h != self.memo_data["height"]):
                
                self.memo_data["x"] = x
                self.memo_data["y"] = y
                self.memo_data["width"] = w
                self.memo_data["height"] = h
                
                db.update_memo(self.memo_data["id"], x=x, y=y, width=w, height=h)
                self.data_changed.emit()
                
                # 位置が変わったので親ウィンドウのマスクを更新
                if hasattr(self.parentWidget(), "update_mask"):
                    self.parentWidget().update_mask()
                
            self.in_resize = False
            event.accept()

    def enterEvent(self, event):
        # ホバー時にカーソルをチェック
        self.setMouseTracking(True)
        super().enterEvent(event)

    def mouseDoubleClickEvent(self, event):
        """ダブルクリックで『外す』ボタンを表示。すでに表示中ならインプレース編集を開始。"""
        if event.button() == Qt.LeftButton and not self.is_editing:
            if not self.remove_btn.isVisible():
                self.show_remove_button()
            else:
                self.remove_btn.setVisible(False)
                self.start_edit()
            event.accept()

    def show_remove_button(self):
        """「外す」ボタンを付箋の中央に表示します。"""
        btn_w = 60
        btn_h = 24
        btn_x = (self.width() - btn_w) // 2
        btn_y = (self.height() - btn_h) // 2
        self.remove_btn.setGeometry(btn_x, btn_y, btn_w, btn_h)
        self.remove_btn.setVisible(True)
        self.remove_btn.raise_()
        self.remove_btn.setFocus()

    # --- インプレース編集 ---

    def start_edit(self):
        self.is_editing = True
        self.text_label.setVisible(False)
        self.footer_widget.setVisible(False)  # 時刻ボタン非表示
        self.editor.setVisible(True)
        self.editor.setFocus()
        # テキストの最後にカーソルを合わせる
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.editor.setTextCursor(cursor)

    def finish_edit(self, save=True):
        if not self.is_editing:
            return
        
        self.is_editing = False
        self.editor.setVisible(False)
        self.text_label.setVisible(True)
        self.footer_widget.setVisible(True)  # 時刻ボタン再表示
        
        if save:
            new_body = self.editor.toPlainText().strip()
            if new_body and new_body != self.memo_data["body"]:
                self.memo_data["body"] = new_body
                
                # テキストの長さに合わせた自動サイズ計算と反映
                font_sz = self.memo_data.get("font_size", 12)
                w, h = calculate_auto_size(new_body, font_size=font_sz)
                self.memo_data["width"] = w
                self.memo_data["height"] = h
                self.resize(w, h)
                
                db.update_memo(self.memo_data["id"], body=new_body, width=w, height=h)
                self.update_content()
                self.data_changed.emit()
            elif not new_body:
                # 空になった場合は削除
                self.delete_note()
        else:
            self.update_content() # 元に戻す

    def eventFilter(self, obj, event):
        """インプレースエディタのキー入力を監視して確定/キャンセルを処理。"""
        if obj is self.editor and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                # Shift+Enter または Ctrl+Enter の改行・確定処理
                # ここでは Enter で確定（保存）とし、Shift+Enterで改行とします（クイック窓と統一）
                if event.modifiers() & Qt.ShiftModifier:
                    return False # 通常の改行処理
                    
                # IME確定のEnterならスルー
                # QPlainTextEditのサブクラス化していないので、ここでは簡易的にチェック
                # ※SafeTextEditと同様の仕組みをイベントフィルタでも行いたいが、
                # inputMethodEventをフィルタリングする必要があるため、直接キーイベントだけだとIME判定が難しい。
                # そのため、テキスト編集エリアではフォーカスアウト時保存に頼るか、
                # または Ctrl+Enter でのみ確定とする方が安全です。
                # 設計書は「Enterで保存」ですが、インプレース編集時は誤爆しやすいので
                # 「フォーカスアウトで保存」も併用し、キープレスでのEnterは
                # テキストエリアでは改行にし、右上の閉じる、または外側クリックで自動保存にするのが親切な場合があります。
                # ここでは「Ctrl+Return」または「単独Return（IME中でない場合）」で確定とします。
                # 安全第一で「フォーカスアウト時に自動保存」にし、Enterは通常の改行（テキストエディタの挙動）にします。
                # ユーザーが「Enterで保存」を望んでいるのはクイック入力窓なので、
                # 付箋エディタ側は「フォーカスアウト」または「Ctrl+Enter」で確定とするのが一般的です。
                # ここでは、エディタ内でEscが押されたらキャンセル、フォーカスアウトで確定とします。
                pass
            elif event.key() == Qt.Key_Escape:
                self.finish_edit(save=False)
                return True
                
        # フォーカスアウト時に保存
        if obj is self.editor and event.type() == QEvent.FocusOut:
            self.finish_edit(save=True)
            return True
            
        return super().eventFilter(obj, event)

    # --- コンテキストメニュー (右クリック操作) ---

    def contextMenuEvent(self, event):
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

        # メニュー項目
        edit_action = QAction("テキストの変更", self)
        edit_action.triggered.connect(self.start_edit)
        menu.addAction(edit_action)

        # 背景色を変更サブメニュー (プリセット対応)
        color_menu = menu.addMenu("背景色を変更")
        color_menu.setStyleSheet(menu.styleSheet())
        
        presets = [
            ("薄黄色", "rgba(255, 255, 200, 1.0)"),
            ("濃い黄色", "rgba(255, 215, 0, 1.0)"),
            ("水色", "rgba(224, 247, 250, 1.0)"),
            ("ピンク", "rgba(252, 228, 236, 1.0)"),
            ("黒半透明", "rgba(30, 30, 30, 0.65)"),
            ("白半透明", "rgba(255, 255, 255, 0.65)"),
            ("高コントラスト", "rgba(0, 0, 0, 1.0)")
        ]
        
        for name, val in presets:
            act = QAction(name, self)
            act.triggered.connect(lambda checked=False, v=val: self.apply_preset_color(v))
            color_menu.addAction(act)
            
        color_menu.addSeparator()
        custom_color_act = QAction("カスタムカラー...", self)
        custom_color_act.triggered.connect(self.change_color)
        color_menu.addAction(custom_color_act)

        # 文字サイズを変更サブメニュー
        size_menu = menu.addMenu("文字サイズを変更")
        size_menu.setStyleSheet(menu.styleSheet())
        
        sizes = [
            ("小 (10px)", 10),
            ("標準 (12px)", 12),
            ("中 (15px)", 15),
            ("大 (18px)", 18),
            ("特大 (22px)", 22)
        ]
        for name, size_val in sizes:
            act = QAction(name, self)
            act.triggered.connect(lambda checked=False, s=size_val: self.apply_font_size(s))
            size_menu.addAction(act)

        reminder_action = QAction("リマインダー設定...", self)
        reminder_action.triggered.connect(self.set_reminder)
        menu.addAction(reminder_action)

        menu.addSeparator()

        complete_action = QAction("完了にする", self)
        complete_action.triggered.connect(self.complete_note)
        menu.addAction(complete_action)

        hide_action = QAction("一時非表示にする", self)
        hide_action.triggered.connect(self.hide_note)
        menu.addAction(hide_action)

        snooze_action = QAction("明日の9:00まで表示 (以降非表示)", self)
        snooze_action.triggered.connect(self.snooze_to_tomorrow)
        menu.addAction(snooze_action)

        archive_action = QAction("アーカイブする", self)
        archive_action.triggered.connect(self.archive_note)
        menu.addAction(archive_action)

        menu.addSeparator()

        delete_action = QAction("削除", self)
        delete_action.triggered.connect(self.delete_note)
        menu.addAction(delete_action)

        menu.exec(event.globalPos())

    def apply_preset_color(self, color_str):
        self.memo_data["color"] = color_str
        db.update_memo(self.memo_data["id"], color=color_str)
        self.update_style()
        self.data_changed.emit()

    def apply_font_size(self, size_val):
        self.memo_data["font_size"] = size_val
        
        # 文字サイズの変更に合わせて付箋サイズを自動再計算してリサイズする
        w, h = calculate_auto_size(self.memo_data["body"], font_size=size_val)
        self.memo_data["width"] = w
        self.memo_data["height"] = h
        self.resize(w, h)
        
        db.update_memo(self.memo_data["id"], font_size=size_val, width=w, height=h)
        self.update_style()
        self.data_changed.emit()
        
        # サイズが変わったのでマスク領域を更新させる
        if hasattr(self.parentWidget(), "update_mask"):
            self.parentWidget().update_mask()

    def change_color(self):
        # 標準カラーダイアログ (アルファチャンネルを有効にする)
        bg_hex = self.memo_data["color"]
        r, g, b, a = parse_color_string(bg_hex)
        current_color = QColor(r, g, b, a)
        color = QColorDialog.getColor(current_color, self, "背景色を選択", QColorDialog.ShowAlphaChannel)
        if color.isValid():
            # アルファ値も含めて rgba 表記で保存する
            rgba_str = f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha() / 255.0})"
            self.memo_data["color"] = rgba_str
            db.update_memo(self.memo_data["id"], color=rgba_str)
            self.update_style()
            self.data_changed.emit()

    def set_reminder(self):
        current_reminder = self.memo_data.get("reminder_at")
        dialog = ReminderDialog(current_reminder, self)
        result = dialog.exec()
        
        if result == QDialog.Accepted:
            dt_str = dialog.get_datetime_str()
            self.memo_data["reminder_at"] = dt_str
            self.memo_data["reminder_status"] = "pending"
            self.memo_data["reminded_at"] = None
            db.update_memo(self.memo_data["id"], reminder_at=dt_str, reminder_status="pending", reminded_at=None)
            self.update_content()
            self.data_changed.emit()
        elif result == 2:  # 解除
            self.memo_data["reminder_at"] = None
            self.memo_data["reminder_status"] = "pending"
            self.memo_data["reminded_at"] = None
            db.update_memo(self.memo_data["id"], reminder_at=None, reminder_status="pending", reminded_at=None)
            self.update_content()
            self.data_changed.emit()

    def complete_note(self):
        db.update_memo(self.memo_data["id"], status="completed")
        self.data_changed.emit()
        self.close()

    def hide_note(self):
        db.update_memo(self.memo_data["id"], status="hidden")
        self.data_changed.emit()
        self.close()

    def snooze_to_tomorrow(self):
        from datetime import datetime, timedelta
        tomorrow_9am = (datetime.now() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        db.update_memo(self.memo_data["id"], status="active", reminder_at=tomorrow_9am.isoformat(), reminder_status="pending", reminded_at=None)
        self.data_changed.emit()
        self.close()

    def archive_note(self):
        db.update_memo(self.memo_data["id"], status="archived")
        self.data_changed.emit()
        self.close()

    def delete_note(self):
        db.update_memo(self.memo_data["id"], status="deleted")
        self.data_changed.emit()
        self.close()


class OverlayWindow(QWidget):
    """モニターごとに全画面に広がる透明オーバーレイウィンドウ。"""
    data_changed = Signal()  # データ変更をメインアプリに通知
    edit_mode_requested = Signal(bool)  # 編集モードへの切り替え要求を通知

    def __init__(self, monitor_idx, geometry):
        super().__init__()
        self.monitor_idx = monitor_idx
        self.geometry_rect = geometry
        self.is_edit_mode = False
        self.notes = []

        self.init_ui()

    def update_mask(self):
        """付箋がある領域だけをクリック可能にするために、ウィンドウマスクを更新します。"""
        display_mode = db.get_setting("display_mode", "hybrid")
        if self.is_edit_mode or display_mode != "overlay":
            # 編集モード、またはオーバーレイモード以外の場合はマスクを解除する
            self.clearMask()
        else:
            # オーバーレイモードの閲覧時は、付箋がある矩形領域だけをクリック可能にする
            from PySide6.QtGui import QRegion
            region = QRegion()
            for note in self.notes:
                if note.isVisible():
                    region = region.united(QRegion(note.geometry()))
            
            if region.isEmpty():
                # 空のQRegionをセットするとマスク解除になってしまうのを防ぐため、画面外の1x1をセット
                self.setMask(QRegion(-10, -10, 1, 1))
            else:
                self.setMask(region)

    def request_edit_mode(self):
        """閲覧モード中の付箋クリックにより、編集モードへの切り替えを要求します。"""
        self.edit_mode_requested.emit(True)

    def init_ui(self):
        # フレームレス、タスクバー非表示、常に最背面（通常閲覧時）
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnBottomHint | Qt.SubWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        
        # モニターの座標に合わせて配置
        self.setGeometry(self.geometry_rect)
        
        # 通常モードではクリック透過
        self.set_edit_mode(False)

    def set_edit_mode(self, enabled):
        """編集モードの切り替え。閲覧モードではクリック透過、編集モードではクリック可能にし最前面に。"""
        self.is_edit_mode = enabled
        
        # フラグ変更前に非表示にする (Windowsでのハンドル再作成時の表示崩れ防止)
        self.hide()
        
        display_mode = db.get_setting("display_mode", "hybrid")
        
        # ウィンドウフラグの変更
        flags = Qt.FramelessWindowHint | Qt.Tool | Qt.SubWindow
        if enabled:
            # 編集時は操作しやすいよう最前面
            flags |= Qt.WindowStaysOnTopHint
            self.setWindowFlags(flags)
            self.setStyleSheet("background-color: rgba(0, 0, 0, 40);") # 編集モードがわかるようにうっすら暗くする
        else:
            # 閲覧時は壁紙のように最背面
            flags |= Qt.WindowStaysOnBottomHint
            self.setWindowFlags(flags)
            self.setStyleSheet("background-color: transparent;")
            
        # flags変更の後はウィンドウハンドルが再作成され位置サイズがリセットされるため、
        # 必ず元のジオメトリを再設定する
        self.setGeometry(self.geometry_rect)
        self.show()
        
        # Win32 APIでOSレベルのクリック透過スタイルを設定
        try:
            hwnd = int(self.winId())
            if display_mode == "overlay":
                # オーバーレイモードでは閲覧時もWin32透過にせず、マスクで部分透過制御する
                set_window_click_through(hwnd, False)
                self.update_mask()
            else:
                set_window_click_through(hwnd, not enabled)
                self.clearMask()
        except Exception as e:
            print(f"Failed to toggle click through: {e}")
            
        if enabled:
            self.raise_()
            self.activateWindow()

    def load_memos(self):
        """このモニターに属するアクティブなメモをロードして表示します。"""
        # 古い付箋ウィジェットを破棄
        for note in self.notes:
            note.close()
            note.deleteLater()
        self.notes.clear()
        
        # データベースからアクティブなメモを取得
        memos = db.get_active_memos()
        
        for memo in memos:
            memo_mon = memo.get("monitor_id")
            
            # このモニターに配置すべきか判定
            should_show = False
            if memo_mon == str(self.monitor_idx):
                should_show = True
            elif memo_mon == "0" and self.monitor_idx == 0:
                should_show = True
                
            if should_show:
                note = StickyNoteWidget(memo, self)
                note.data_changed.connect(self.data_changed.emit)
                # 編集モードの時のみ表示 (オーバーレイモードなら閲覧時も表示する)
                display_mode = db.get_setting("display_mode", "hybrid")
                note.setVisible(self.is_edit_mode or display_mode == "overlay")
                note.show()
                self.notes.append(note)
                
        # マスクを更新
        self.update_mask()

# テスト実行用
if __name__ == "__main__":
    app = QApplication(sys.argv)
    db.init_db()
    
    # テスト用画面 (プライマリ画面)
    screen = QApplication.primaryScreen()
    geom = screen.geometry()
    
    win = OverlayWindow(0, geom)
    win.set_edit_mode(True) # 編集モードで表示テスト
    win.load_memos()
    win.show()
    
    sys.exit(app.exec())
