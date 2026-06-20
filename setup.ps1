# UTF-8/Shift-JIS encoding safety
$OutputEncoding = [System.Text.Encoding]::GetEncoding(932)

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  壁紙付箋アプリ (Wallpaper Sticky Notes) セットアップ" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# Python check
try {
    $pythonVer = python --version 2>&1
    Write-Host "Python version: $pythonVer"
} catch {
    Write-Error "Python がインストールされていないか、PATH が通っていません。"
    Write-Host "Python 3.8 以上をインストールし、インストール時に「Add Python to PATH」にチェックを入れてください。"
    Read-Host "続行するには Enter キーを押してください..."
    exit 1
}

# Create virtual environment
if (-not (Test-Path ".venv")) {
    Write-Host "仮想環境 (.venv) を作成しています..."
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Error "仮想環境の作成に失敗しました。"
        Read-Host "続行するには Enter キーを押してください..."
        exit 1
    }
} else {
    Write-Host "既に仮想環境 (.venv) が存在します。"
}

# Install dependencies
Write-Host ""
Write-Host "依存ライブラリをインストールしています..."
& ".venv\Scripts\python.exe" -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    Write-Error "pip のアップグレードに失敗しました。"
    Read-Host "続行するには Enter キーを押してください..."
    exit 1
}

& ".venv\Scripts\pip.exe" install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Error "ライブラリのインストールに失敗しました。"
    Read-Host "続行するには Enter キーを押してください..."
    exit 1
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Green
Write-Host "  セットアップが正常に完了しました！" -ForegroundColor Green
Write-Host "  run.bat からアプリを起動できます。" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
Write-Host ""
Read-Host "続行するには Enter キーを押してください..."
