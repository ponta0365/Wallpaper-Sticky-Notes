@echo off
:: コンダや別の仮想環境のアクティベートに干渉しないよう安全に仮想環境の pythonw.exe を叩く
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" -m src.app
) else (
    echo [エラー] セットアップが完了していません。先に setup.bat を実行してください。
    pause
)
