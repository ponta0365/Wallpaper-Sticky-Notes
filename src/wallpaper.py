import os
import shutil
import winreg
import ctypes
from ctypes import wintypes
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtGui import QGuiApplication
import src.db as db

# Windows API definitions
SPI_SETDESKWALLPAPER = 0x0014
SPIF_UPDATEINIFILE = 0x0001
SPIF_SENDCHANGE = 0x0002

BACKUP_DIR = os.path.join(db.DB_DIR, "backups")
TEMP_DIR = os.path.join(db.DB_DIR, "temp")
os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

# Pillowのバージョン互換性を考慮したリサンプリングフィルターの決定
if hasattr(Image, "Resampling"):
    LANCEZOS_FILTER = getattr(Image.Resampling, "LANCEZOS", getattr(Image, "LANCEZOS", 3))
else:
    LANCEZOS_FILTER = getattr(Image, "LANCEZOS", 3)

# 元の壁紙のパス（Windows標準）
TRANSCODED_WALLPAPER = os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Themes\TranscodedWallpaper")

def get_virtual_screen_geometry():
    """Windows API を使用して、仮想画面全体の物理ピクセル座標とサイズを取得します。"""
    user32 = ctypes.windll.user32
    left = user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
    top = user32.GetSystemMetrics(77)    # SM_YVIRTUALSCREEN
    width = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
    height = user32.GetSystemMetrics(79) # SM_CYVIRTUALSCREEN
    return left, top, width, height

def get_monitors_physical():
    """Windows API を使用して、接続されているすべてのモニターの物理座標（ピクセル）を取得します。"""
    monitors = []
    
    def monitor_enum_proc(hMonitor, hdcMonitor, lprcMonitor, dwData):
        rect = lprcMonitor.contents
        monitors.append({
            "left": rect.left,
            "top": rect.top,
            "right": rect.right,
            "bottom": rect.bottom,
            "width": rect.right - rect.left,
            "height": rect.bottom - rect.top
        })
        return True

    MonitorEnumProc = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.RECT),
        ctypes.c_double
    )
    
    proc = MonitorEnumProc(monitor_enum_proc)
    ctypes.windll.user32.EnumDisplayMonitors(None, None, proc, 0)
    return monitors

def get_current_wallpaper_path():
    """現在設定されている壁紙ファイルのパスを取得します（レジストリまたはTranscodedWallpaper）。"""
    if os.path.exists(TRANSCODED_WALLPAPER):
        return TRANSCODED_WALLPAPER
        
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", 0, winreg.KEY_READ)
        wallpaper_path, _ = winreg.QueryValueEx(key, "WallPaper")
        winreg.CloseKey(key)
        if wallpaper_path and os.path.exists(wallpaper_path):
            return wallpaper_path
    except Exception as e:
        print(f"Failed to read wallpaper from registry: {e}")
        
    return None

def backup_current_wallpaper():
    """現在の壁紙をバックアップします。"""
    base_wallpaper = db.get_setting("base_wallpaper_path")
    if base_wallpaper and os.path.exists(base_wallpaper):
        return base_wallpaper
        
    orig_path = get_current_wallpaper_path()
    if orig_path:
        try:
            # 元の表示スタイルも保存
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", 0, winreg.KEY_READ)
                style, _ = winreg.QueryValueEx(key, "WallpaperStyle")
                tile, _ = winreg.QueryValueEx(key, "TileWallpaper")
                winreg.CloseKey(key)
                db.set_setting("original_wallpaper_style", style)
                db.set_setting("original_tile_wallpaper", tile)
                print(f"Original wallpaper style backed up: Style={style}, Tile={tile}")
            except Exception as e:
                print(f"Failed to backup wallpaper style: {e}")

            ext = ".jpg"
            if orig_path == TRANSCODED_WALLPAPER:
                try:
                    with Image.open(orig_path) as img:
                        fmt = img.format
                        if fmt:
                            ext = f".{fmt.lower()}"
                except Exception:
                    pass
            else:
                ext = os.path.splitext(orig_path)[1] or ".jpg"
                
            dest_path = os.path.join(BACKUP_DIR, f"original_wallpaper{ext}")
            shutil.copy2(orig_path, dest_path)
            db.set_setting("base_wallpaper_path", dest_path)
            print(f"Original wallpaper backed up to: {dest_path}")
            return dest_path
        except Exception as e:
            print(f"Failed to backup wallpaper: {e}")
            
    return None

