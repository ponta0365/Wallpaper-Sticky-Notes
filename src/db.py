import os
import sqlite3
import json
from datetime import datetime

DB_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "WallpaperStickyNotes")
DB_PATH = os.path.join(DB_DIR, "data.db")

def get_db_connection():
    """データベース接続を取得します。"""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """データベースとテーブルを初期化します。デフォルト設定値も挿入します。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # memos テーブルの作成
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS memos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        body TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        color TEXT NOT NULL,
        monitor_id TEXT NOT NULL,
        x INTEGER NOT NULL DEFAULT 100,
        y INTEGER NOT NULL DEFAULT 100,
        width INTEGER NOT NULL DEFAULT 200,
        height INTEGER NOT NULL DEFAULT 200,
        z_index INTEGER NOT NULL DEFAULT 0,
        pinned BOOLEAN NOT NULL DEFAULT 0,
        priority INTEGER NOT NULL DEFAULT 0,
        reminder_at TEXT,
        font_size INTEGER NOT NULL DEFAULT 12,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)
    
    # 既存のDBにカラムがない場合のマイグレーション
    try:
        cursor.execute("SELECT font_size FROM memos LIMIT 1")
    except sqlite3.OperationalError:
        try:
            cursor.execute("ALTER TABLE memos ADD COLUMN font_size INTEGER NOT NULL DEFAULT 12")
        except Exception as e:
            print("Migration warning (font_size):", e)
    
    # settings テーブルの作成
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """)
    
    # デフォルト設定値の挿入
    default_settings = {
        "display_mode": "hybrid",
        "hotkey": "Ctrl+Alt+N",
        "default_note_color": "#FFFFC8",
        "auto_apply_wallpaper": "true",
        "startup_enabled": "false",
        "base_wallpapers": "{}",
        "layout_direction": "diagonal"
    }
    
    for key, val in default_settings.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, val))
        
    conn.commit()
    conn.close()

# --- memos 操作関数 ---

def normalize_monitor_id(mon_id):
    """モニターIDを正規化します。インデックスかデバイス名かに関わらず、
    プライマリモニターを指すものをすべて '0' に統一します。"""
    if not mon_id:
        return "0"
    mon_id_str = str(mon_id).strip()
    if mon_id_str in ("0", "primary", "Unknown", "") or "DISPLAY1" in mon_id_str:
        return "0"
    return mon_id_str.replace("\\\\.\\", "")

def is_overlapping(x1, y1, w1, h1, x2, y2, w2, h2):
    """2つの矩形が重なっている（衝突している）か判定します。"""
    return not (x1 + w1 <= x2 or x2 + w2 <= x1 or y1 + h1 <= y2 or y2 + h2 <= y1)

def get_next_position(monitor_id="0", default_x=100, default_y=100, width=200, height=150, 
                      monitor_width=None, monitor_height=None):
    """配置スタイル設定に基づいて、既存のメモと領域が重ならない次の座標 (x, y) を計算します。"""
    active_memos = get_active_memos()
    direction = get_setting("layout_direction", "diagonal")
    
    # 動的にQtからスクリーンサイズを取得
    m_width, m_height = monitor_width, monitor_height
    if m_width is None or m_height is None:
        try:
            from PySide6.QtGui import QGuiApplication
            app = QGuiApplication.instance()
            if app:
                screens = app.screens()
                target_screen = None
                try:
                    idx = int(monitor_id)
                    if 0 <= idx < len(screens):
                        target_screen = screens[idx]
                except ValueError:
                    for s in screens:
                        if s.name() == monitor_id:
                            target_screen = s
                            break
                if not target_screen and screens:
                    target_screen = screens[0]
                
                if target_screen:
                    geom = target_screen.geometry()
                    m_width = geom.width()
                    m_height = geom.height()
        except Exception:
            pass

    if m_width is None: m_width = 1920
    if m_height is None: m_height = 1080
    
    # スタイルごとの初期位置
    if direction == "from_right":
        x = m_width - width - 50
        y = 100
    elif direction == "from_left":
        x = 50
        y = 100
    else:
        x = default_x
        y = default_y
        
    overlapping = True
    attempts = 0
    max_attempts = 100
    
    while overlapping and attempts < max_attempts:
        overlapping = False
        for memo in active_memos:
            if normalize_monitor_id(memo["monitor_id"]) == normalize_monitor_id(monitor_id):
                mx, my = memo["x"], memo["y"]
                mw, mh = memo["width"], memo["height"]
                # 矩形衝突判定
                if is_overlapping(x, y, width, height, mx, my, mw, mh):
                    overlapping = True
                    attempts += 1
                    
                    if direction == "diagonal":
                        x += 40
                        y += 40
                    elif direction == "vertical":
                        # 縦並び：下に積んでいき、下端を越えたら右の列へ
                        y += mh + 15
                        if y + height > m_height - 50:
                            y = 100
                            x += width + 20
                    elif direction == "horizontal":
                        # 横並び：右に並べていき、右端を越えたら下の行へ
                        x += mw + 15
                        if x + width > m_width - 50:
                            x = 100
                            y += height + 20
                    elif direction == "from_right":
                        # 右端縦並び：右端に沿って下に積み、下端を越えたら左の列へ
                        y += mh + 15
                        if y + height > m_height - 50:
                            y = 100
                            x -= (width + 20)
                    elif direction == "from_left":
                        # 左端縦並び：左端に沿って下に積み、下端を越えたら右の列へ
                        y += mh + 15
                        if y + height > m_height - 50:
                            y = 100
                            x += width + 20
                    else:
                        x += 40
                        y += 40
                    break  # 内側ループを抜けて、ずらした新しい座標で再判定
                    
    return x, y

