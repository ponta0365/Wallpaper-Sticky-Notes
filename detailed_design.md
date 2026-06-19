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
| `color` | TEXT | 付箋の背景色 (HEXコード, 例: `#FFFFC8`) |
| `monitor_id` | TEXT | 表示対象のモニター識別子 (例: SCREEN_NAME またはインデックス) |
| `x` | INTEGER | 配置するX座標 (モニター内相対座標) |
| `y` | INTEGER | 配置するY座標 (モニター内相対座標) |
| `width` | INTEGER | 付箋の幅 (px) |
| `height` | INTEGER | 付箋の高さ (px) |
| `z_index` | INTEGER | 重なり順 |
| `pinned` | BOOLEAN | 最前面ピン留めフラグ (オーバーレイ表示時) |
| `priority` | INTEGER | 優先度 (表示順や並び替え用) |
| `reminder_at` | TEXT | 通知予定日時 (ISO 8601 形式: `YYYY-MM-DD HH:MM:SS`) |
| `created_at` | TEXT | 作成日時 (ISO 8601 形式) |
| `updated_at` | TEXT | 更新日時 (ISO 8601 形式) |

#### settings テーブル (アプリ設定)
| カラム名 | 型 | 説明 |
| :--- | :--- | :--- |
| `key` | TEXT | 設定のキー名 (主キー) |
| `value` | TEXT | 設定の値 (JSON文字列または文字列) |

※設定項目：
- `display_mode` (`wallpaper` / `overlay` / `hybrid`)
- `hotkey` (デフォルト: `Ctrl+Alt+N`)
- `default_note_color` (デフォルト: `#FFFFC8`)
- `auto_apply_wallpaper` (デフォルト: `true`)
- `startup_enabled` (デフォルト: `false`)
- `base_wallpapers` (各モニターの元の壁紙ファイルパスを格納するJSON)

---

## 2. 技術的解決策と実装詳細

### 2.1. グローバルホットキーの処理
- **ライブラリ**: `keyboard` ライブラリ、もしくは Windows API の `RegisterHotKey` (ctypes) を使用します。
  - 依存を減らすため、かつ安定動作のために `ctypes` を用いた Windows API の直接呼び出しを推奨します。
- **スレッド連携**:
  - ホットキー監視はバックグラウンドスレッドで実行します。
  - ホットキー検知時、PySide6のカスタムシグナル（`QObject` の `Signal`）を発火させてGUIスレッドに通知し、「クイック入力小窓」を安全に表示させます。

### 2.2. 日本語IMEの Enter 確定と保存処理の衝突回避
- **現象**: クイック入力小窓などで `Enter` キーを押したときに、日本語の漢字変換確定（IME）の `Enter` なのか、入力完了としての `Enter` なのかを判別しないと、変換確定した瞬間に小窓が閉じてしまいます。
- **解決策**:
  - PySide6の `QTextEdit` または `QLineEdit` のイベントハンドリングにおいて、キープレスイベントだけでなく `inputMethodEvent` や `focusInEvent` などを監視します。
  - より確実な方法として、`QKeyEvent` の処理時に「IME入力中であるか」を判断します。Qtでは `QInputMethod` オブジェクトを介して `qApp->inputMethod()->isMicroFocusActive()` や、IMEがオープンしているかを確認できます。
  - または、テキスト入力欄で `Enter` が押された際、`event->key() == Qt::Key_Return` または `Qt::Key_Enter` のときに `QInputMethodEvent` の状態を確認し、未確定テキスト（`preeditString`）が存在する場合はイベントを通し、確定テキストのみが存在する（または空）の状態で `Enter` が押された場合のみ「保存して閉じる」処理を実行します。

### 2.3. マルチモニターとDPIスケーリングの管理
- **DPIスケーリング**:
  - Windowsではモニターごとに異なるDPI（拡大率）が設定されている場合があります。
  - `QGuiApplication.screens()` を使用して全モニターのリストを取得し、各モニターの `geometry()` (論理座標) と `devicePixelRatio()` (拡大率) を取得します。
  - 付箋の座標は「論理座標」で保持し、壁紙画像に書き込む際には `座標 × devicePixelRatio()` の物理ピクセル座標に補正して描画します。
- **壁紙の設定方法**:
  - `ctypes` で `SystemParametersInfoW(SPI_SETDESKWALLPAPER, ...)` を呼び出すと、プライマリモニターのみ、あるいはスパンされた壁紙になってしまいます。
  - モニターごとに個別の壁紙をセットするには、WindowsのCOMインターフェースである `IDesktopWallpaper` を使用します。
  - Pythonの `comtypes` ライブラリ（または `ctypes` でCOMの仮想関数テーブルを叩くコード）を使用して `IDesktopWallpaper` にアクセスし、モニターデバイスID（`GetMonitorDevicePathAt` で取得）ごとに生成した壁紙画像を `SetWallpaper` します。

### 2.4. リマインダー機能とOS通知
- **常駐監視**:
  - アプリはバックグラウンド（タスクバーまたはシステムトレイ `QSystemTrayIcon`）に常駐します。
  - `QTimer` を使用して、60秒ごとに SQLite から `reminder_at` が現在時刻以前かつ未通知의 メモをクエリします。
- **通知の送信**:
  - 該当するメモがあれば、`QSystemTrayIcon.showMessage()` を使って Windows のネイティブ通知バルーンを表示します。
  - 通知をクリックすると、その付箋をハイライト表示または編集画面を開きます。
  - 通知完了後、データベースに通知済フラグ（または `reminder_status = 'notified'`）を記録します。

