@echo off
chcp 65001 > nul
echo ==================================================
echo   壁紙付箋アプリ (Wallpaper Sticky Notes) セットアップ
echo ==================================================
echo.

:: Python の存在チェック
python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo [エラー] Python がインストールされていないか、PATH が通っていません。
    echo Python 3.8 以上をインストールし、インストール時に「Add Python to PATH」にチェックを入れてください。
    pause
    exit /b
)

:: 仮想環境の作成
if not exist ".venv" (
    echo 仮想環境 (.venv) を作成しています...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [エラー] 仮想環境の作成に失敗しました。
        pause
        exit /b
    )
) else (
    echo すでに仮想環境 (.venv) が存在します。
)

:: 依存ライブラリのインストール
echo.
echo 依存ライブラリをインストールしています...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

if %errorlevel% neq 0 (
    echo.
    echo [エラー] ライブラリのインストール中にエラーが発生しました。
    pause
    exit /b
)

echo.
echo ==================================================
echo   セットアップが正常に完了しました！
echo   run.bat からアプリを起動できます。
echo ==================================================
echo.
pause
