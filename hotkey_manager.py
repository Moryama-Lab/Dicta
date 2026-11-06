"""
Dicta — Global Hotkey Manager (v3: self-healing)

設計方針:
  1. Win32 RegisterHotKey（OS標準・キー入力をブロックしない）を第一経路とする。
  2. 登録に失敗したキー（他アプリや多重起動した Dicta が使用中）は、
     3秒ごとに自動で再登録を試み、その間は GetAsyncKeyState による
     軽量ポーリング（15ms）で代替検知する。→「押しても無反応」を根絶。
  3. バックグラウンドスレッドは Tkinter に一切触れず、queue.Queue 経由で
     メインGUIスレッドへ命令を渡す（Tcl デッドロック防止）。
  4. GetMessage で無期限ブロックせず MsgWaitForMultipleObjects で待機するため、
     停止要求に 15ms 以内で確実に応答する。
"""
import ctypes
from ctypes import wintypes
import threading
import queue
import time

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.PeekMessageW.restype = wintypes.BOOL
user32.MsgWaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD, wintypes.DWORD]
user32.MsgWaitForMultipleObjects.restype = wintypes.DWORD
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short

WM_HOTKEY = 0x0312
PM_REMOVE = 0x0001
QS_ALLINPUT = 0x04FF

# Modifiers
MOD_NONE = 0x0000
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN = 0x10, 0x11, 0x12, 0x5B, 0x5C

# Virtual Keys mapping (あらゆる標準キー・テンキー・記号・特殊キーを網羅)
VK_KEYS = {
    "SPACE": 0x20, "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28,
    "ESC": 0x1B, "ESCAPE": 0x1B, "TAB": 0x09, "ENTER": 0x0D, "RETURN": 0x0D,
    "BACKSPACE": 0x08, "BS": 0x08,
    "HOME": 0x24, "END": 0x23, "PGUP": 0x21, "PGDN": 0x22, "PRIOR": 0x21, "NEXT": 0x22,
    "INS": 0x2D, "INSERT": 0x2D, "DEL": 0x2E, "DELETE": 0x2E,
    "PAUSE": 0x13, "CAPSLOCK": 0x14, "SCROLLLOCK": 0x91, "PRINTSCREEN": 0x2C, "APPS": 0x5D,
    "無変換": 0x1D, "NONCONVERT": 0x1D, "変換": 0x1C, "CONVERT": 0x1C, "かな": 0x15,
    # テンキー
    "NUM0": 0x60, "NUM1": 0x61, "NUM2": 0x62, "NUM3": 0x63, "NUM4": 0x64,
    "NUM5": 0x65, "NUM6": 0x66, "NUM7": 0x67, "NUM8": 0x68, "NUM9": 0x69,
    "NUM*": 0x6A, "NUM+": 0x6B, "NUMPLUS": 0x6B, "NUM-": 0x6D, "NUM.": 0x6E, "NUM/": 0x6F,
    # 記号キー
    "-": 0xBD, "MINUS": 0xBD, "^": 0xDE, "=": 0xBB, "\\": 0xDC, "YEN": 0xDC,
    "@": 0xC0, "[": 0xDB, ";": 0xBB, ":": 0xBA, "]": 0xDD,
    ",": 0xBC, ".": 0xBE, "/": 0xBF, "_": 0xE2,
    # メディアキー等
    "MEDIA_PLAY_PAUSE": 0xB3, "MEDIA_STOP": 0xB2, "MEDIA_NEXT": 0xB0, "MEDIA_PREV": 0xB1,
    "VOLUME_MUTE": 0xAD, "VOLUME_DOWN": 0xAE, "VOLUME_UP": 0xAF,
}
for i in range(1, 25):
    VK_KEYS[f"F{i}"] = 0x70 + (i - 1)
for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
    VK_KEYS[c] = ord(c)