def add_memo(body, color="#FFFFC8", monitor_id="0", x=None, y=None, width=200, height=200, reminder_at=None, font_size=12):
    """新規メモを追加します。"""
    if x is None or y is None:
        calc_x, calc_y = get_next_position(monitor_id, default_x=100, default_y=100, width=width, height=height)
        x = x if x is not None else calc_x
        y = y if y is not None else calc_y

    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute("""
    INSERT INTO memos (body, color, monitor_id, x, y, width, height, reminder_at, font_size, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (body, color, str(monitor_id), x, y, width, height, reminder_at, font_size, now, now))
    memo_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return memo_id

def update_memo(memo_id, **kwargs):
    """指定されたIDのメモを更新します。"""
    if not kwargs:
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    kwargs["updated_at"] = datetime.now().isoformat()
    
    # カラム名と値のプレースホルダを作成
    fields = [f"{key} = ?" for key in kwargs.keys()]
    values = list(kwargs.values())
    values.append(memo_id)
    
    query = f"UPDATE memos SET {', '.join(fields)} WHERE id = ?"
    cursor.execute(query, values)
    conn.commit()
    conn.close()

def get_active_memos():
    """表示中(active)のメモをすべて取得します。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM memos WHERE status = 'active' ORDER BY z_index ASC, id ASC")
    memos = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return memos

def get_all_memos():
    """すべてのメモを取得します（管理画面用）。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM memos ORDER BY status ASC, created_at DESC")
    memos = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return memos

# --- settings 操作関数 ---

def get_setting(key, default=None):
    """設定値を取得します。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    if row:
        val = row["value"]
        # JSON形式か、ブール値/文字列かの判定と変換
        if val.lower() == "true":
            return True
        elif val.lower() == "false":
            return False
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return val
    return default

def set_setting(key, value):
    """設定値を保存します。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if isinstance(value, (dict, list)):
        val_str = json.dumps(value)
    elif isinstance(value, bool):
        val_str = "true" if value else "false"
    else:
        val_str = str(value)
        
    cursor.execute("""
    INSERT INTO settings (key, value)
    VALUES (?, ?)
    ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, (key, val_str))
    conn.commit()
    conn.close()

def export_data(file_path):
    """アクティブな付箋とアプリ設定をJSONファイルにエクスポートします。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # memos の取得 (idやcreated_atなどはインポート時に再生成されるため除外)
    cursor.execute("SELECT body, color, monitor_id, x, y, width, height, reminder_at, font_size FROM memos WHERE status = 'active'")
    memos = [dict(row) for row in cursor.fetchall()]
    
    # settings の取得 (base_wallpaper_path などの環境固有設定は除外)
    cursor.execute("SELECT key, value FROM settings WHERE key NOT IN ('base_wallpaper_path', 'base_wallpapers', 'original_wallpaper_style', 'original_tile_wallpaper')")
    settings = {row["key"]: row["value"] for row in cursor.fetchall()}
    
    conn.close()
    
    data = {
        "version": "1.0",
        "memos": memos,
        "settings": settings
    }
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def import_data(file_path, mode="append"):
    """JSONファイルから付箋と設定をインポートします。
    mode: 'append' (現在の付箋に追加), 'overwrite' (現在の付箋をすべて削除してから追加)
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    memos = data.get("memos", [])
    settings = data.get("settings", {})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if mode == "overwrite":
            cursor.execute("DELETE FROM memos")
            
        now = datetime.now().isoformat()
        
        # memos の挿入
        for m in memos:
            cursor.execute("""
            INSERT INTO memos (body, color, monitor_id, x, y, width, height, reminder_at, font_size, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                m["body"], m["color"], str(m.get("monitor_id", "0")),
                m.get("x", 100), m.get("y", 100),
                m.get("width", 200), m.get("height", 150),
                m.get("reminder_at"), m.get("font_size", 12), now, now
            ))
            
        # settings の反映
        for k, v in settings.items():
            cursor.execute("""
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, (k, str(v)))
            
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        raise e
        
    conn.close()

def clear_all_memos(physical=False):
    """すべての付箋を削除します。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    if physical:
        cursor.execute("DELETE FROM memos")
    else:
        cursor.execute("UPDATE memos SET status = 'deleted'")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized at:", DB_PATH)
