import sys
from PySide6.QtCore import Qt, Signal, QSize, QDateTime
from PySide6.QtGui import QColor, QFont, QPalette, QBrush, QPainter, QCursor
from PySide6.QtWidgets import (
    QApplication, QWidget, QFrame, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QGraphicsDropShadowEffect, QPlainTextEdit, QDialog
)
from src.gui_overlay import ReminderDialog

class SafeTextEdit(QPlainTextEdit):
    """IMEの変換決定と送信処理をスマートに両立させるカスタムテキストエディット。"""
    submit_pressed = Signal()
    cancel_pressed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QPlainTextEdit {
                background-color: rgba(30, 30, 35, 180);
                color: #F3F3F3;
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 6px;
                padding: 8px;
                font-family: "Segoe UI", "Meiryo";
                font-size: 14px;
            }
            QPlainTextEdit:focus {
                border: 1px solid rgba(0, 120, 215, 180);
                background-color: rgba(35, 35, 40, 200);
            }
        """)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            # Shift+Enter は改行
            if event.modifiers() & Qt.ShiftModifier:
                super().keyPressEvent(event)
                return
            
            # IMEの変換候補ウィンドウが表示されている場合は、候補の選択・確定のみを優先し、送信しない
            input_method = QApplication.inputMethod()
            if input_method.isVisible():
                super().keyPressEvent(event)
                return
                
            # 何も入力されていない場合は送信しない
            if not self.toPlainText().strip():
                event.accept()
                return
                
            # 保存実行シグナル
            self.submit_pressed.emit()
            event.accept()
            return
            
        elif event.key() == Qt.Key_Escape:
            self.cancel_pressed.emit()
            event.accept()
            return
            
        super().keyPressEvent(event)

class QuickInputWindow(QWidget):
    """スタイリッシュなグラスモーフィズム調のクイック入力小窓。"""
    submitted = Signal(str, object)

    def __init__(self):
        super().__init__()
        self.reminder_at = None
        self.init_ui()

    def init_ui(self):
        # フレームレス、常に最前面、タスクバー非表示
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.SubWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        
        # 初期サイズと配置位置（画面中央に表示するためのダミー、表示時に再計算）
        self.resize(450, 205)
        
        # メインフレーム（半透明で角丸、ボーダー付き）
        self.frame = QFrame(self)
        self.frame.setGeometry(0, 0, 450, 205)
        self.frame.setStyleSheet("""
            QFrame#mainFrame {
                background-color: rgba(20, 20, 25, 220);
                border: 1px solid rgba(255, 255, 255, 40);
                border-radius: 12px;
            }
        """)
        self.frame.setObjectName("mainFrame")
        
        # ドロップシャドウ効果
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 120))
        shadow.setOffset(0, 4)
        self.frame.setGraphicsEffect(shadow)
        
        # レイアウト
        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(15, 15, 15, 10)
        layout.setSpacing(8)
        
        # タイトル/ヘッダー
        self.title_label = QLabel("クイックメモ入力", self.frame)
        self.title_label.setStyleSheet("""
            color: rgba(255, 255, 255, 200);
            font-family: "Segoe UI", "Meiryo";
            font-size: 12px;
            font-weight: bold;
        """)
        layout.addWidget(self.title_label)
        
        # 入力テキストエディット
        self.text_edit = SafeTextEdit(self.frame)
        self.text_edit.setPlaceholderText("ここにメモを入力...")
        self.text_edit.submit_pressed.connect(self.handle_submit)
        self.text_edit.cancel_pressed.connect(self.close)
        layout.addWidget(self.text_edit)
        
        # コントロールエリア（リマインダーボタン）
        control_layout = QHBoxLayout()
        control_layout.setContentsMargins(0, 0, 0, 0)
        
        self.reminder_btn = QPushButton("🕐 通知設定なし", self.frame)
        self.reminder_btn.clicked.connect(self.set_reminder)
        self.reminder_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 15);
                color: rgba(255, 255, 255, 180);
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 4px;
                padding: 4px 10px;
                font-family: "Segoe UI", "Meiryo";
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 30);
            }
        """)
        control_layout.addWidget(self.reminder_btn)
        control_layout.addStretch()
        layout.addLayout(control_layout)
        
        # フッターガイド
        self.footer_label = QLabel("Enter: 保存  /  Shift+Enter: 改行  /  Esc: 閉じる", self.frame)
        self.footer_label.setAlignment(Qt.AlignCenter)
        self.footer_label.setStyleSheet("""
            color: rgba(255, 255, 255, 100);
            font-family: "Segoe UI", "Meiryo";
            font-size: 10px;
        """)
        layout.addWidget(self.footer_label)
        
        # フォーカスを設定
        self.text_edit.setFocus()
 
    def handle_submit(self):
        text = self.text_edit.toPlainText().strip()
        if text:
            self.submitted.emit(text, self.reminder_at)
            self.text_edit.clear()
            self.reminder_at = None
            self.reminder_btn.setText("🕐 通知設定なし")
            self.reminder_btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(255, 255, 255, 15);
                    color: rgba(255, 255, 255, 180);
                    border: 1px solid rgba(255, 255, 255, 30);
                    border-radius: 4px;
                    padding: 4px 10px;
                    font-family: "Segoe UI", "Meiryo";
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 30);
                }
            """)
            self.close()
 
    def set_reminder(self):
        dialog = ReminderDialog(self.reminder_at, self)
        result = dialog.exec()
        
        if result == QDialog.Accepted:
            self.reminder_at = dialog.get_datetime_str()
            try:
                time_str = QDateTime.fromString(self.reminder_at, Qt.ISODate).toString("MM-dd HH:mm")
            except Exception:
                time_str = self.reminder_at
            self.reminder_btn.setText(f"🕐 {time_str} に通知")
            self.reminder_btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(0, 122, 204, 100);
                    color: white;
                    border: 1px solid #007ACC;
                    border-radius: 4px;
                    padding: 4px 10px;
                    font-family: "Segoe UI", "Meiryo";
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: rgba(0, 122, 204, 150);
                }
            """)
        elif result == 2:  # 解除
            self.reminder_at = None
            self.reminder_btn.setText("🕐 通知設定なし")
            self.reminder_btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(255, 255, 255, 15);
                    color: rgba(255, 255, 255, 180);
                    border: 1px solid rgba(255, 255, 255, 30);
                    border-radius: 4px;
                    padding: 4px 10px;
                    font-family: "Segoe UI", "Meiryo";
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 30);
                }
            """)

    def showEvent(self, event):
        """表示される際に、アクティブな画面の中央に配置します。"""
        super().showEvent(event)
        self.center_on_screen()
        self.text_edit.setFocus()
        self.activateWindow()

    def center_on_screen(self):
        """現在マウスカーソルがあるスクリーンの中央にウィンドウを配置します。"""
        # マウスがあるスクリーンを取得
        screen = QApplication.screenAt(QCursor.pos())
        if not screen:
            screen = QApplication.primaryScreen()
            
        screen_geom = screen.geometry()
        x = screen_geom.x() + (screen_geom.width() - self.width()) // 2
        y = screen_geom.y() + (screen_geom.height() - self.height()) // 2
        self.move(x, y)

    def paintEvent(self, event):
        """背景の微調整など。"""
        super().paintEvent(event)

# テスト実行用
if __name__ == "__main__":
    from PySide6.QtGui import QCursor
    app = QApplication(sys.argv)
    
    win = QuickInputWindow()
    win.submitted.connect(lambda text: print("Submitted text:", text))
    win.show()
    
    sys.exit(app.exec())
