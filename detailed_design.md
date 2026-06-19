# 壁紙付箋アプリ 詳細設計書

本ドキュメントは、「壁紙付箋アプリ」の要件に基づき、技術的な実現方法と詳細な仕様を定義します。

---

## 1. システム構成とデータモデル

### 1.1. データベース設計 (SQLite)

アプリケーションのデータ管理には SQLite を使用します。データベースファイルはユーザーデータディレクトリ（例: `%APPDATA%/WallpaperStickyNotes/data.db`）に配置します。

#### memos テーブル (付箋データ)
| カラム名 | 型 | 説明 |
| :--- | :--- | :--- |
| `id` | INTEGER | 主キー (AUTOINCREMENT) |
| `body` | TEXT | 付箋のテキスト内容 |
| `status` | TEXT | 状態 (`active`: 表示中, `completed`: 完了, `deleted`: 削除済) |
| `color` | TEXT | 付箋の背景色 (HEXコードまたはrgba、例: `rgba(255,255,200,1.0)`) |
| `monitor_id` | TEXT | 表示対象のモニター識別子 (例: SCREEN_NAME またはインデックス) |
| `x` | INTEGER | 配置するX座標 (モニター内相対座標) |
| `y` | INTEGER | 配置するY座標 (モニター内相対座標) |
| `width` | INTEGER | 付箋の幅 (px) |
| `height` | INTEGER | 付箋の高さ (px) |
| `z_index` | INTEGER | 重なり順 |
| `pinned` | BOOLEAN | 最前面ピン留めフラグ (オーバーレイ表示時) |
| `priority` | INTEGER | 優先度 (表示順や並び替え用) |
| `reminder_at` | TEXT | 通知予定日時 (ISO 8601 形式: `YYYY-MM-DDTHH:MM:SS`) |
| `font_size` | INTEGER | フォントサイズ (px) |
| `reminder_status` | TEXT | リマインダー通知ステータス (`pending`: 未通知, `notified`: 通知済) |
| `reminded_at` | TEXT | 実際に通知が送信された実績日時 (ISO 8601 形式) |
| `created_at` | TEXT | 作成日時 (ISO 8601 形式) |
| `updated_at` | TEXT | 更新日時 (ISO 8601 形式) |

#### settings テーブル (アプリ設定)
| カラム名 | 型 | 説明 |
| :--- | :--- | :--- |
| `key` | TEXT | 設定のキー名 (主キー) |
| `value` | TEXT | 設定の値 (JSON文字列または文字列) |

※設定項目：
- `display_mode` (`wallpaper` / `overlay` / `hybrid`)
- `layout_direction` (`diagonal` / `vertical` / `horizontal` / `from_right` / `from_left`)
- `hotkey` (デフォルト: `Ctrl+Alt+N`)
- `default_note_color` (デフォルト: `#FFFFC8`)
- `auto_apply_wallpaper` (デフォルト: `true`)
- `startup_enabled` (デフォルト: `false`)
- `startup_method` (`registry` / `folder`)
- `base_wallpapers` (各モニターの元の壁紙ファイルパスを格納するJSON)

---

## 2. 技術的解決策と実装詳細

### 2.1. グローバルホットキーの処理と衝突対策
- **実装方法**:
  - `ctypes` を用いて Windows API の `RegisterHotKey` を直接呼び出します。監視はバックグラウンドスレッド（`GlobalHotkeyThread`）で実行します。
  - ホットキー検知時、PySide6のカスタムシグナル（`activated`）を発火させてGUIスレッドに通知し、「クイック入力小窓」を安全に表示させます。
- **衝突（競合）対策**:
  - アプリ起動時またはホットキー変更時、設定されたキーが他のアプリケーションで使用されていて登録できない場合、自動で安全な代替キー候補（`Ctrl+Alt+Shift+N`、`Ctrl+Alt+K`、`Ctrl+Alt+M`、`Ctrl+Alt+Y`、`Ctrl+Alt+I`、`Ctrl+Shift+N`、`Alt+Shift+N`）を順次テストし、競合しないキーを自動で割り当てます。
  - 代替キーで登録された場合は、システムトレイのバルーン通知（ポップアップ）を表示してユーザーに通知します。また、トレイメニューの「クイック入力」欄の表示キー名も動的に更新します。