# 逆引きテーブル（表示名の正規化用）
VK_TO_NAME = {
    0x20: "SPACE", 0x25: "LEFT", 0x26: "UP", 0x27: "RIGHT", 0x28: "DOWN",
    0x1B: "ESC", 0x09: "TAB", 0x0D: "ENTER", 0x08: "BACKSPACE",
    0x24: "HOME", 0x23: "END", 0x21: "PGUP", 0x22: "PGDN",
    0x2D: "INS", 0x2E: "DEL", 0x13: "PAUSE", 0x14: "CAPSLOCK",
    0x91: "SCROLLLOCK", 0x2C: "PRINTSCREEN", 0x5D: "APPS",
    0x1D: "無変換", 0x1C: "変換", 0x15: "かな",
    0x60: "NUM0", 0x61: "NUM1", 0x62: "NUM2", 0x63: "NUM3", 0x64: "NUM4",
    0x65: "NUM5", 0x66: "NUM6", 0x67: "NUM7", 0x68: "NUM8", 0x69: "NUM9",
    0x6A: "NUM*", 0x6B: "NUM+", 0x6D: "NUM-", 0x6E: "NUM.", 0x6F: "NUM/",
    0xBD: "-", 0xDE: "^", 0xDC: "\\", 0xC0: "@", 0xDB: "[",
    0xBB: ";", 0xBA: ":", 0xDD: "]", 0xBC: ",", 0xBE: ".", 0xBF: "/", 0xE2: "_",
    0xB3: "MEDIA_PLAY_PAUSE", 0xB2: "MEDIA_STOP", 0xB0: "MEDIA_NEXT", 0xB1: "MEDIA_PREV",
    0xAD: "VOLUME_MUTE", 0xAE: "VOLUME_DOWN", 0xAF: "VOLUME_UP",
}
for i in range(1, 25):
    VK_TO_NAME[0x70 + (i - 1)] = f"F{i}"
for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
    VK_TO_NAME[ord(c)] = c


def parse_hotkey_string(hk_str):
    """
    'Shift+Ctrl+Alt+W' / 'Ctrl+Space' / 'F4' 等あらゆるキー表記を解析する。
    Returns: (mods, vk, display_str) or (None, None, '')
    """
    if not hk_str or hk_str.strip() == "":
        return None, None, ""

    safe_str = hk_str.replace("NUM+", "NUMPLUS")
    parts = [p.strip().upper() for p in safe_str.replace(" ", "").split("+") if p.strip()]
    if not parts:
        return None, None, ""

    ctrl = alt = shift = win = False
    key = None
    for p in parts:
        if p in ("CTRL", "CONTROL"):
            ctrl = True
        elif p == "ALT":
            alt = True
        elif p == "SHIFT":
            shift = True
        elif p in ("WIN", "WINDOWS"):
            win = True
        else:
            key = p

    vk = None
    disp_key = None
    if key in VK_KEYS:
        vk = VK_KEYS[key]
        disp_key = VK_TO_NAME.get(vk, key)
    elif key and key.startswith("VK") and key[2:].isdigit():
        vk = int(key[2:])
        disp_key = VK_TO_NAME.get(vk, key)
    elif key is None:
        # 修飾キー単体または修飾キー同士の組み合わせ（例: Shift / Shift+Ctrl 等）にも対応
        if alt:
            vk, disp_key, alt = VK_MENU, "Alt", False
        elif ctrl:
            vk, disp_key, ctrl = VK_CONTROL, "Ctrl", False
        elif shift:
            vk, disp_key, shift = VK_SHIFT, "Shift", False
        elif win:
            vk, disp_key, win = VK_LWIN, "Win", False

    if vk is None:
        return None, None, ""

    mods = MOD_NOREPEAT
    if ctrl:
        mods |= MOD_CONTROL
    if alt:
        mods |= MOD_ALT
    if shift:
        mods |= MOD_SHIFT
    if win:
        mods |= MOD_WIN

    tokens = []
    if shift:
        tokens.append("Shift")
    if ctrl:
        tokens.append("Ctrl")
    if alt:
        tokens.append("Alt")
    if win:
        tokens.append("Win")
    tokens.append(disp_key)
    return mods, vk, " + ".join(tokens)


