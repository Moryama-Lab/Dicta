@echo off
setlocal
cd /d "%~dp0"
title Dicta - 初回セットアップ

echo ========================================================
echo  Dicta の実行に必要なライブラリをインストールしています...
echo ========================================================
echo.

python -m pip install -r "%~dp0requirements.txt"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [エラー] Pythonがインストールされていないか、PATHが通っていません。
    echo Microsoft Store または python.org から Python をインストールしてください。
    echo.
    pause
    exit /b 1
)

echo ========================================================
echo  ライブラリのセットアップが完了しました！
echo  「デスクトップにショートカットを作成.bat」を実行するか、
echo  「Dicta.exe」をダブルクリックして起動してください。
echo ========================================================
echo.
pause
