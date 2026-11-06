@echo off
setlocal
cd /d "%~dp0"

set "TARGET_EXE=%~dp0Dicta.exe"
set "TARGET_ICO=%~dp0dicta.ico"
set "SHORTCUT_PATH=%USERPROFILE%\Desktop\Dicta.lnk"

set "VBS=%TEMP%\make_dicta_shortcut.vbs"

echo Set ws = CreateObject("WScript.Shell") > "%VBS%"
echo Set sc = ws.CreateShortcut("%SHORTCUT_PATH%") >> "%VBS%"
echo sc.TargetPath = "%TARGET_EXE%" >> "%VBS%"
echo sc.WorkingDirectory = "%~dp0" >> "%VBS%"
echo sc.IconLocation = "%TARGET_ICO%,0" >> "%VBS%"
echo sc.Description = "Dicta - 音声文字起こし再生スタジオ" >> "%VBS%"
echo sc.WindowStyle = 1 >> "%VBS%"
echo sc.Save >> "%VBS%"

cscript //nologo "%VBS%"
del "%VBS%" >nul 2>&1

echo ========================================================
echo  Dicta のデスクトップショートカットを作成しました！
echo  デスクトップ上の「Dicta」アイコンから起動できます。
echo ========================================================
echo.
pause