def _key_down(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


class HotkeyManager:
    def __init__(self, debounce_ms=45, retry_sec=3.0, poll_ms=15):
        self.hotkeys = {}            # id -> (mods, vk, action_name, canon)
        self.command_queue = queue.Queue(maxsize=64)
        self.debounce_sec = debounce_ms / 1000.0
        self.retry_sec = retry_sec
        self.poll_ms = poll_ms
        self._last_fire_time = {}
        self.thread = None
        self.running = False
        self.lock = threading.Lock()
        self.registered_ids = set()
        self.fallback_ids = set()    # 登録できず代替ポーリング中のID
        self._fallback_prev = {}     # id -> 前回押下状態（エッジ検出用）

    # ------------------------------------------------------------------
    def set_hotkeys(self, hotkey_dict):
        was_running = self.running
        if was_running:
            self.stop()
        with self.lock:
            self.hotkeys.clear()
            next_id = 1
            for action_name, key_str in hotkey_dict.items():
                mods, vk, canon = parse_hotkey_string(key_str)
                if vk is not None:
                    self.hotkeys[next_id] = (mods, vk, action_name, canon)
                    next_id += 1
        if was_running:
            self.start()

    def poll_action(self):
        try:
            return self.command_queue.get_nowait()
        except queue.Empty:
            return None

    def get_status(self):
        """Returns (ok_list, fallback_list) of (action_name, canon)."""
        with self.lock:
            ok = [(self.hotkeys[i][2], self.hotkeys[i][3]) for i in self.registered_ids if i in self.hotkeys]
            fb = [(self.hotkeys[i][2], self.hotkeys[i][3]) for i in self.fallback_ids if i in self.hotkeys]
        return ok, fb

    # ------------------------------------------------------------------
    def start(self):
        if self.running:
            return
        self.running = True
        started = threading.Event()
        self.thread = threading.Thread(target=self._loop, args=(started,), daemon=True, name="DictaHotkeys")
        self.thread.start()
        started.wait(timeout=1.5)

    def stop(self):
        if not self.running:
            return
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=0.5)
        self.thread = None

    # ------------------------------------------------------------------
    def _emit(self, action_name):
        now = time.monotonic()
        if (now - self._last_fire_time.get(action_name, 0.0)) < self.debounce_sec:
            return
        self._last_fire_time[action_name] = now
        try:
            self.command_queue.put_nowait(action_name)
        except queue.Full:
            pass

    def _try_register_pending(self):
        with self.lock:
            for hk_id, (mods, vk, _name, _canon) in self.hotkeys.items():
                if hk_id in self.registered_ids:
                    continue
                if user32.RegisterHotKey(None, hk_id, mods, vk):
                    self.registered_ids.add(hk_id)
                    self.fallback_ids.discard(hk_id)
                else:
                    self.fallback_ids.add(hk_id)

    def _poll_fallback(self):
        if not self.fallback_ids:
            return
        with self.lock:
            items = [(i, self.hotkeys[i]) for i in self.fallback_ids if i in self.hotkeys]
        if not items:
            return
        shift = _key_down(VK_SHIFT)
        ctrl = _key_down(VK_CONTROL)
        alt = _key_down(VK_MENU)
        win = _key_down(VK_LWIN) or _key_down(VK_RWIN)
        for hk_id, (mods, vk, name, _canon) in items:
            want_shift = bool(mods & MOD_SHIFT)
            want_ctrl = bool(mods & MOD_CONTROL)
            want_alt = bool(mods & MOD_ALT)
            want_win = bool(mods & MOD_WIN)
            pressed = (
                _key_down(vk)
                and shift == want_shift and ctrl == want_ctrl
                and alt == want_alt and win == want_win
            )
            prev = self._fallback_prev.get(hk_id, False)
            if pressed and not prev:
                self._emit(name)
            self._fallback_prev[hk_id] = pressed

    def _loop(self, started):
        self.registered_ids = set()
        self.fallback_ids = set()
        self._fallback_prev = {}
        self._try_register_pending()
        started.set()

        msg = wintypes.MSG()
        last_retry = time.monotonic()
        try:
            while self.running:
                user32.MsgWaitForMultipleObjects(0, None, False, self.poll_ms, QS_ALLINPUT)
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                    if msg.message == WM_HOTKEY:
                        hk_id = int(msg.wParam)
                        with self.lock:
                            entry = self.hotkeys.get(hk_id)
                        if entry:
                            self._emit(entry[2])
                self._poll_fallback()
                now = time.monotonic()
                if self.fallback_ids and (now - last_retry) >= self.retry_sec:
                    last_retry = now
                    self._try_register_pending()
        finally:
            for hk_id in list(self.registered_ids):
                try:
                    user32.UnregisterHotKey(None, hk_id)
                except Exception:
                    pass
            self.registered_ids.clear()
            self.fallback_ids.clear()