- **設定画面での事前衝突検証と入力アシスト**:
  - 設定タブのホットキー入力欄にはカスタムウィジェット `HotkeyLineEdit` を使用します。直接キーをタイピングするのではなく、押されたキーの組み合わせ（例: `Ctrl`+`Alt`+`K`）を直接キャプチャし、入力ミスを防ぎます。
  - 設定を保存する前に、一時的に `RegisterHotKey` のテスト登録を実行する `test_hotkey_availability` を呼び出して他のアプリと競合していないか検証します。競合している場合は警告ダイアログを表示して設定の保存を拒否し、以前の設定キーに戻します。

### 2.2. 日本語IMEの Enter 確定と保存処理の衝突回避
- **現象**: テキストエディット内で `Enter` キーを押したときに、日本語の漢字変換確定（IME）の `Enter` なのか、入力完了としての `Enter` なのかを判別しないと、変換確定した瞬間に保存・終了されてしまいます。
- **解決策**:
  - カスタムテキストエディット `SafeTextEdit` (QPlainTextEditのサブクラス) において、`QApplication.inputMethod().isVisible()` を使用して IME の変換候補ウィンドウが表示されているか確認します。
  - 変換候補ウィンドウが表示されている（変換中である）場合は、イベントを親クラスに流して変換確定のキー操作のみを処理し、送信シグナル（`submit_pressed`）の送信をスキップします。

### 2.3. マルチモニターとDPIスケーリングの管理
- **DPIスケーリング**:
  - `QGuiApplication.screens()` を使用して全モニターの論理座標とデバイスピクセル比（`devicePixelRatio`）を取得します。
  - 付箋の座標は「論理座標」で保持し、壁紙画像に書き込む際には `座標 × devicePixelRatio` の物理ピクセル座標に補正して描画することで、異なる解像度やスケーリング設定のモニター間でも位置ズレなく描画します。
- **壁紙の設定方法**:
  - WindowsのCOMインターフェース `IDesktopWallpaper` を使用します。
  - `GetMonitorDevicePathAt` で取得したモニターデバイスIDごとに生成した壁紙画像を `SetWallpaper` することで、マルチモニター環境で異なる壁紙を正確に設定できます。

### 2.4. リマインダー機能とOS通知
- **常駐監視**:
  - `QTimer` を使用して、30秒ごとに SQLite から `reminder_at` が現在時刻以前、かつ `reminder_status` が `'pending'` のアクティブなメモをクエリします。
- **通知の送信**:
  - 該当するメモがあれば、`QSystemTrayIcon.showMessage()` を使って Windows のネイティブ通知バルーンを表示します。
  - 通知完了後、データベース上の `reminder_status` を `'notified'` に更新し、`reminded_at` に実際の通知送信日時のタイムスタンプを記録します。これにより、元の設定時刻を消去せずに履歴（予定日時と通知実績）を保存し続け、後から確認することを可能にします。

### 2.5. スタートアップ自動起動
- **設定方式の選択**:
  - 設定の「スタートアップ起動」がONになった際、レジストリ登録（推奨）とスタートアップフォルダへのショートカット作成の2種類を選択して登録できます。
- **レジストリ登録**:
  - Windowsレジストリの `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` にアプリ起動コマンドを登録します。
- **スタートアップフォルダ登録**:
  - PowerShellを使用して、ユーザーの `APPDATA/Microsoft/Windows/Start Menu/Programs/Startup` フォルダに起動用ショートカット（`.lnk`）をサイレント作成・削除します。

### 2.6. 多重起動防止 (シングルインスタンス化)
- **実装方法**:
  - `QLockFile` を使用して、起動時に専用のロックファイル（`app.lock`）を作成します。
  - すでにアプリの別プロセスが起動していてロックの取得に失敗した場合、**「壁紙付箋アプリは既に起動しています」**という警告ダイアログを `QMessageBox` で表示し、直ちに安全に自動終了 (`sys.exit(0)`) させます。これにより、壁紙バックアップデータの衝突やデータベースのロックエラーを防止します。