### 2.5. スタートアップ自動起動
- **実装方法**:
  - 設定の「スタートアップ起動」がONになった際、Windowsレジストリの `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run` に、本アプリの実行パスを書き込みます。
  - レジストリキー: `WallpaperStickyNotes`
  - 値: `"{Pythonのパス} -w {スクリプトのパス}"` または PyInstaller 等でパッケージングした場合は `"{EXEのパス}"`
  - OFFにされた際は、該当レジストリキーを削除します。

### 2.6. 壁紙の変更と元画像バックアップ
- **バックアップ**:
  - 初回起動時、または元の壁紙が変更されたことを検知した際、Windows設定から現在の壁紙画像のパスを取得（`IDesktopWallpaper::GetWallpaper` から取得可能）し、アプリのバックアップディレクトリにコピーして保存します。
- **壁紙への描画 (Pillow)**:
  - バックアップした元画像をベースに、SQLite に登録されているアクティブな付箋情報を取得します。
  - 各付箋の位置・サイズ・背景色・テキストを Pillow (`ImageDraw`, `ImageFont`) を使用して画像上にレンダリングします。
  - レンダリングした画像を一時保存用ディレクトリに出力し、`IDesktopWallpaper` を使用して壁紙として再設定します。
  - *注意*: フォントには Windows 標準の「メイリオ」や「Yu Gothic」などを使用し、日本語が文字化けしないようにします。

---

## 3. 画面の遷移とUIデザイン

```mermaid
graph TD
    Tray[システムトレイ常駐] -->|右クリック| Menu[コンテキストメニュー]
    Menu -->|設定| SettingsWin[設定画面]
    Menu -->|メモ管理| ManageWin[管理画面]
    Menu -->|終了| Exit[アプリ終了]
    
    Hotkey[Ctrl+Alt+N / ホットキー] --> QuickInput[クイック入力小窓]
    QuickInput -->|Enter (保存)| SaveDB[SQLiteへ保存 & 壁紙再生成]
    
    SettingsWin -->|保存| SaveDB
    ManageWin -->|新規追加/編集/削除| SaveDB
    
    SaveDB -->|表示モード判定| ModeCheck{モードは?}
    ModeCheck -->|壁紙 / ハイブリッド| RenderWallpaper[Pillowで壁紙生成 & 反映]
    ModeCheck -->|オーバーレイ / ハイブリッド| RenderOverlay[PySide6 透過ウィンドウ表示]
```

### 3.1. クイック入力小窓 (Quick Input Window)
- フレームレスの小さなウィンドウを画面中央に表示。
- 背景はダーク調で洗練された半透明（アクリル/グラスモーフィズム風）デザイン。
- 入力欄にフォーカスがあたった状態で起動し、`Enter` で保存、`Esc` で破棄して閉じます。

### 3.2. 管理画面 (Management Window)
- 現在の付箋をリスト表示するダッシュボード。
- 付箋のステータス変更（進行中、完了、アーカイブ）、色変更、タイマー設定、モニターの割り当てを一覧で行えます。
- 「壁紙に適用」ボタンや「オーバーレイ編集モード開始」ボタンを配置。

### 3.3. オーバーレイ編集画面 (Overlay Window)
- 透明な全画面ウィンドウを各モニターに配置。
- `settings.display_mode` が `hybrid` で編集モードに入った時、または `overlay` モードの時に表示。
- 各付箋をウィジェット（`QWidget`）として描画。
- **ドラッグ＆ドロップ移動**: マウスドラッグで位置移動。
- **サイズ変更**: ウィジェットの端をドラッグしてリサイズ。
- **操作**: ダブルクリックでテキスト編集、右クリックメニューで色変更・削除・リマインダー設定。
- 閲覧モードでは `Qt.WindowTransparentForInput` フラグを設定してクリックを透過し、デスクトップ操作の邪魔をしない。編集モードに入るとこのフラグを外してマウス操作を可能にします。

---

## 4. 開発ロードマップ

1. **フェーズ1: データベース・環境構築・壁紙設定のコア機能検証**
   - SQLiteの初期化スクリプト作成。
   - `ctypes` または `pywin32` による Windows 壁紙変更、モニター情報取得の検証。
   - Pillow を使った付箋描画のプロトタイプ作成。
2. **フェーズ2: 基本GUIとホットキーの統合**
   - クイック入力小窓の実装。
   - グローバルホットキーのリスナー実装と、スレッド安全なUI呼び出し。
   - IME入力中の `Enter` 判定の実装。
3. **フェーズ3: オーバーレイ表示とハイブリッドモードの構築**
   - PySide6によるクリック透過・非透過の切り替えが可能なオーバーレイウィンドウの実装。
   - ウィジェットのドラッグ移動・リサイズ機能の実装。
   - ハイブリッドモードのライフサイクル（編集開始 -> オーバーレイ表示 -> 編集終了 -> 壁紙焼き込み -> オーバーレイ非表示）の統合。
4. **フェーズ4: 詳細機能の追加と磨き上げ**
   - トレイアイコンからの通知、`QTimer` によるリマインダー監視。
   - スタートアップ登録機能の実装。
   - 設定画面、管理画面（一覧・編集・削除）の実装。
   - デザインの調整（フォント、配色、アニメーション）。