def set_wallpaper_style_to_span():
    """壁紙の表示スタイルを「スパン (Span)」に設定します。"""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, "WallpaperStyle", 0, winreg.REG_SZ, "22")  # 22 = Span
        winreg.SetValueEx(key, "TileWallpaper", 0, winreg.REG_SZ, "0")
        winreg.CloseKey(key)
        print("Wallpaper style set to Span (22).")
    except Exception as e:
        print(f"Failed to set wallpaper style to Span: {e}")

def get_system_font(size):
    """Windowsの日本語フォントを取得します。"""
    font_paths = [
        r"C:\Windows\Fonts\meiryo.ttc",     # メイリオ
        r"C:\Windows\Fonts\msgothic.ttc",   # MS ゴシック
        r"C:\Windows\Fonts\yu Gothic.ttf"    # Yu Gothic
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except IOError:
                continue
    return ImageFont.load_default()

def parse_color_string(color_str):
    """'#RRGGBB' または 'rgba(r,g,b,a)' 形式の色文字列を (r, g, b, a) タプルに変換します。"""
    import re
    color_str = color_str.strip()
    if color_str.startswith("#"):
        hex_color = color_str.lstrip('#')
        if len(hex_color) == 6:
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            a = 255
            return r, g, b, a
        elif len(hex_color) == 8:
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            a = int(hex_color[6:8], 16)
            return r, g, b, a
    elif color_str.startswith("rgba"):
        m = re.match(r"rgba\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d\.]+)\s*\)", color_str)
        if m:
            r = int(m.group(1))
            g = int(m.group(2))
            b = int(m.group(3))
            a = int(float(m.group(4)) * 255)
            return r, g, b, a
    return 255, 255, 200, 255

def draw_sticky_note(overlay_img, x, y, w, h, body, bg_color, dpi_scale, reminder_at=None, font_size=12):
    """画像上に付箋を描画します（アルファブレンド対応）。"""
    shadow_offset = int(4 * dpi_scale)
    shadow_color = (0, 0, 0, 40)
    radius = int(8 * dpi_scale)
    
    # 影と付箋が収まるテンポラリイメージを作成
    note_w = w + shadow_offset
    note_h = h + shadow_offset
    note_img = Image.new("RGBA", (note_w, note_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(note_img)
    
    # 1. 影 (ローカル座標)
    draw.rounded_rectangle(
        [shadow_offset, shadow_offset, w, h],
        radius=radius, fill=shadow_color
    )
    
    # 2. 本体色パース
    r, g, b, a = parse_color_string(bg_color)
    draw.rounded_rectangle(
        [0, 0, w, h],
        radius=radius, fill=(r, g, b, a)
    )
    
    # 3. ヘッダーバー
    hr, hg, hb = max(0, r - 30), max(0, g - 30), max(0, b - 30)
    bar_height = int(12 * dpi_scale)
    draw.rounded_rectangle(
        [0, 0, w, bar_height],
        radius=radius, fill=(hr, hg, hb, a)
    )
    draw.rectangle(
        [0, bar_height - radius, w, bar_height],
        fill=(hr, hg, hb, a)
    )
    
    # 4. テキスト
    scaled_font_size = int(font_size * dpi_scale)
    font = get_system_font(scaled_font_size)
    
    # 輝度を計算してテキスト色とリマインダーの色を自動反転
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    if luminance < 140:
        text_color = (240, 240, 240, 255) # 白系
        bell_color = (180, 180, 180, 255)
    else:
        text_color = (30, 30, 30, 255) # 黒系
        bell_color = (120, 120, 120, 255)
    
    padding = int(12 * dpi_scale)
    text_x = padding
    text_y = bar_height + padding
    max_width = w - (padding * 2)
    
    # 自動改行とレイアウト
    lines = []
    paragraphs = body.split('\n')
    for paragraph in paragraphs:
        line = ""
        for char in paragraph:
            test_line = line + char
            bbox = draw.textbbox((0, 0), test_line, font=font)
            test_w = bbox[2] - bbox[0]
            if test_w <= max_width:
                line = test_line
            else:
                lines.append(line)
                line = char
        lines.append(line)
        
    line_spacing = int(4 * dpi_scale)
    curr_y = text_y
    for line in lines:
        if curr_y + scaled_font_size > h - padding:
            draw.text((text_x, curr_y - line_spacing), "...", fill=text_color, font=font)
            break
        draw.text((text_x, curr_y), line, fill=text_color, font=font)
        bbox = draw.textbbox((0, 0), line or " ", font=font)
        curr_y += (bbox[3] - bbox[1]) + line_spacing
        
    # 5. リマインダーマーク
    if reminder_at:
        bell_font = get_system_font(int(10 * dpi_scale))
        try:
            time_part = datetime.fromisoformat(reminder_at).strftime("%H:%M")
        except ValueError:
            time_part = reminder_at
        text_w = draw.textbbox((0, 0), f"rem: {time_part}", font=bell_font)[2]
        draw.text((w - text_w - padding, h - int(15 * dpi_scale) - padding // 2), f"rem: {time_part}", fill=bell_color, font=bell_font)

    # 6. オーバーレイキャンバスにアルファ合成
    overlay_img.alpha_composite(note_img, (x, y))


def render_and_apply_wallpaper():
    """マルチモニターをまたぐ巨大な1枚の画像を生成し、スパンモードで壁紙に適用します。"""
    # 1. QGuiApplication のインスタンス確認
    app = QGuiApplication.instance()
    if not app:
        print("Error: QGuiApplication is not running. Cannot render wallpapers.")
        return
        
    # 2. 元画像のバックアップ
    backup_path = backup_current_wallpaper()
    
    # 3. Windows API から仮想画面全体の物理座標を取得
    v_left, v_top, canvas_w, canvas_h = get_virtual_screen_geometry()
    print(f"Virtual Canvas Size (API): {canvas_w}x{canvas_h} at ({v_left}, {v_top})")
    
    if canvas_w <= 0 or canvas_h <= 0:
        print("Invalid canvas dimensions.")
        return

    # 4. 各モニターの物理座標を取得
    physical_monitors = get_monitors_physical()
    if not physical_monitors:
        print("No physical monitors detected.")
        return
        
    screens = app.screens()
    
    # モニター情報と QScreen (DPIスケール用) の紐付け
    screen_infos = []
    for m in physical_monitors:
        matched_screen = None
        min_dist = 999999
        
        m_center_x = m["left"] + m["width"] / 2
        m_center_y = m["top"] + m["height"] / 2
        
        for s in screens:
            geom = s.geometry()
            dpi = s.devicePixelRatio()
            
            s_center_x = (geom.x() + geom.width() / 2) * dpi
            s_center_y = (geom.y() + geom.height() / 2) * dpi
            
            distance = ((m_center_x - s_center_x) ** 2 + (m_center_y - s_center_y) ** 2) ** 0.5
            if distance < min_dist:
                matched_screen = s
                min_dist = distance
                
        dpi = matched_screen.devicePixelRatio() if matched_screen else 1.0
        name = matched_screen.name() if matched_screen else "Unknown"
        
        screen_infos.append({
            "name": name,
            "dpi": dpi,
            "px": m["left"] - v_left,  # 仮想キャンバス上の物理X開始点
            "py": m["top"] - v_top,    # 仮想キャンバス上の物理Y開始点
            "pw": m["width"],          # モニターの物理幅
            "ph": m["height"]          # モニターの物理高さ
        })
        
    # 5. 元画像をベースにキャンバスを構築
    try:
        if backup_path and os.path.exists(backup_path):
            orig_img = Image.open(backup_path).convert("RGBA")
        else:
            orig_img = None
    except Exception as e:
        print(f"Failed to open original wallpaper: {e}")
        orig_img = None
        
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (30, 30, 40, 255))
    
    orig_style = db.get_setting("original_wallpaper_style")
    orig_tile = db.get_setting("original_tile_wallpaper")
    if orig_style is None or orig_tile is None:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", 0, winreg.KEY_READ)
            orig_style, _ = winreg.QueryValueEx(key, "WallpaperStyle")
            orig_tile, _ = winreg.QueryValueEx(key, "TileWallpaper")
            winreg.CloseKey(key)
            db.set_setting("original_wallpaper_style", orig_style)
            db.set_setting("original_tile_wallpaper", orig_tile)
        except Exception:
            orig_style = "10"
            orig_tile = "0"

    bg_color = get_windows_background_color()
    
    # 各モニター領域に元の壁紙を配置
    for s_info in screen_infos:
        px, py, pw, ph = s_info["px"], s_info["py"], s_info["pw"], s_info["ph"]
        if orig_img:
            try:
                monitor_canvas = Image.new("RGBA", (pw, ph), bg_color)
                img_w, img_h = orig_img.size
                
                if orig_style == "0" and orig_tile == "0":
                    # 中央表示 (Center): リサイズせず中央配置
                    offset_x = (pw - img_w) // 2
                    offset_y = (ph - img_h) // 2
                    monitor_canvas.paste(orig_img, (offset_x, offset_y))
                    
                elif orig_style == "0" and orig_tile == "1":
                    # タイル表示 (Tile)
                    for tx in range(0, pw, img_w):
                        for ty in range(0, ph, img_h):
                            monitor_canvas.paste(orig_img, (tx, ty))
                            
                elif orig_style == "6":
                    # フィット (Fit)
                    scale = min(pw / img_w, ph / img_h)
                    new_w = max(1, int(img_w * scale))
                    new_h = max(1, int(img_h * scale))
                    resized = orig_img.resize((new_w, new_h), LANCEZOS_FILTER)
                    offset_x = (pw - new_w) // 2
                    offset_y = (ph - new_h) // 2
                    monitor_canvas.paste(resized, (offset_x, offset_y))
                    
                elif orig_style == "10":
                    # 画面サイズに合わせる (Fill)
                    scale = max(pw / img_w, ph / img_h)
                    new_w = max(1, int(img_w * scale))
                    new_h = max(1, int(img_h * scale))
                    resized = orig_img.resize((new_w, new_h), LANCEZOS_FILTER)
                    offset_x = (new_w - pw) // 2
                    offset_y = (new_h - ph) // 2
                    cropped = resized.crop((offset_x, offset_y, offset_x + pw, offset_y + ph))
                    monitor_canvas.paste(cropped, (0, 0))
                    
                elif orig_style == "2":
                    # 引き伸ばし (Stretch)
                    resized = orig_img.resize((pw, ph), LANCEZOS_FILTER)
                    monitor_canvas.paste(resized, (0, 0))
                    
                else:
                    # デフォルト (Fill)
                    scale = max(pw / img_w, ph / img_h)
                    new_w = max(1, int(img_w * scale))
                    new_h = max(1, int(img_h * scale))
                    resized = orig_img.resize((new_w, new_h), LANCEZOS_FILTER)
                    offset_x = (new_w - pw) // 2
                    offset_y = (new_h - ph) // 2
                    cropped = resized.crop((offset_x, offset_y, offset_x + pw, offset_y + ph))
                    monitor_canvas.paste(cropped, (0, 0))
                
                canvas.paste(monitor_canvas, (px, py))
            except Exception as e:
                print(f"Failed to process wallpaper for monitor: {e}")
                color_img = Image.new("RGBA", (pw, ph), bg_color)
                canvas.paste(color_img, (px, py))
        else:
            # 単色背景
            color_img = Image.new("RGBA", (pw, ph), bg_color)
            canvas.paste(color_img, (px, py))
            
    # 6. 付箋を描画する
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    active_memos = db.get_active_memos()
    
    for memo in active_memos:
        memo_mon = memo.get("monitor_id")
        
        target_screen = None
        try:
            m_idx = int(memo_mon)
            if 0 <= m_idx < len(screen_infos):
                target_screen = screen_infos[m_idx]
        except ValueError:
            for s_info in screen_infos:
                if s_info["name"] == memo_mon:
                    target_screen = s_info
                    break
                    
        if not target_screen and screen_infos:
            target_screen = screen_infos[0]
            
        if target_screen:
            dpi = target_screen["dpi"]
            spx = target_screen["px"]
            spy = target_screen["py"]
            
            # メモの相対座標を物理ピクセルに変換し、モニターの物理開始座標を加算
            x = spx + int(memo["x"] * dpi)
            y = spy + int(memo["y"] * dpi)
            w = int(memo["width"] * dpi)
            h = int(memo["height"] * dpi)
            
            rem_at = memo.get("reminder_at") if memo.get("reminder_status") == "pending" else None
            draw_sticky_note(
                overlay, x, y, w, h,
                memo["body"], memo["color"], dpi,
                reminder_at=rem_at,
                font_size=memo.get("font_size", 12)
            )
            
    # 合成
    final_img = Image.alpha_composite(canvas, overlay)
    
    # 7. 保存と適用
    temp_file_path = os.path.abspath(os.path.join(TEMP_DIR, "temp_wallpaper_span.png"))
    try:
        final_img.convert("RGB").save(temp_file_path, "PNG")
        
        # 壁紙表示スタイルを「スパン」に設定
        set_wallpaper_style_to_span()
        
        # 壁紙の変更適用
        result = ctypes.windll.user32.SystemParametersInfoW(
            SPI_SETDESKWALLPAPER, 0, temp_file_path,
            SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
        )
        if result:
            print(f"Successfully applied wallpaper (Span mode): {temp_file_path}")
        else:
            print("SystemParametersInfoW failed to set wallpaper.")
    except Exception as e:
        print(f"Failed to apply wallpaper: {e}")

def get_windows_background_color():
    """Windowsのデスクトップ背景色を取得します。"""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Colors", 0, winreg.KEY_READ)
        bg_rgb_str, _ = winreg.QueryValueEx(key, "Background")
        winreg.CloseKey(key)
        parts = [int(x) for x in bg_rgb_str.split()]
        if len(parts) == 3:
            return (parts[0], parts[1], parts[2], 255)
    except Exception:
        pass
    return (30, 30, 40, 255)

def restore_original_wallpaper():
    """バックアップした元の壁紙を復元します。"""
    base_wallpaper = db.get_setting("base_wallpaper_path")
    if base_wallpaper and os.path.exists(base_wallpaper):
        try:
            # 元のスタイルもレジストリに戻す
            orig_style = db.get_setting("original_wallpaper_style")
            orig_tile = db.get_setting("original_tile_wallpaper")
            if orig_style is not None and orig_tile is not None:
                try:
                    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", 0, winreg.KEY_SET_VALUE)
                    winreg.SetValueEx(key, "WallpaperStyle", 0, winreg.REG_SZ, str(orig_style))
                    winreg.SetValueEx(key, "TileWallpaper", 0, winreg.REG_SZ, str(orig_tile))
                    winreg.CloseKey(key)
                    print(f"Restored original wallpaper style: Style={orig_style}, Tile={orig_tile}")
                except Exception as e:
                    print(f"Failed to restore wallpaper style registry: {e}")

            result = ctypes.windll.user32.SystemParametersInfoW(
                SPI_SETDESKWALLPAPER, 0, base_wallpaper,
                SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
            )
            if result:
                print(f"Restored original wallpaper: {base_wallpaper}")
            else:
                print("Failed to restore original wallpaper.")
        except Exception as e:
            print(f"Failed to restore original wallpaper: {e}")

if __name__ == "__main__":
    import sys
    app = QGuiApplication(sys.argv)
    db.init_db()
    
    memos = db.get_active_memos()
    if not memos:
        db.add_memo(
            "これは仮想スクリーン（Spanモード）対応テスト付箋です。\nマルチモニターの境界を跨ぐ場合も安全に描画できます。",
            color="#FFFFC8", monitor_id="0"
        )
        
    render_and_apply_wallpaper()
