import ctypes
from ctypes import wintypes
from PySide6.QtCore import QThread, Signal
import src.db as db

# Windows API Constants
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

# VK key codes
VK_CODES = {
    'A': 0x41, 'B': 0x42, 'C': 0x43, 'D': 0x44, 'E': 0x45, 'F': 0x46, 'G': 0x47,
    'H': 0x48, 'I': 0x49, 'J': 0x4A, 'K': 0x4B, 'L': 0x4C, 'M': 0x4D, 'N': 0x4E,
    'O': 0x4F, 'P': 0x50, 'Q': 0x51, 'R': 0x52, 'S': 0x53, 'T': 0x54, 'U': 0x55,
    'V': 0x56, 'W': 0x57, 'X': 0x58, 'Y': 0x59, 'Z': 0x5A,
    '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34, '5': 0x35, '6': 0x36,
    '7': 0x37, '8': 0x38, '9': 0x39,
    'F1': 0x70, 'F2': 0x71, 'F3': 0x72, 'F4': 0x73, 'F5': 0x74, 'F6': 0x75,
    'F7': 0x76, 'F8': 0x77, 'F9': 0x78, 'F10': 0x79, 'F11': 0x7A, 'F12': 0x7B,
    'SPACE': 0x20, 'ENTER': 0x0D, 'ESC': 0x1B, 'TAB': 0x09
}

def parse_hotkey_string(hotkey_str):
    """'Ctrl+Alt+N'のようなホットキー文字列をWindows API用のmodifiersとvkCodeにパースします。"""
    parts = hotkey_str.upper().split('+')
    modifiers = MOD_NOREPEAT
    vk_code = 0
    
    for part in parts:
        part = part.strip()
        if part in ('CTRL', 'CONTROL'):
            modifiers |= MOD_CONTROL
        elif part == 'ALT':
            modifiers |= MOD_ALT
        elif part == 'SHIFT':
            modifiers |= MOD_SHIFT
        elif part == 'WIN':
            modifiers |= MOD_WIN
        else:
            vk_code = VK_CODES.get(part, 0)
            if vk_code == 0 and len(part) == 1:
                # 辞書にない1文字キーのフォールバック
                vk_code = ord(part)
                
    return modifiers, vk_code

class GlobalHotkeyThread(QThread):
    """Windows APIを使用してグローバルホットキーを監視するバックグラウンドスレッド。"""
    activated = Signal()
    # 引数: 元設定されていたキー, 実際に登録されたキー(登録失敗時はNone)
    registration_status = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = True
        self.thread_id = None
        self.hotkey_id = 1001

    def run(self):
        # スレッドIDを取得（終了シグナルの送信用）
        self.thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        
        # 設定からホットキーを取得してパース
        hotkey_str = db.get_setting("hotkey", "Ctrl+Alt+N")
        if not hotkey_str or not hotkey_str.strip():
            hotkey_str = "Ctrl+Alt+N"
        modifiers, vk_code = parse_hotkey_string(hotkey_str)
        
        if vk_code == 0:
            print(f"Invalid hotkey configuration: {hotkey_str}")
            self.registration_status.emit(hotkey_str, None)
            return
            
        user32 = ctypes.windll.user32
        
        # まず元々の希望ホットキーで登録を試みる
        success = user32.RegisterHotKey(None, self.hotkey_id, modifiers, vk_code)
        if success:
            print(f"Global hotkey registered: {hotkey_str}")
            self.registration_status.emit(hotkey_str, hotkey_str)
        else:
            print(f"Failed to register primary hotkey: {hotkey_str} (error: {ctypes.windll.kernel32.GetLastError()})")
            
            # 競合発生時、安全な代替候補キーを順番にテスト登録
            fallbacks = [
                "Ctrl+Alt+Shift+N",
                "Ctrl+Alt+K",
                "Ctrl+Alt+M",
                "Ctrl+Alt+Y",
                "Ctrl+Alt+I",
                "Ctrl+Shift+N",
                "Alt+Shift+N"
            ]
            
            # 希望キーは除外
            fallbacks = [f for f in fallbacks if f.upper() != hotkey_str.upper()]
            
            fallback_success = False
            for candidate in fallbacks:
                f_mods, f_vk = parse_hotkey_string(candidate)
                if f_vk != 0:
                    success = user32.RegisterHotKey(None, self.hotkey_id, f_mods, f_vk)
                    if success:
                        print(f"Fallback hotkey registered successfully: {candidate}")
                        self.registration_status.emit(hotkey_str, candidate)
                        fallback_success = True
                        break
                        
            if not fallback_success:
                print("All fallback hotkeys failed to register.")
                self.registration_status.emit(hotkey_str, None)
                return
        
        msg = wintypes.MSG()
        while self.running:
            # スレッドメッセージを取得 (GetMessageW はブロックする)
            res = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if res > 0:
                if msg.message == WM_HOTKEY and msg.wParam == self.hotkey_id:
                    self.activated.emit()
                elif msg.message == WM_QUIT:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                break
                
        # ホットキーの解除
        user32.UnregisterHotKey(None, self.hotkey_id)
        print("Global hotkey unregistered.")

    def stop(self):
        """スレッドを安全に停止します。"""
        self.running = False
        if self.thread_id:
            # GetMessageW のブロックを解除するために WM_QUIT をポストする
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
        self.wait()

def test_hotkey_availability(hotkey_str):
    """指定したホットキーが現在他のアプリと衝突せずに使用可能かテストします。"""
    modifiers, vk_code = parse_hotkey_string(hotkey_str)
    if vk_code == 0:
        return False
    user32 = ctypes.windll.user32
    dummy_id = 9999
    # 登録を試みる
    success = user32.RegisterHotKey(None, dummy_id, modifiers, vk_code)
    if success:
        # 登録に成功したら直ちに解除
        user32.UnregisterHotKey(None, dummy_id)
        return True
    return False