### 2.7. データ管理と初期化
- **インポート / エクスポート**:
  - 設定データと付箋データをまとめて JSON 形式でインポート・エクスポートすることができます。
  - インポート時には、「現在の付箋を残したまま取り込む（追加）」か「既存の付箋をすべて消去して取り込む（上書き）」かを選択できます。
- **初期化**:
  - 登録されているすべての付箋を物理的に一括消去する初期化機能を提供します。

---

## 3. 画面の遷移とUIデザイン

```mermaid
graph TD
    Tray[システムトレイ常駐] -->|右クリック| Menu[コンテキストメニュー]
    Menu -->|設定/管理| ManageWin[管理画面]
    Menu -->|終了| Exit[アプリ終了]
    
    Hotkey[Ctrl+Alt+N 等 / ホットキー] --> QuickInput[クイック入力小窓]
    QuickInput -->|Enter (保存)| SaveDB[SQLiteへ保存 & 壁紙再生成]
    
    ManageWin -->|設定変更| SaveDB
    ManageWin -->|新規追加/編集/削除| SaveDB
    ManageWin -->|データインポート/エクスポート| SaveDB
    
    SaveDB -->|表示モード判定| ModeCheck{モードは?}
    ModeCheck -->|壁紙 / ハイブリッド| RenderWallpaper[Pillowで壁紙生成 & 反映]
    ModeCheck -->|オーバーレイ / ハイブリッド| RenderOverlay[PySide6 透過ウィンドウ表示]
```

### 3.1. クイック入力小窓 (Quick Input Window)
- フレームレスの半透明なアクリル/グラスモーフィズム風デザインのウィンドウをマウスカーソルがある画面の中央に表示。
- 入力テキストエディットにフォーカスがあたった状態で起動し、`Enter` で保存、`Esc` で破棄して閉じます。
- リマインダー設定のための `🕐`（時計）マークボタンがあり、クリックして通知日時を設定・解除できます。

### 3.2. 管理画面 (Management Window)
- タブ切り替え式の管理パネル。
  - **「付箋一覧」タブ**: 現在登録されている付箋をリスト表示。ダブルクリックやボタン操作で編集・削除・完了切り替えが可能です。
  - **「アプリ設定」タブ**: 表示モード、新規付箋の配置ルール、ホットキー、デフォルトカラー、スタートアップ登録方法の選択、データのエクスポート・インポート、付箋の初期化を行えます。

### 3.3. オーバーレイ編集画面 (Overlay Window)
- 各モニターに配置される透明な全画面ウィンドウ。
- **閲覧モード**: 付箋をクリック透過（`WindowTransparentForInput`）で表示し、背後のデスクトップの操作を妨げません。付箋をダブルクリックすることで直接編集モードに入ることができます。
- **編集モード**: クリック透過を解除し、付箋ウィジェットをドラッグで移動、端をドラッグしてサイズ変更（リサイズ）できます。
- **コンテキストメニュー**: 付箋を右クリックして、その場でのテキスト変更、色変更、リマインダー設定、削除、完了/未完了の切り替えが行えます。

---

## 4. プログラム構成 (フォルダ構成)

```text
壁紙付箋アプリ/
│  .gitignore            # 不要ファイルの除外設定
│  LICENSE               # GPL v3 ライセンスファイル
│  README.md             # プロジェクト解説・マニュアル
│  requirements.txt      # 依存ライブラリ一覧 (Pillow, PySide6)
│  setup.bat             # 自動環境構築バッチファイル
│  run.bat               # アプリ起動バッチファイル (コンソール非表示)
│  Wallpaper-Sticky-Notes.zip # 配布用クリーンZIP
│
└─src/
        app.py           # アプリコントローラ、トレイ常駐、多重起動制御
        db.py            # SQLiteデータベース、データ入出力、インポート/エクスポート
        gui_input.py     # クイック入力小窓 (SafeTextEdit実装)
        gui_manage.py    # 管理画面、設定画面、HotkeyLineEdit実装
        gui_overlay.py   # 透過オーバーレイ、付箋ウィジェット
        hotkey.py        # グローバルホットキー登録・衝突回避ロジック
        wallpaper.py     # Pillowによる壁紙への付箋描画・COM連携適用
```
