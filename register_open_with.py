"""
register_open_with.py

Windowsのエクスプローラーで音源ファイル（.mp3, .wav, .m4a, .aac, .flac, .wma, .ogg）を
右クリックした際の「プログラムから開く」の選択肢一覧に Dicta を安全に追加・登録／解除するスクリプト。

【重要】
- ユーザーの「既定のアプリ（デフォルト）」は一切変更しません。
- 管理者権限不要（HKEY_CURRENT_USER\Software\Classes 配下に安全に登録）。
- 登録後、音源ファイルを右クリック ➔「プログラムから開く」➔「Dicta」で直接開けるようになります。
"""
import os
import sys
import winreg
import ctypes

SUPPORTED_EXTS = [".mp3", ".wav", ".m4a", ".aac", ".flac", ".wma", ".ogg", ".opus", ".m4b"]

def get_paths():
    dicta_dir = os.path.abspath(os.path.dirname(__file__))
    dicta_py = os.path.join(dicta_dir, "dicta.py")
    ico_path = os.path.join(dicta_dir, "dicta.ico")
    exe_path = os.path.join(dicta_dir, "Dicta.exe")
    
    # pythonw.exe を優先使用（黒いコンソール窓が出ない）
    py_dir = os.path.dirname(sys.executable)
    pythonw_exe = os.path.join(py_dir, "pythonw.exe")
    if not os.path.exists(pythonw_exe):
        pythonw_exe = sys.executable
    return dicta_dir, dicta_py, ico_path, exe_path, pythonw_exe

def register_open_with():
    dicta_dir, dicta_py, ico_path, exe_path, pythonw_exe = get_paths()
    # Dicta.exe が存在すればそれを最優先（Windows Explorer のプログラムから開くに「Python」ではなく「Dicta」と美しく表示される）
    if os.path.exists(exe_path):
        cmd = f'"{exe_path}" "%1"'
    else:
        cmd = f'"{pythonw_exe}" "{dicta_py}" "%1"'
    
    # アイコンは常に dicta.ico を直接指定（クォートなしがWindowsレジストリ標準・古いキャッシュ問題を100%回避）
    target_icon = f"{ico_path},0" if os.path.exists(ico_path) else f"{exe_path},0"

    try:
        # 1. HKEY_CURRENT_USER\Software\Classes\Applications\Dicta.exe
        app_key_path = r"Software\Classes\Applications\Dicta.exe"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, app_key_path) as app_key:
            winreg.SetValueEx(app_key, "FriendlyAppName", 0, winreg.REG_SZ, "Dicta")
            winreg.SetValueEx(app_key, "ApplicationCompany", 0, winreg.REG_SZ, "Moryama-Lab")
            winreg.SetValueEx(app_key, "", 0, winreg.REG_SZ, "Dicta - 音声文字起こし再生スタジオ")

        # 2. SupportedTypes
        sup_key_path = rf"{app_key_path}\SupportedTypes"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, sup_key_path) as sup_key:
            for ext in SUPPORTED_EXTS:
                winreg.SetValueEx(sup_key, ext, 0, winreg.REG_SZ, "")

        # 3. DefaultIcon
        icon_key_path = rf"{app_key_path}\DefaultIcon"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, icon_key_path) as icon_key:
            winreg.SetValueEx(icon_key, "", 0, winreg.REG_SZ, target_icon)

        # 4. shell\open\command
        shell_key_path = rf"{app_key_path}\shell\open\command"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, shell_key_path) as shell_key:
            winreg.SetValueEx(shell_key, "", 0, winreg.REG_SZ, cmd)

        # 5. 各拡張子の OpenWithList に Dicta.exe を追加
        for ext in SUPPORTED_EXTS:
            owl_path = rf"Software\Classes\{ext}\OpenWithList\Dicta.exe"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, owl_path) as owl_key:
                winreg.SetValueEx(owl_key, "", 0, winreg.REG_SZ, "")

        # 6. デスクトップショートカットも Dicta.exe を指すように更新
        desktop = os.path.join(os.environ["USERPROFILE"], "Desktop")
        shortcut_path = os.path.join(desktop, "Dicta.lnk")
        if os.path.exists(exe_path):
            import subprocess
            vbs_code = f'''Set ws = CreateObject("WScript.Shell")
Set sc = ws.CreateShortcut("{shortcut_path}")
sc.TargetPath = "{exe_path}"
sc.WorkingDirectory = "{dicta_dir}"
sc.IconLocation = "{ico_path},0"
sc.Description = "Dicta - 音声文字起こし再生スタジオ"
sc.WindowStyle = 1
sc.Save
'''
            vbs_file = os.path.join(dicta_dir, "_temp_lnk.vbs")
            with open(vbs_file, "w", encoding="utf-16") as f:
                f.write(vbs_code)
            try:
                subprocess.run(["cscript", "//nologo", vbs_file], check=True)
            finally:
                if os.path.exists(vbs_file):
                    os.remove(vbs_file)

        # シェルキャッシュ更新
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
        print("Success: Windowsの「プログラムから開く」にDictaが正常に登録されました。")
        print(f"  実行コマンド: {cmd}")
        print(f"  対象拡張子: {', '.join(SUPPORTED_EXTS)}")
        print("  ※既定のアプリ（デフォルトプレーヤー）は一切変更されていません。")
        return True
    except Exception as e:
        print(f"Error registering OpenWith: {e}")
        return False

def unregister_open_with():
    try:
        # 1. 各拡張子の OpenWithList\Dicta.exe を削除
        for ext in SUPPORTED_EXTS:
            owl_path = rf"Software\Classes\{ext}\OpenWithList\Dicta.exe"
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, owl_path)
            except FileNotFoundError:
                pass
            except Exception as e:
                print(f"Warning deleting {owl_path}: {e}")

        # 2. Applications\Dicta.exe ツリーを再帰削除
        def delete_key_tree(root, path):
            try:
                with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as k:
                    while True:
                        try:
                            sub = winreg.EnumKey(k, 0)
                            delete_key_tree(root, f"{path}\\{sub}")
                        except OSError:
                            break
                winreg.DeleteKey(root, path)
            except FileNotFoundError:
                pass

        delete_key_tree(winreg.HKEY_CURRENT_USER, r"Software\Classes\Applications\Dicta.exe")

        # シェルキャッシュ更新
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
        print("Success: Windowsの「プログラムから開く」からDictaの登録を解除しました。")
        return True
    except Exception as e:
        print(f"Error unregistering OpenWith: {e}")
        return False

def is_registered():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\Applications\Dicta.exe\shell\open\command"):
            return True
    except FileNotFoundError:
        return False

if __name__ == "__main__":
    action = sys.argv[1].lower() if len(sys.argv) > 1 else "register"
    if action in ("register", "reg", "install"):
        register_open_with()
    elif action in ("unregister", "unreg", "remove", "clean"):
        unregister_open_with()
    elif action in ("status", "check"):
        reg = is_registered()
        print(f"Registered in OpenWith: {reg}")
    else:
        print("Usage: python register_open_with.py [register | unregister | status]")
