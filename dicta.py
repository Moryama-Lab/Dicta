"""
Dicta（ディクタ）— 文字起こし再生スタジオ  v3.2

Okoshiyasu2 の全機能を上位互換で再実装した、64bit・耐フリーズ設計の文字起こし専用プレーヤー。
  - サクサク高速起動 & 起動時スムーズ最大化（チラつきゼロ）
  - 極太・高品位アンチエイリアス進捗バー（Pillow 4xスーパーサンプリング超滑らか円球ツマミ）
  - 進捗バー直結のしおり機能（黄色縦線のみ・クリックでジャンプ・右クリックで削除）
  - 時間コピー ＆ 区間コピー（A点〜B点を '01:30:27,175 --> 01:30:37,420' でワンクリックコピー）
  - 操作ボタンのサイズ均一化（最初から／しおり追加／しおり全消去）＆ 直感的な色の区別
  - ショートカット設定の「キーボード直接入力キャプチャ」と「選択式」の完全両立
  - ウィンドウ左上にGitコミット日付＆バージョンを自動参照表示（ウィンドウ上部表記の洗練）
  - 再生速度レンジ拡張（0.20倍〜3.00倍）
  - 音量コントロールを右下（イコライザー下）に自然配置
  - 日本語ユニバーサルデザインフォント（BIZ UDPゴシック / BIZ UDゴシック）
  - タイムコード直接クリック編集ジャンプ
"""
import os
import sys
import math
import json
import time
import ctypes
import winsound
import subprocess
from datetime import datetime
from ctypes import wintypes
from collections import deque
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox
from PIL import Image, ImageDraw, ImageTk
import customtkinter as ctk

# 1. Windows OSレベルで System DPI Aware (1) を適用（Orbit互換：動的再計算・チラつき停止）
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

from customtkinter.windows.widgets.scaling import ScalingTracker
ScalingTracker.get_window_dpi_scaling = lambda *args, **kwargs: 1.25
ScalingTracker.check_dpi_scaling = lambda *args, **kwargs: None

from bass_engine import BassAudioEngine
from hotkey_manager import HotkeyManager, parse_hotkey_string

user32 = ctypes.windll.user32

def get_current_modifiers():
    """Windows APIから現在のShift, Ctrl, Altキー押下状態を100%正確に取得"""
    shift = bool(user32.GetAsyncKeyState(0x10) & 0x8000)
    ctrl = bool(user32.GetAsyncKeyState(0x11) & 0x8000)
    alt = bool(user32.GetAsyncKeyState(0x12) & 0x8000)
    return shift, ctrl, alt

# Optional Drag-and-Drop support via tkinterdnd2
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except Exception:
    HAS_DND = False

# Ensure Windows 11 Taskbar displays Dicta's own icon instead of generic Python icon
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MoriyamaLab.Dicta.TranscriptionEngine.3.2")
except Exception:
    pass

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(APP_DIR, "config.json")
CONFIG_DEFAULT_FILE = os.path.join(APP_DIR, "config.default.json")
ICON_FILE = os.path.join(APP_DIR, "dicta.ico")
LOGO_FILE = os.path.join(APP_DIR, "dicta_logo.png")
CONFIG_VERSION = 3


def get_git_version() -> str:
    """Gitコミット履歴から最新のコミット日付と短縮コミットハッシュを自動取得（Orbit互換）"""
    try:
        cmd = ["git", "log", "-1", "--format=%ad (commit %h)", "--date=format:%Y.%m.%d"]
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        out = subprocess.check_output(cmd, cwd=APP_DIR, stderr=subprocess.DEVNULL, creationflags=creationflags)
        ver = out.decode("utf-8", errors="ignore").strip()
        if ver:
            return ver
    except Exception:
        pass
    return datetime.now().strftime("%Y.%m.%d")


# Universal Design High-Contrast Color Palette (WCAG AAA Compliant Deep Navy & Neon Cyan)
COLOR_BG_MAIN = "#050912"
COLOR_BG_CARD = "#0C1526"
COLOR_BG_COUNTER = "#02050A"
COLOR_BG_BUTTON = "#16243D"
COLOR_BG_BUTTON_HOVER = "#233B61"
COLOR_BORDER_SUBTLE = "#2A4570"
COLOR_BORDER_GLOW = "#00E5FF"
COLOR_NEON_CYAN = "#00F0FF"
COLOR_CYAN_MID = "#0284C7"
COLOR_CYAN_DARK = "#0369A1"
COLOR_PLAY_ACTIVE = "#00E699"
COLOR_PAUSE_ACTIVE = "#FFB300"
COLOR_ISOLATOR_ON = "#FFEA00"
COLOR_BOOKMARK = "#FFC820"         # 鮮やかなゴールド・イエロー（しおり縦線）
COLOR_REPEAT_RED = "#FF3355"       # 高コントラスト鮮烈レッド（区間リピート用）
COLOR_TEXT_MAIN = "#FFFFFF"
COLOR_TEXT_SUB = "#C2D3EA"
COLOR_TEXT_DARK = "#020810"

# Resolved at runtime
FONT_UI = "Meiryo UI"
FONT_MONO = "Consolas"

DEFAULT_CONFIG = {
    "config_version": CONFIG_VERSION,
    "theme": "dark",
    "always_on_top": False,
    "start_maximized": True,
    "use_ssd_cache": True,
    "loop_beep": False,
    "analyzer_mode": "spectrum_wave",
    "counter_format": "{time}",
    "counter_precision": "sec",
    "volume": 0.9,
    "speed": 1.0,
    "pitch": 0.0,
    "speed_step": 0.05,
    "auto_rewind_sec": 1.0,
    "jump_rewind_sec": 5.0,
    "jump_forward_sec": 5.0,
    "resume_last_file": True,
    "last_file": "",
    "last_position": 0.0,
    "eq_preset": "クリアボイス（会話強調）",
    "eq_gains": [-4.0, -1.0, 2.0, 6.0, 3.0, -2.0],
    "bookmarks_dict": {},          # file_path -> [sec1, sec2, sec3, ...]
    "hotkeys": {
        "play_pause": "Shift+Ctrl+Alt+W",
        "forward": "Shift+Ctrl+Alt+E",
        "rewind": "Shift+Ctrl+Alt+Q",
        "speed_reset": "Shift+Ctrl+Alt+Z",
        "speed_up": "Shift+Ctrl+Alt+X",
        "speed_down": "Shift+Ctrl+Alt+A",
        "speed_05": "",
        "speed_15": "",
        "speed_20": "",
        "counter_copy": "Shift+Ctrl+Alt+C",
        "range_copy": "",
        "counter_jump": "Shift+Ctrl+Alt+J",
        "loop_a": "Shift+Ctrl+Alt+1",
        "loop_b": "Shift+Ctrl+Alt+2",
        "reset_head": "Shift+Ctrl+Alt+R",
        "bookmark_add": "Shift+Ctrl+Alt+B",
        "volume_up": "Shift+Ctrl+Alt+UP",
        "volume_down": "Shift+Ctrl+Alt+DOWN",
        "toggle_mini": "Shift+Ctrl+Alt+M",
    }
}

HOTKEY_NAMES = {
    "play_pause": "再生 / 一時停止（自動巻き戻し）",
    "forward": "早送り",
    "rewind": "巻き戻し",
    "speed_reset": "速度 1.0倍（等倍に戻す）",
    "speed_up": "速度変更＋（速く）",
    "speed_down": "速度変更－（遅く）",
    "speed_05": "速度 0.5倍",
    "speed_15": "速度 1.5倍",
    "speed_20": "速度 2.0倍",
    "counter_copy": "時間コピー（現在位置）",
    "range_copy": "区間コピー（A点 --> B点）",
    "counter_jump": "時間を直接入力してジャンプ",
    "loop_a": "区間リピート A点 設定／解除",
    "loop_b": "区間リピート B点 設定／解除",
    "reset_head": "最初から（A点設定時はA点から）",
    "bookmark_add": "現在位置にしおりを追加",
    "volume_up": "音量を上げる",
    "volume_down": "音量を下げる",
    "toggle_mini": "ミニモード切替",
}

EQ_PRESETS = {
    "フラット（標準）": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    "クリアボイス（会話強調）": [-4.0, -1.0, 2.0, 6.0, 3.0, -2.0],
    "低音ノイズカット（空調・振動）": [-12.0, -8.0, 0.0, 3.0, 2.0, 0.0],
    "高音クリア（子音聞き取り）": [-2.0, 0.0, 1.0, 4.0, 7.0, 4.0]
}
EQ_FREQ_LABELS = ["120Hz", "200Hz", "400Hz", "1.2k", "4k", "10k"]

COUNTER_FORMATS = {
    "01:24:18（括弧なし）": "{time}",
    "[01:24:18]": "[{time}]",
    "(01:24:18)": "({time})",
    "#01:24:18#": "#{time}#",
}

ISO_PRESETS = [
    ("通常（全域）", False, 1200, 1.2),
    ("会話のみ", True, 1000, 1.8),
    ("子音・小声", True, 2600, 1.3),
    ("低い声のみ", True, 420, 1.3),
    ("高めの声のみ", True, 1500, 1.4),
    ("ピンポイント", True, 1000, 0.5),
]


# =============================================================================
# Helpers
# =============================================================================
def _split_ms(seconds):
    total_ms = int(round(max(0.0, seconds) * 1000))
    h, rem = divmod(total_ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return h, m, s, ms


def format_time(seconds, include_ms=True):
    h, m, s, ms = _split_ms(seconds)
    if include_ms:
        return f"{h:02d}:{m:02d}:{s:02d}.{ms // 100}"
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_time_copy(seconds, precision="sec"):
    h, m, s, ms = _split_ms(seconds)
    if precision == "ms":
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    return f"{h:02d}:{m:02d}:{s:02d}"


def parse_time_input(text):
    text = text.strip().replace("：", ":").replace("，", ",").replace("．", ".").replace(",", ".")
    text = text.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if not text:
        return None
    if ":" in text:
        parts = text.split(":")
        try:
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            if len(parts) == 2:
                return int(parts[0]) * 60 + float(parts[1])
        except ValueError:
            return None
        return None
    whole, _, frac = text.partition(".")
    if not whole.isdigit() or (frac and not frac.isdigit()):
        return None
    f = float("0." + frac) if frac else 0.0
    if len(whole) <= 2:
        return int(whole) + f
    if len(whole) in (3, 4):
        return int(whole[:-2]) * 60 + int(whole[-2:]) + f
    if len(whole) in (5, 6):
        return int(whole[:-4]) * 3600 + int(whole[-4:-2]) * 60 + int(whole[-2:]) + f
    return None


def intensity_to_hex(val):
    v = max(0.0, min(1.0, val))
    if v < 0.25:
        t = v / 0.25
        r, g, b = int(6 * (1 - t)), int(14 * (1 - t) + 90 * t), int(30 * (1 - t) + 160 * t)
    elif v < 0.6:
        t = (v - 0.25) / 0.35
        r, g, b = 0, int(90 * (1 - t) + 240 * t), int(160 * (1 - t) + 255 * t)
    elif v < 0.85:
        t = (v - 0.6) / 0.25
        r, g, b = int(255 * t), int(240 * (1 - t) + 230 * t), int(255 * (1 - t) + 40 * t)
    else:
        t = (v - 0.85) / 0.15
        r, g, b = 255, int(230 * (1 - t) + 255 * t), int(40 * (1 - t) + 255 * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def resolve_fonts():
    global FONT_UI, FONT_MONO
    try:
        fams = set(tkfont.families())
    except Exception:
        fams = set()
    for cand in ("BIZ UDPゴシック", "BIZ UDPGothic", "Yu Gothic UI", "Meiryo UI"):
        if cand in fams:
            FONT_UI = cand
            break
    for cand in ("BIZ UDゴシック", "BIZ UDGothic", "Consolas"):
        if cand in fams:
            FONT_MONO = cand
            break


def make_smooth_circle_image(radius, border_width, fill_color, border_color):
    """
    Pillowによる4倍スーパーサンプリング（LANCZOS縮小）で、
    Canvas特有のエッジのジャギー・ガビガビ感を100%解消した超高品位アンチエイリアス円球スプライトを生成。
    """
    scale = 4
    size = radius * 2 * scale
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # 外枠
    draw.ellipse([0, 0, size - 1, size - 1], fill=border_color)
    # 内側
    bw = border_width * scale
    draw.ellipse([bw, bw, size - 1 - bw, size - 1 - bw], fill=fill_color)
    # Lanczosダウンサンプリング
    img_smooth = img.resize((radius * 2, radius * 2), Image.Resampling.LANCZOS)
    return ImageTk.PhotoImage(img_smooth)


# =============================================================================
# Single-instance guard (newest launch takes over gracefully)
# =============================================================================
# =============================================================================
# Ultra-Thick High-Visibility SeekBar with Direct Bookmark & Loop Rendering
# =============================================================================
class MainSeekBar(tk.Canvas):
    """
    最も太く見やすいメイン進捗バー。
      - 極太トラック（太さ15px）
      - Pillowアンチエイリアスによる滑らかでクリスプなツマミ（ガビガビ解消）
      - 区間リピートの赤色半透明帯＆A/B赤線
      - 直感的なしおり（黄色い縦線のみ）、クリックでジャンプ、右クリックで削除
      - Shiftドラッグで10倍微調整、ホイールで1秒（Shiftホイールで5秒）
      - マウスホバーで現在位置の時間プレビュー
    """
    def __init__(self, master, scale, bg, on_seek, on_preview, on_bookmark_delete=None, height=72):
        self.s = scale
        self.h = int(height * scale)
        super().__init__(master, height=self.h, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        self.on_seek = on_seek
        self.on_preview = on_preview
        self.on_bookmark_delete = on_bookmark_delete

        self.duration = 0.0
        self.position = 0.0
        self.dragging = False
        self.hover_x = None
        self._fine = False
        self._anchor_x = 0
        self._anchor_sec = 0.0
        self.loop_a = None
        self.loop_b = None
        self.bookmarks = []

        self.pad = int(20 * scale)
        self.track_y = int(self.h * 0.62)
        self.track_th = max(10, int(15 * scale))
        self.r_norm = max(9, int(11 * scale))
        self.r_big = max(12, int(14 * scale))
        self.tip_y = int(self.h * 0.22)
        self.font_tip = (FONT_MONO, 12, "bold")
        self.font_mark = (FONT_UI, 11, "bold")

        # Static track elements
        self.it_track = self.create_line(0, 0, 0, 0, fill="#12233D", width=self.track_th, capstyle="round")
        self.it_loop_rect = self.create_rectangle(0, 0, 0, 0, fill="#5C0D1C", outline="", state="hidden")
        self.it_prog = self.create_line(0, 0, 0, 0, fill=COLOR_NEON_CYAN, width=self.track_th, capstyle="round")

        # Pillow 4xスーパーサンプリングによる完全アンチエイリアスThumb画像
        self.img_thumb_norm = make_smooth_circle_image(self.r_norm, max(2, int(2.5 * scale)), "#FFFFFF", COLOR_NEON_CYAN)
        self.img_thumb_big = make_smooth_circle_image(self.r_big, max(3, int(3.5 * scale)), "#FFFFFF", COLOR_ISOLATOR_ON)
        self.it_thumb = self.create_image(0, 0, image=self.img_thumb_norm)

        # Dynamic markers
        self.marker_items = []

        # Tooltip
        self.it_tip_bg = self.create_rectangle(0, 0, 0, 0, fill="#081426", outline=COLOR_NEON_CYAN, state="hidden")
        self.it_tip = self.create_text(0, 0, text="", fill="#FFFFFF", font=self.font_tip, state="hidden")

        self.bind("<Configure>", lambda e: self._layout())
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<ButtonPress-3>", self._on_right_click)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", self._on_leave)
        self.bind("<MouseWheel>", self._on_wheel)

    def _usable(self):
        w = max(2 * self.pad + 10, self.winfo_width())
        return self.pad, w - self.pad

    def sec_to_x(self, sec):
        x0, x1 = self._usable()
        if self.duration <= 0:
            return x0
        return x0 + (max(0.0, min(self.duration, sec)) / self.duration) * (x1 - x0)

    def x_to_sec(self, x):
        x0, x1 = self._usable()
        frac = max(0.0, min(1.0, (x - x0) / max(1, (x1 - x0))))
        return frac * self.duration

    def set_duration(self, dur):
        self.duration = max(0.0, float(dur))
        self._layout()

    def set_position(self, sec):
        if self.dragging:
            return
        self.position = sec
        self._draw_dynamic()

    def set_markers(self, loop_a, loop_b, bookmarks):
        self.loop_a = loop_a
        self.loop_b = loop_b
        self.bookmarks = sorted(list(bookmarks))
        self._draw_markers()

    def _layout(self):
        x0, x1 = self._usable()
        self.coords(self.it_track, x0, self.track_y, x1, self.track_y)
        self._draw_markers()
        self._draw_dynamic()

    def _draw_markers(self):
        for it in self.marker_items:
            self.delete(it)
        self.marker_items = []
        if self.duration <= 0:
            self.itemconfigure(self.it_loop_rect, state="hidden")
            return

        ty, th = self.track_y, self.track_th

        # 1. 区間リピート（赤色帯 ＆ A/B線）
        if self.loop_a is not None and self.loop_b is not None:
            xa, xb = self.sec_to_x(self.loop_a), self.sec_to_x(self.loop_b)
            self.coords(self.it_loop_rect, xa, ty - th // 2 - 2, xb, ty + th // 2 + 2)
            self.itemconfigure(self.it_loop_rect, state="normal")
        else:
            self.itemconfigure(self.it_loop_rect, state="hidden")

        for sec, label in ((self.loop_a, "A"), (self.loop_b, "B")):
            if sec is not None:
                x = self.sec_to_x(sec)
                self.marker_items.append(self.create_line(x, ty - th - 6, x, ty + th + 6, fill=COLOR_REPEAT_RED, width=max(3, int(3 * self.s))))
                self.marker_items.append(self.create_text(x, ty - th - 12, text=label, fill=COLOR_REPEAT_RED, font=self.font_mark))

        # 2. しおり（黄色い縦線のみ・星マーク削除）
        for bm_sec in self.bookmarks:
            x = self.sec_to_x(bm_sec)
            self.marker_items.append(self.create_line(x, ty - th - 6, x, ty + th + 6, fill=COLOR_BOOKMARK, width=max(2, int(2.5 * self.s))))

        for it in (self.it_prog, self.it_thumb, self.it_tip_bg, self.it_tip):
            self.tag_raise(it)

    def _draw_dynamic(self):
        x0, _ = self._usable()
        xp = self.sec_to_x(self.position)
        self.coords(self.it_prog, x0, self.track_y, max(x0, xp), self.track_y)

        # アンチエイリアス画像の切替と配置
        img = self.img_thumb_big if (self.dragging or self.hover_x is not None) else self.img_thumb_norm
        self.itemconfigure(self.it_thumb, image=img)
        self.coords(self.it_thumb, xp, self.track_y)

        if self.dragging:
            prefix = "微調整: " if self._fine else ""
            self._show_tip(xp, prefix + format_time(self.position, include_ms=True))
        elif self.hover_x is not None and self.duration > 0:
            h_sec = self.x_to_sec(self.hover_x)
            nearest_bm = self._find_nearest_bookmark(self.hover_x, dist_px=10)
            if nearest_bm is not None:
                self._show_tip(self.hover_x, f"しおり {format_time(nearest_bm, False)}（右クリックで削除）")
            else:
                self._show_tip(self.hover_x, format_time(h_sec, include_ms=False))
        else:
            self.itemconfigure(self.it_tip, state="hidden")
            self.itemconfigure(self.it_tip_bg, state="hidden")

    def _find_nearest_bookmark(self, x, dist_px=10):
        if not self.bookmarks or self.duration <= 0:
            return None
        for bm in self.bookmarks:
            bx = self.sec_to_x(bm)
            if abs(bx - x) <= dist_px:
                return bm
        return None

    def _show_tip(self, x, text):
        w = self.winfo_width()
        self.itemconfigure(self.it_tip, text=text, state="normal")
        bbox = self.bbox(self.it_tip)
        tw = (bbox[2] - bbox[0]) if bbox else 80
        cx = max(tw // 2 + 10, min(w - tw // 2 - 10, x))
        self.coords(self.it_tip, cx, self.tip_y)
        bbox = self.bbox(self.it_tip)
        if bbox:
            self.coords(self.it_tip_bg, bbox[0] - 8, bbox[1] - 3, bbox[2] + 8, bbox[3] + 3)
            self.itemconfigure(self.it_tip_bg, state="normal")

    def _on_press(self, e):
        if self.duration <= 0:
            return
        near_bm = self._find_nearest_bookmark(e.x, dist_px=12)
        if near_bm is not None:
            self.position = near_bm
            self.on_seek(self.position)
            self._draw_dynamic()
            return

        self.dragging = True
        self._fine = bool(e.state & 0x0001)
        self.position = self.x_to_sec(e.x)
        self._anchor_x, self._anchor_sec = e.x, self.position
        self.on_preview(self.position)
        self._draw_dynamic()

    def _on_drag(self, e):
        if not self.dragging:
            return
        fine = bool(e.state & 0x0001)
        if fine != self._fine:
            self._fine = fine
            self._anchor_x, self._anchor_sec = e.x, self.position
        if self._fine:
            x0, x1 = self._usable()
            delta = (e.x - self._anchor_x) / max(1, (x1 - x0)) * self.duration * 0.1
            self.position = max(0.0, min(self.duration, self._anchor_sec + delta))
        else:
            self.position = self.x_to_sec(e.x)
        self.on_preview(self.position)
        self._draw_dynamic()

    def _on_release(self, e):
        if not self.dragging:
            return
        self.dragging = False
        self.on_seek(self.position)
        self.on_preview(None)
        self._draw_dynamic()

    def _on_right_click(self, e):
        near_bm = self._find_nearest_bookmark(e.x, dist_px=14)
        if near_bm is not None and self.on_bookmark_delete:
            self.on_bookmark_delete(near_bm)

    def _on_motion(self, e):
        self.hover_x = e.x
        if not self.dragging:
            self._draw_dynamic()

    def _on_leave(self, e):
        self.hover_x = None
        if not self.dragging:
            self._draw_dynamic()

    def _on_wheel(self, e):
        if self.duration <= 0:
            return
        step = 5.0 if (e.state & 0x0001) else 1.0
        target = self.position + (step if e.delta > 0 else -step)
        self.position = max(0.0, min(self.duration, target))
        self.on_seek(self.position)
        self._draw_dynamic()


# =============================================================================
# Main Application
# =============================================================================
class DictaApp(ctk.CTk):
    def __init__(self, **kwargs):
        super().__init__()
        resolve_fonts()
        self._font_cache = {}
        self.version_str = get_git_version()

        self.load_config()
        ctk.set_appearance_mode("dark")
        self.configure(fg_color=COLOR_BG_MAIN)

        self.ui_scale = 1.25

        # ウィンドウ左上（タイトルバー）：バージョンとコミット情報のみ（文字起こし再生スタジオは不要）
        self.title(f"Dicta {self.version_str}")
        self.geometry("1380x950")
        self.minsize(1080, 760)

        if os.path.exists(ICON_FILE):
            try:
                self.iconbitmap(ICON_FILE)
            except Exception:
                pass

        if HAS_DND:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
                self.drop_target_register(DND_FILES)
                self.dnd_bind("<<Drop>>", self.on_file_drop)
            except Exception:
                pass

        # Audio engine
        self.engine = BassAudioEngine(APP_DIR)
        self.engine.set_volume(self.config.get("volume", 0.9))

        self.loop_a = None
        self.loop_b = None
        self.is_seeking = False
        self.is_mini_mode = False
        self.editing_time = None
        self._last_autosave_time = time.monotonic()
        self._status_restore_job = None
        self._analyzer_idle_drawn = False
        self.spec_history = deque(maxlen=42)

        step = lambda: self.config.get("speed_step", 0.05)
        self.action_dispatch = {
            "play_pause": self.action_play_pause,
            "forward": self.action_forward,
            "rewind": self.action_rewind,
            "speed_reset": lambda: self.set_speed(1.0),
            "speed_up": lambda: self.adjust_speed(step()),
            "speed_down": lambda: self.adjust_speed(-step()),
            "speed_05": lambda: self.set_speed(0.5),
            "speed_15": lambda: self.set_speed(1.5),
            "speed_20": lambda: self.set_speed(2.0),
            "counter_copy": self.action_counter_copy,
            "range_copy": self.action_range_copy,
            "counter_jump": self.action_counter_jump,
            "loop_a": self.action_toggle_loop_a,
            "loop_b": self.action_toggle_loop_b,
            "reset_head": self.action_stop,
            "bookmark_add": self.action_bookmark_add,
            "volume_up": lambda: self.adjust_volume(0.02),
            "volume_down": lambda: self.adjust_volume(-0.02),
            "toggle_mini": self.toggle_mini_mode,
        }

        # UIの構築
        self.init_ui()

        # 最大化表示
        if self.config.get("start_maximized", True):
            try:
                self.state("zoomed")
            except Exception:
                pass

        self.apply_always_on_top()
        self.apply_eq_gains(self.config.get("eq_gains", [-4.0, -1.0, 2.0, 6.0, 3.0, -2.0]))
        self.set_speed(self.config.get("speed", 1.0))
        self.set_pitch(self.config.get("pitch", 0.0))
        self.set_volume_ui(self.config.get("volume", 0.9))

        # Hotkeys
        self.hotkey_mgr = HotkeyManager(debounce_ms=45)
        self.setup_hotkeys()
        self.hotkey_mgr.start()
        self.after(800, self.report_hotkey_status)

        self.after(40, self.update_playback_timer)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # ファイル復元
        if self.config.get("resume_last_file") and self.config.get("last_file"):
            last_f = self.config.get("last_file")
            if os.path.exists(last_f):
                self.after(150, lambda: self.resume_file(last_f, self.config.get("last_position", 0.0)))

    # -------------------------------------------------------------------------
    # Style helpers
    # -------------------------------------------------------------------------
    def F(self, size, bold=True, mono=False):
        key = (size, bold, mono)
        f = self._font_cache.get(key)
        if f is None:
            f = ctk.CTkFont(family=FONT_MONO if mono else FONT_UI, size=size, weight="bold" if bold else "normal")
            self._font_cache[key] = f
        return f

    def card(self, parent, glow=False, bg=COLOR_BG_CARD):
        return ctk.CTkFrame(parent, corner_radius=14, fg_color=bg, border_width=2,
                            border_color=COLOR_BORDER_GLOW if glow else COLOR_BORDER_SUBTLE)

    BTN_STYLES = {
        "normal": dict(fg_color=COLOR_BG_BUTTON, hover_color=COLOR_BG_BUTTON_HOVER, border_color=COLOR_BORDER_SUBTLE, text_color=COLOR_TEXT_MAIN),
        "accent": dict(fg_color=COLOR_BG_BUTTON, hover_color=COLOR_BG_BUTTON_HOVER, border_color=COLOR_NEON_CYAN, text_color=COLOR_TEXT_MAIN),
        "primary": dict(fg_color=COLOR_CYAN_MID, hover_color=COLOR_CYAN_DARK, border_color=COLOR_NEON_CYAN, text_color=COLOR_TEXT_MAIN),
        "danger": dict(fg_color="#5C1D2B", hover_color="#7F263A", border_color="#F43F5E", text_color=COLOR_TEXT_MAIN),
        "play": dict(fg_color=COLOR_PLAY_ACTIVE, hover_color="#00B87A", border_color="#FFFFFF", text_color=COLOR_TEXT_DARK),
        # サブ操作ボタン（均一サイズ・明快な色の区別）
        "sub_head": dict(fg_color="#182338", hover_color="#243452", border_color="#47608A", text_color="#E2EDF8"),
        "sub_bm": dict(fg_color="#2A2006", hover_color="#423208", border_color="#FFB300", text_color="#FDE047"),
        "sub_del": dict(fg_color="#2A1018", hover_color="#401824", border_color="#E11D48", text_color="#FDA4AF"),
    }

    def btn(self, parent, text, cmd, size=17, height=44, width=None, kind="normal", radius=10):
        kw = dict(text=text, command=cmd, height=height, corner_radius=radius, border_width=2, font=self.F(size))
        kw.update(self.BTN_STYLES[kind])
        if width:
            kw["width"] = width
        return ctk.CTkButton(parent, **kw)

    def set_btn_kind(self, button, kind, highlight_border=None):
        st = dict(self.BTN_STYLES[kind])
        if highlight_border:
            st["border_color"] = highlight_border
        button.configure(**st)

    # -------------------------------------------------------------------------
    # Config
    # -------------------------------------------------------------------------
    def load_config(self):
        self.config = json.loads(json.dumps(DEFAULT_CONFIG))
        target_file = CONFIG_FILE if os.path.exists(CONFIG_FILE) else (CONFIG_DEFAULT_FILE if os.path.exists(CONFIG_DEFAULT_FILE) else None)
        if target_file:
            try:
                with open(target_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                saved_hk = saved.pop("hotkeys", {})
                self.config.update(saved)
                self.config["hotkeys"].update(saved_hk)
                if not isinstance(self.config.get("bookmarks_dict"), dict):
                    self.config["bookmarks_dict"] = {}
            except Exception as e:
                print("Failed to load config:", e)

    def save_config(self):
        if self.engine.current_file:
            self.config["last_file"] = self.engine.current_file
            self.config["last_position"] = round(self.engine.get_position_seconds(), 3)
        tmp_file = CONFIG_FILE + ".tmp"
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, CONFIG_FILE)
        except Exception as e:
            print("Failed to save config atomically:", e)

    def setup_hotkeys(self):
        self.hotkey_mgr.set_hotkeys(self.config.get("hotkeys", {}))

    def report_hotkey_status(self):
        try:
            _ok, fb = self.hotkey_mgr.get_status()
            if fb:
                names = "、".join(HOTKEY_NAMES.get(a, a) for a, _ in fb[:3])
                self.flash_status(f"注意: 一部のキーが他のアプリと重複（{names} 等）— 代替監視で動作中", COLOR_PAUSE_ACTIVE, 6000)
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # UI construction
    # -------------------------------------------------------------------------
    def init_ui(self):
        self.main_container = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=22, pady=10)
        mc = self.main_container

        # ---------- 1. Header ----------
        top_bar = ctk.CTkFrame(mc, fg_color="transparent")
        top_bar.pack(fill="x", pady=(0, 4))

        brand = ctk.CTkFrame(top_bar, fg_color="transparent")
        brand.pack(side="left")
        if os.path.exists(LOGO_FILE):
            try:
                pil_logo = Image.open(LOGO_FILE)
                self.logo_img = ctk.CTkImage(light_image=pil_logo, dark_image=pil_logo, size=(40, 40))
                ctk.CTkLabel(brand, image=self.logo_img, text="").pack(side="left", padx=(0, 10))
            except Exception:
                pass
        # 中身のヘッダー：バージョン記載は排除し、元通りのすっきりした表記に
        ctk.CTkLabel(brand, text="Dicta", font=self.F(28), text_color=COLOR_TEXT_MAIN).pack(side="left")
        ctk.CTkLabel(brand, text="ディクタ ｜ 文字起こし再生スタジオ", font=self.F(15), text_color=COLOR_NEON_CYAN).pack(side="left", padx=(12, 0), pady=(4, 0))

        self.btn_top = self.btn(top_bar, "最前面: OFF", self.toggle_always_on_top, size=15, height=38, width=150)
        self.btn_top.pack(side="right", padx=4)
        self.btn_mini = self.btn(top_bar, "ミニモード", self.toggle_mini_mode, size=15, height=38, width=140)
        self.btn_mini.pack(side="right", padx=4)
        self.btn_settings = self.btn(top_bar, "設定・キー", self.show_settings_dialog, size=15, height=38, width=150, kind="accent")
        self.btn_settings.pack(side="right", padx=4)

        # ---------- 2. File bar ----------
        file_box = self.card(mc)
        file_box.pack(fill="x", pady=4)
        self.lbl_filename = ctk.CTkLabel(
            file_box, text="音声ファイル未選択 — 右のボタン、またはドラッグ＆ドロップで開きます",
            anchor="w", font=self.F(18), text_color=COLOR_TEXT_MAIN)
        self.lbl_filename.pack(side="left", fill="x", expand=True, padx=16, pady=8)
        self.btn(file_box, "ファイルを開く", self.open_file_dialog, size=16, height=40, width=190,
                 kind="primary").pack(side="right", padx=10, pady=6)

        # ---------- 3. Counter & Copy Box (時間コピー ＆ 区間コピー並び) ----------
        counter_box = self.card(mc, glow=True, bg=COLOR_BG_COUNTER)
        counter_box.pack(fill="x", pady=4)
        ci = ctk.CTkFrame(counter_box, fg_color="transparent")
        ci.pack(fill="x", padx=24, pady=8)

        tcol = ctk.CTkFrame(ci, fg_color="transparent")
        tcol.pack(side="left")
        self.lbl_status_dot = ctk.CTkLabel(tcol, text="● 待機中", font=self.F(16), text_color=COLOR_TEXT_SUB, anchor="w")
        self.lbl_status_dot.pack(anchor="w")

        self.time_nums_row = ctk.CTkFrame(tcol, fg_color="transparent")
        self.time_nums_row.pack(anchor="w")
        self.lbl_time = ctk.CTkLabel(self.time_nums_row, text="00:00:00.0", font=self.F(74, mono=True), text_color=COLOR_NEON_CYAN)
        self.lbl_time.pack(side="left")
        self.lbl_duration = ctk.CTkLabel(self.time_nums_row, text="/ 00:00:00", font=self.F(30, mono=True), text_color=COLOR_TEXT_SUB)
        self.lbl_duration.pack(side="left", padx=14, pady=(24, 0))
        self._make_time_label_editable(self.lbl_time, "main")

        # 時間コピー（左） ＆ 区間コピー（右隣）
        acol = ctk.CTkFrame(ci, fg_color="transparent")
        acol.pack(side="right", pady=4)

        copy_row = ctk.CTkFrame(acol, fg_color="transparent")
        copy_row.pack(fill="x", pady=(0, 6))

        self.btn_copy = self.btn(copy_row, "📋 時間コピー", self.action_counter_copy, size=17, height=48, width=155, kind="primary")
        self.btn_copy.pack(side="left", padx=(0, 6))

        self.btn_copy_range = self.btn(copy_row, "⏱ 区間コピー", self.action_range_copy, size=17, height=48, width=155, kind="accent")
        self.btn_copy_range.pack(side="left")

        self.seg_copy = ctk.CTkSegmentedButton(
            acol, values=["秒まで", "ミリ秒まで"], font=self.F(15), height=34,
            selected_color=COLOR_CYAN_MID, selected_hover_color=COLOR_CYAN_DARK,
            unselected_color=COLOR_BG_BUTTON, command=self.on_copy_precision_change)
        self.seg_copy.pack(fill="x")
        self.seg_copy.set("ミリ秒まで" if self.config.get("counter_precision") == "ms" else "秒まで")

        # ---------- 4. Ultra-Thick High-Visibility SeekBar & Compact Controls ----------
        transport_box = self.card(mc)
        transport_box.pack(fill="x", pady=4)

        # 最も太く見やすい進捗バー（Pillowスーパーサンプリングでツマミのガビガビ解消）
        self.seekbar = MainSeekBar(
            transport_box, self.ui_scale, COLOR_BG_CARD,
            on_seek=self.on_seekbar_seek,
            on_preview=self.on_seekbar_preview,
            on_bookmark_delete=self.action_bookmark_delete,
            height=68
        )
        self.seekbar.pack(fill="x", padx=12, pady=(6, 2))

        # トランスポート操作列
        ctrl = ctk.CTkFrame(transport_box, fg_color="transparent")
        ctrl.pack(fill="x", padx=14, pady=(4, 10))

        # メイン再生グループ
        self.btn_rewind = self.btn(ctrl, "◀◀ 戻る", self.action_rewind, size=18, height=46, kind="accent", radius=10)
        self.btn_rewind.pack(side="left", fill="x", expand=True, padx=4)

        self.btn_play = self.btn(ctrl, "▶ 再生", self.action_play_pause, size=21, height=48, kind="play", radius=10)
        self.btn_play.pack(side="left", fill="x", expand=True, padx=6)

        self.btn_forward = self.btn(ctrl, "▶▶ 進む", self.action_forward, size=18, height=46, kind="accent", radius=10)
        self.btn_forward.pack(side="left", fill="x", expand=True, padx=4)

        # サブ操作グループ（幅135px・高さ46px均一、色で明確に区別）
        self.btn_stop = self.btn(ctrl, "最初から", self.action_stop, size=16, height=46, width=135, kind="sub_head", radius=10)
        self.btn_stop.pack(side="left", padx=(12, 4))

        self.btn_bm_add = self.btn(ctrl, "しおり追加", self.action_bookmark_add, size=16, height=46, width=135, kind="sub_bm", radius=10)
        self.btn_bm_add.pack(side="left", padx=4)

        self.btn_bm_clear = self.btn(ctrl, "しおり全消去", self.action_bookmark_clear_all, size=15, height=46, width=135, kind="sub_del", radius=10)
        self.btn_bm_clear.pack(side="left", padx=4)

        self.refresh_jump_labels()

        # ---------- 5. Studio (2 columns) ----------
        studio = ctk.CTkFrame(mc, fg_color="transparent")
        studio.pack(fill="both", expand=True, pady=4)
        studio.grid_columnconfigure(0, weight=1, uniform="col")
        studio.grid_columnconfigure(1, weight=1, uniform="col")
        studio.grid_rowconfigure(0, weight=1)

        self._build_analyzer_column(studio)
        self._build_right_column(studio)

        # ---------- 6. Mini mode ----------
        self._build_mini_mode()

    def _build_analyzer_column(self, studio):
        card = self.card(studio)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(8, 2))
        ctk.CTkLabel(head, text="精密音響解析", font=self.F(19), text_color=COLOR_TEXT_MAIN).pack(side="left")
        self.opt_ana_mode = ctk.CTkSegmentedButton(
            head, values=["波形＋スペクトル", "スペクトログラム", "OFF"], font=self.F(14), height=34,
            selected_color=COLOR_CYAN_MID, selected_hover_color=COLOR_CYAN_DARK, unselected_color=COLOR_BG_BUTTON,
            command=self.on_analyzer_mode_change)
        self.opt_ana_mode.pack(side="right")
        mode = self.config.get("analyzer_mode", "spectrum_wave")
        self.opt_ana_mode.set({"spectrum_wave": "波形＋スペクトル", "spectrogram": "スペクトログラム"}.get(mode, "OFF"))

        self.ana_canvas = tk.Canvas(card, bg="#02050B", height=int(145 * self.ui_scale), highlightthickness=2,
                                    highlightbackground="#1E3A5F", cursor="crosshair")
        self.ana_canvas.pack(fill="both", expand=True, padx=16, pady=4)
        self.ana_canvas.bind("<Button-1>", self.on_canvas_click_frequency)
        self.ana_canvas.bind("<B1-Motion>", self.on_canvas_click_frequency)
        self.ana_canvas.bind("<Configure>", lambda e: setattr(self, "_analyzer_idle_drawn", False))

        iso = ctk.CTkFrame(card, corner_radius=10, fg_color="#071020", border_width=1, border_color="#1E3A5F")
        iso.pack(fill="x", padx=16, pady=(2, 10))

        self.lbl_iso_status = ctk.CTkLabel(iso, text="", font=self.F(16), text_color=COLOR_TEXT_SUB, anchor="w", justify="left")
        self.lbl_iso_status.pack(fill="x", padx=12, pady=(6, 2))
        iso.bind("<Configure>", lambda e: self.lbl_iso_status.configure(wraplength=max(200, int(e.width / self.ui_scale) - 30)))

        grid = ctk.CTkFrame(iso, fg_color="transparent")
        grid.pack(fill="x", padx=8, pady=2)
        for c in range(3):
            grid.grid_columnconfigure(c, weight=1, uniform="iso")
        self.iso_preset_btns = []
        for i, (label, en, freq, bw) in enumerate(ISO_PRESETS):
            b = self.btn(grid, label, lambda e=en, f=freq, w=bw, l=label: self.apply_isolator_preset(e, f, w, l),
                         size=15, height=36, kind="normal", radius=8)
            b.grid(row=i // 3, column=i % 3, sticky="ew", padx=4, pady=2)
            self.iso_preset_btns.append((label, b))

        sl = ctk.CTkFrame(iso, fg_color="transparent")
        sl.pack(fill="x", padx=12, pady=(4, 8))
        sl.grid_columnconfigure(1, weight=3)
        sl.grid_columnconfigure(3, weight=2)
        self.lbl_iso_freq = ctk.CTkLabel(sl, text="中心 1200Hz", font=self.F(14), text_color=COLOR_TEXT_MAIN, width=110, anchor="w")
        self.lbl_iso_freq.grid(row=0, column=0, sticky="w")
        self.slider_iso_freq = ctk.CTkSlider(sl, from_=150, to=5500, height=20, fg_color=COLOR_BG_BUTTON,
                                             progress_color=COLOR_ISOLATOR_ON, button_color=COLOR_ISOLATOR_ON,
                                             command=self.on_iso_slider_change)
        self.slider_iso_freq.grid(row=0, column=1, sticky="ew", padx=(4, 12))
        self.slider_iso_freq.set(1200)
        self.lbl_iso_bw = ctk.CTkLabel(sl, text="幅 1.2", font=self.F(14), text_color=COLOR_TEXT_MAIN, width=65, anchor="w")
        self.lbl_iso_bw.grid(row=0, column=2, sticky="w")
        self.slider_iso_bw = ctk.CTkSlider(sl, from_=0.4, to=2.4, height=20, fg_color=COLOR_BG_BUTTON,
                                           progress_color=COLOR_NEON_CYAN, button_color="#FFFFFF",
                                           command=self.on_iso_slider_change)
        self.slider_iso_bw.grid(row=0, column=3, sticky="ew", padx=(4, 0))
        self.slider_iso_bw.set(1.2)
        self.update_isolator_ui(active_preset="通常（全域）")

    def _build_right_column(self, studio):
        right = ctk.CTkFrame(studio, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        # 1. 再生速度 (0.20倍〜3.00倍) & ピッチ
        sp = self.card(right)
        sp.pack(fill="x", pady=(0, 6))
        sh = ctk.CTkFrame(sp, fg_color="transparent")
        sh.pack(fill="x", padx=16, pady=(8, 2))
        ctk.CTkLabel(sh, text="再生速度", font=self.F(19), text_color=COLOR_TEXT_MAIN).pack(side="left")
        self.lbl_speed_val = ctk.CTkLabel(sh, text="1.00倍", font=self.F(22, mono=True), text_color=COLOR_NEON_CYAN)
        self.lbl_speed_val.pack(side="left", padx=10)

        pf = ctk.CTkFrame(sh, fg_color="transparent")
        pf.pack(side="right")
        ctk.CTkLabel(pf, text="声の高さ", font=self.F(15), text_color=COLOR_TEXT_SUB).pack(side="left", padx=4)
        self.btn(pf, "－", lambda: self.adjust_pitch(-0.5), size=16, height=32, width=36, radius=6).pack(side="left", padx=2)
        self.lbl_pitch_val = ctk.CTkLabel(pf, text="0.0", font=self.F(17, mono=True), text_color=COLOR_NEON_CYAN, width=46)
        self.lbl_pitch_val.pack(side="left", padx=2)
        self.btn(pf, "＋", lambda: self.adjust_pitch(0.5), size=16, height=32, width=36, radius=6).pack(side="left", padx=2)
        self.btn(pf, "標準", lambda: self.set_pitch(0.0), size=14, height=32, width=50, radius=6).pack(side="left", padx=(4, 0))

        sb = ctk.CTkFrame(sp, fg_color="transparent")
        sb.pack(fill="x", padx=16, pady=(0, 8))
        self.slider_speed = ctk.CTkSlider(sb, from_=0.2, to=3.0, number_of_steps=280, height=22, fg_color=COLOR_BG_BUTTON,
                                          progress_color=COLOR_CYAN_MID, button_color=COLOR_NEON_CYAN,
                                          command=lambda v: self.set_speed(float(v)))
        self.slider_speed.pack(fill="x", pady=4)
        self.slider_speed.set(1.0)
        pr = ctk.CTkFrame(sb, fg_color="transparent")
        pr.pack(fill="x")
        self.speed_preset_btns = {}
        for spd in [0.5, 0.8, 1.0, 1.2, 1.5, 2.0]:
            b = self.btn(pr, f"{spd}倍", lambda s=spd: self.set_speed(s), size=16, height=36, radius=8)
            b.pack(side="left", expand=True, fill="x", padx=2)
            self.speed_preset_btns[spd] = b

        # 2. 区間リピート（A-Bループ）
        lp = self.card(right)
        lp.pack(fill="x", pady=(0, 6))
        li = ctk.CTkFrame(lp, fg_color="transparent")
        li.pack(fill="x", padx=16, pady=8)
        ctk.CTkLabel(li, text="区間リピート", font=self.F(18), text_color=COLOR_TEXT_MAIN).pack(side="left", padx=(0, 8))
        self.btn_loop_a = self.btn(li, "A点", self.action_toggle_loop_a, size=16, height=38, radius=8)
        self.btn_loop_a.pack(side="left", fill="x", expand=True, padx=3)
        self.btn_loop_b = self.btn(li, "B点", self.action_toggle_loop_b, size=16, height=38, radius=8)
        self.btn_loop_b.pack(side="left", fill="x", expand=True, padx=3)
        self.btn_loop_clear = self.btn(li, "解除", self.action_clear_loop, size=15, height=38, width=80, kind="danger", radius=8)
        self.btn_loop_clear.pack(side="left", padx=(3, 0))

        # 3. イコライザー ＆ その下にマスター音量
        eq = self.card(right)
        eq.pack(fill="both", expand=True)

        et = ctk.CTkFrame(eq, fg_color="transparent")
        et.pack(fill="x", padx=16, pady=(8, 2))
        ctk.CTkLabel(et, text="イコライザー", font=self.F(18), text_color=COLOR_TEXT_MAIN).pack(side="left")
        self.opt_eq = ctk.CTkOptionMenu(et, values=list(EQ_PRESETS.keys()), command=self.on_eq_preset_changed,
                                        width=280, height=34, corner_radius=8, fg_color=COLOR_BG_BUTTON,
                                        button_color=COLOR_CYAN_MID, button_hover_color=COLOR_CYAN_DARK,
                                        font=self.F(15), dropdown_font=self.F(15))
        self.opt_eq.pack(side="right")
        self.opt_eq.set(self.config.get("eq_preset", "クリアボイス（会話強調）"))

        er = ctk.CTkFrame(eq, fg_color="transparent")
        er.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        self.eq_sliders = []
        for idx, (lbl, gain) in enumerate(zip(EQ_FREQ_LABELS, self.config.get("eq_gains", [0] * 6))):
            col = ctk.CTkFrame(er, fg_color="transparent")
            col.pack(side="left", expand=True, fill="both", padx=2)
            ctk.CTkLabel(col, text=lbl, font=self.F(13, mono=True), text_color=COLOR_TEXT_MAIN).pack(side="bottom")
            s = ctk.CTkSlider(col, from_=-15.0, to=15.0, orientation="vertical", height=75, width=22,
                              fg_color=COLOR_BG_BUTTON, progress_color=COLOR_CYAN_MID, button_color=COLOR_NEON_CYAN,
                              command=lambda v, i=idx: self.on_eq_manual_change(i, v))
            s.pack(side="top", expand=True, fill="y", pady=2)
            s.set(gain)
            self.eq_sliders.append(s)

        # 4. イコライザー直下のマスター音量バー
        vol_frame = ctk.CTkFrame(eq, fg_color="#071020", corner_radius=10, border_width=1, border_color="#1E3A5F")
        vol_frame.pack(fill="x", padx=12, pady=(2, 8))

        vt = ctk.CTkFrame(vol_frame, fg_color="transparent")
        vt.pack(fill="x", padx=12, pady=(6, 2))
        ctk.CTkLabel(vt, text="マスター音量", font=self.F(16), text_color=COLOR_TEXT_MAIN).pack(side="left")
        self.lbl_vol_val = ctk.CTkLabel(vt, text="90%", font=self.F(18, mono=True), text_color=COLOR_NEON_CYAN)
        self.lbl_vol_val.pack(side="left", padx=10)
        ctk.CTkLabel(vt, text="（マウスホイールで1%微調整）", font=self.F(13, bold=False), text_color=COLOR_TEXT_SUB).pack(side="right")

        vr = ctk.CTkFrame(vol_frame, fg_color="transparent")
        vr.pack(fill="x", padx=8, pady=(0, 6))
        self.btn(vr, "－", lambda: self.adjust_volume(-0.01), size=18, height=36, width=44, radius=6).pack(side="left")
        self.slider_vol = ctk.CTkSlider(
            vr, from_=0, to=100, number_of_steps=200, height=24,
            fg_color="#1B2E4B", progress_color=COLOR_NEON_CYAN, button_color="#FFFFFF",
            button_hover_color=COLOR_ISOLATOR_ON, command=lambda v: self.on_volume_change(float(v) / 100.0))
        self.slider_vol.pack(side="left", fill="x", expand=True, padx=8)
        self.slider_vol.bind("<MouseWheel>", lambda e: self.adjust_volume(0.01 if e.delta > 0 else -0.01))
        self.btn(vr, "＋", lambda: self.adjust_volume(0.01), size=18, height=36, width=44, radius=6).pack(side="left")

    def _build_mini_mode(self):
        self.mini_container = ctk.CTkFrame(self, corner_radius=0, fg_color=COLOR_BG_MAIN)
        mt = ctk.CTkFrame(self.mini_container, fg_color="transparent")
        mt.pack(fill="x", padx=14, pady=(8, 0))
        ctk.CTkLabel(mt, text=f"Dicta {self.version_str}", font=self.F(16), text_color=COLOR_NEON_CYAN).pack(side="left", padx=(0, 10))
        self.mini_time_row = ctk.CTkFrame(mt, fg_color="transparent")
        self.mini_time_row.pack(side="left")
        self.lbl_mini_time = ctk.CTkLabel(self.mini_time_row, text="00:00:00.0", font=self.F(38, mono=True), text_color=COLOR_NEON_CYAN)
        self.lbl_mini_time.pack(side="left")
        self._make_time_label_editable(self.lbl_mini_time, "mini")
        self.lbl_mini_speed = ctk.CTkLabel(mt, text="1.00倍", font=self.F(18, mono=True), text_color=COLOR_TEXT_MAIN)
        self.lbl_mini_speed.pack(side="left", padx=12)
        self.btn(mt, "通常画面に戻す", self.toggle_mini_mode, size=15, height=36, width=150, kind="primary", radius=8).pack(side="right")

        self.mini_seekbar = MainSeekBar(
            self.mini_container, self.ui_scale, COLOR_BG_MAIN,
            on_seek=self.on_seekbar_seek,
            on_preview=self.on_seekbar_preview,
            on_bookmark_delete=self.action_bookmark_delete,
            height=46
        )
        self.mini_seekbar.pack(fill="x", padx=8)

        mc = ctk.CTkFrame(self.mini_container, fg_color="transparent")
        mc.pack(fill="x", padx=14, pady=(0, 8))
        self.btn_mini_rew = self.btn(mc, "◀◀ 戻る", self.action_rewind, size=16, height=42, kind="accent", radius=8)
        self.btn_mini_rew.pack(side="left", fill="x", expand=True, padx=3)
        self.btn_mini_play = self.btn(mc, "▶ 再生", self.action_play_pause, size=18, height=42, kind="play", radius=8)
        self.btn_mini_play.pack(side="left", fill="x", expand=True, padx=3)
        self.btn_mini_fwd = self.btn(mc, "▶▶ 進む", self.action_forward, size=16, height=42, kind="accent", radius=8)
        self.btn_mini_fwd.pack(side="left", fill="x", expand=True, padx=3)
        self.btn(mc, "遅く", lambda: self.adjust_speed(-self.config.get("speed_step", 0.05)), size=15, height=42, width=65, radius=8).pack(side="left", padx=2)
        self.btn(mc, "速く", lambda: self.adjust_speed(self.config.get("speed_step", 0.05)), size=15, height=42, width=65, radius=8).pack(side="left", padx=2)
        self.btn(mc, "しおり", self.action_bookmark_add, size=15, height=42, width=80, kind="sub_bm", radius=8).pack(side="left", padx=2)
        self.btn(mc, "コピー", self.action_counter_copy, size=15, height=42, width=80, kind="primary", radius=8).pack(side="left", padx=2)

    # -------------------------------------------------------------------------
    # Status line helper
    # -------------------------------------------------------------------------
    def set_status(self, text, color=COLOR_TEXT_SUB):
        self._status_base = (text, color)
        if self._status_restore_job is None:
            self.lbl_status_dot.configure(text=text, text_color=color)

    def flash_status(self, text, color, ms=2500):
        if self._status_restore_job is not None:
            self.after_cancel(self._status_restore_job)
        self.lbl_status_dot.configure(text=text, text_color=color)
        self._status_restore_job = self.after(ms, self.restore_status)

    def restore_status(self):
        if self._status_restore_job is not None:
            try:
                self.after_cancel(self._status_restore_job)
            except Exception:
                pass
        self._status_restore_job = None
        base = getattr(self, "_status_base", ("● 待機中", COLOR_TEXT_SUB))
        self.lbl_status_dot.configure(text=base[0], text_color=base[1])

    def _cache_badge(self):
        return "　[SSDキャッシュ再生]" if self.engine.is_cached_copy else ""

    # -------------------------------------------------------------------------
    # Click-to-edit timecode
    # -------------------------------------------------------------------------
    def _make_time_label_editable(self, label, which):
        try:
            label.configure(cursor="hand2")
        except Exception:
            pass
        label.bind("<Button-1>", lambda e: self.begin_time_edit(which))
        label.bind("<Enter>", lambda e: (label.configure(text_color=COLOR_TEXT_MAIN),
                                         which == "main" and self.flash_status("数字をクリックすると時間を直接入力してジャンプできます", COLOR_TEXT_MAIN, 2500)))
        label.bind("<Leave>", lambda e: label.configure(text_color=COLOR_NEON_CYAN))

    def begin_time_edit(self, which="main"):
        if self.editing_time or not self.engine.current_file:
            return
        self.editing_time = which
        if which == "main":
            label, row, size, before = self.lbl_time, self.time_nums_row, 62, self.lbl_duration
        else:
            label, row, size, before = self.lbl_mini_time, self.mini_time_row, 32, None
        label.pack_forget()
        ent = ctk.CTkEntry(row, font=self.F(size, mono=True), width=int(size * 6.4), height=int(size * 1.45),
                           justify="center", fg_color="#0B1A2E", border_color=COLOR_ISOLATOR_ON, border_width=3,
                           text_color=COLOR_NEON_CYAN)
        if before is not None:
            ent.pack(side="left", before=before)
        else:
            ent.pack(side="left")
        ent.insert(0, format_time(self.engine.get_position_seconds(), include_ms=False))
        ent.select_range(0, "end")
        ent.icursor("end")
        ent.focus_set()
        self._time_entry = ent
        if which == "main":
            self.flash_status("時間を入力して Enter（例: 1:24:18 ／ 012418 ／ 1:24:04,492） Escで取消", COLOR_ISOLATOR_ON, 15000)
        ent.bind("<Return>", lambda e: self.end_time_edit(commit=True))
        ent.bind("<KP_Enter>", lambda e: self.end_time_edit(commit=True))
        ent.bind("<Escape>", lambda e: self.end_time_edit(commit=False))
        ent.bind("<FocusOut>", lambda e: self.after(120, lambda: self.end_time_edit(commit=False)))

    def end_time_edit(self, commit):
        which = self.editing_time
        if not which:
            return
        ent = self._time_entry
        text = ent.get()
        self.editing_time = None
        self._time_entry = None
        try:
            ent.destroy()
        except Exception:
            pass
        if which == "main":
            self.lbl_time.pack(side="left", before=self.lbl_duration)
        else:
            self.lbl_mini_time.pack(side="left")
        if commit:
            sec = parse_time_input(text)
            if sec is None:
                self.flash_status("時間の形式が読み取れませんでした（例: 1:24:18）", COLOR_PAUSE_ACTIVE, 3500)
                return
            sec = max(0.0, min(self.engine.duration_seconds, sec))
            self.engine.set_position_seconds(sec)
            self.refresh_position_display(sec)
            self.flash_status(f"移動: {format_time(sec, include_ms=False)}", COLOR_NEON_CYAN, 2500)
        elif which == "main":
            self.restore_status()

    def action_counter_jump(self):
        try:
            if self.state() == "iconic":
                self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:
            pass
        self.begin_time_edit("mini" if self.is_mini_mode else "main")

    # -------------------------------------------------------------------------
    # Analyzer & isolator
    # -------------------------------------------------------------------------
    def on_analyzer_mode_change(self, val):
        self.config["analyzer_mode"] = {"波形＋スペクトル": "spectrum_wave", "スペクトログラム": "spectrogram"}.get(val, "off")
        self._analyzer_idle_drawn = False
        if self.config["analyzer_mode"] == "off":
            self.ana_canvas.delete("all")
            w = max(100, self.ana_canvas.winfo_width())
            h = max(60, self.ana_canvas.winfo_height())
            self.ana_canvas.create_text(w // 2, h // 2, text="解析モニター休止中（省電力）",
                                        fill=COLOR_TEXT_SUB, font=(FONT_UI, 14, "bold"))

    def apply_isolator_preset(self, enabled, center_hz, bw_oct, label_name):
        self.slider_iso_freq.set(center_hz)
        self.slider_iso_bw.set(bw_oct)
        self.engine.set_bandpass_isolator(enabled, center_hz, bw_oct)
        self.update_isolator_ui(active_preset=label_name if enabled else "通常（全域）")

    def on_iso_slider_change(self, _=None):
        self.engine.set_bandpass_isolator(True, float(self.slider_iso_freq.get()), float(self.slider_iso_bw.get()))
        self.update_isolator_ui(active_preset="custom")

    def on_canvas_click_frequency(self, event):
        w = max(1, self.ana_canvas.winfo_width())
        ratio = max(0.0, min(1.0, event.x / w))
        freq = max(150.0, min(5500.0, 80.0 * ((10000.0 / 80.0) ** ratio)))
        self.slider_iso_freq.set(freq)
        self.engine.set_bandpass_isolator(True, freq, float(self.slider_iso_bw.get()))
        self.update_isolator_ui(active_preset="custom")

    def update_isolator_ui(self, active_preset=""):
        self.lbl_iso_freq.configure(text=f"中心 {int(self.slider_iso_freq.get())}Hz")
        self.lbl_iso_bw.configure(text=f"幅 {self.slider_iso_bw.get():.1f}")
        if not self.engine.isolator_enabled:
            self.lbl_iso_status.configure(text="周波数の抜き出し: OFF（すべての帯域を再生中）", text_color=COLOR_TEXT_SUB)
        else:
            c_hz = int(self.engine.isolator_center_hz)
            bw = self.engine.isolator_bw_oct
            lo, hi = int(c_hz / (2 ** (bw / 2))), int(c_hz * (2 ** (bw / 2)))
            self.lbl_iso_status.configure(text=f"抜き出し中: {lo}〜{hi} Hz の音だけを再生（中心 {c_hz} Hz）",
                                          text_color=COLOR_ISOLATOR_ON)
        for lbl, b in self.iso_preset_btns:
            if lbl == active_preset:
                self.set_btn_kind(b, "primary", COLOR_ISOLATOR_ON if self.engine.isolator_enabled else COLOR_NEON_CYAN)
            else:
                self.set_btn_kind(b, "normal")
        self._analyzer_idle_drawn = False

    def render_acoustic_analyzer(self):
        mode = self.config.get("analyzer_mode", "spectrum_wave")
        if mode == "off" or self.is_mini_mode:
            return
        playing = self.engine.is_playing()
        if not playing and self._analyzer_idle_drawn:
            return
        c = self.ana_canvas
        w, h = c.winfo_width(), c.winfo_height()
        if w < 50 or h < 40:
            return

        spectrum, wave_pts = self.engine.get_realtime_analysis(num_bands=44, num_wave_pts=88)
        c.delete("all")
        base = h - 22
        log_span = math.log10(10000.0 / 80.0)
        for f_mark, f_lbl in [(200, "200Hz"), (500, "500Hz"), (1000, "1kHz"), (2000, "2kHz"), (4000, "4kHz"), (8000, "8kHz")]:
            gx = int(math.log10(f_mark / 80.0) / log_span * w)
            c.create_line(gx, 0, gx, h, fill="#102238", width=1)
            c.create_text(gx + 4, h - 11, text=f_lbl, anchor="w", fill="#7F9BC0", font=(FONT_MONO, 10, "bold"))

        if mode == "spectrum_wave":
            num_b = len(spectrum)
            slot = w / num_b
            bar_w = max(4, slot - 3)
            for i, val in enumerate(spectrum):
                bh = int(val * (base - 6))
                if bh > 2:
                    bx = i * slot + 2
                    c.create_rectangle(bx, base - bh, bx + bar_w, base, fill="#00F0FF" if val < 0.75 else "#FFEA00", outline="")
            mid_y, amp_y = base * 0.42, base * 0.38
            pts = []
            n = len(wave_pts)
            for i, wv in enumerate(wave_pts):
                pts.extend([int(i / max(1, n - 1) * w), int(mid_y - wv * amp_y)])
            if len(pts) >= 4:
                c.create_line(*pts, fill="#FFFFFF", width=2, smooth=True)
        elif mode == "spectrogram":
            if playing:
                self.spec_history.append([max(spectrum[i * 2], spectrum[i * 2 + 1]) for i in range(22)])
            max_rows = self.spec_history.maxlen
            cell_h = max(2, base / max_rows)
            cell_w = max(4, w / 22)
            for r_idx, bins in enumerate(self.spec_history):
                y1 = int((max_rows - 1 - r_idx) * cell_h)
                y2 = int(y1 + cell_h + 1)
                for b_idx, val in enumerate(bins):
                    if val > 0.04:
                        x1 = int(b_idx * cell_w)
                        c.create_rectangle(x1, y1, int(x1 + cell_w + 1), y2, fill=intensity_to_hex(val), outline="")

        if self.engine.isolator_enabled:
            c_hz = self.engine.isolator_center_hz
            bw = self.engine.isolator_bw_oct
            lo = max(80.0, c_hz / (2 ** (bw / 2)))
            hi = min(10000.0, c_hz * (2 ** (bw / 2)))
            x1 = int(math.log10(lo / 80.0) / log_span * w)
            x2 = int(math.log10(hi / 80.0) / log_span * w)
            xc = int(math.log10(c_hz / 80.0) / log_span * w)
            c.create_rectangle(x1, 2, x2, base, outline=COLOR_ISOLATOR_ON, width=3)
            c.create_line(xc, 2, xc, base, fill=COLOR_ISOLATOR_ON, width=2, dash=(4, 2))
            c.create_text(max(60, min(w - 60, xc)), 16, text=f"抽出中: {int(c_hz)}Hz", fill=COLOR_ISOLATOR_ON, font=(FONT_UI, 12, "bold"))
        if not playing:
            c.create_text(w // 2, base // 2, text="再生すると音の波形と周波数が表示されます\n（グラフをクリックするとその高さの音だけを抜き出せます）",
                          fill="#5B789E", font=(FONT_UI, 13, "bold"), justify="center")
        self._analyzer_idle_drawn = not playing

    # -------------------------------------------------------------------------
    # File handling
    # -------------------------------------------------------------------------
    def on_file_drop(self, event):
        raw = event.data
        if not raw:
            return
        path = raw[1:raw.index("}")] if raw.startswith("{") and "}" in raw else raw.split()[0]
        if os.path.exists(path):
            self.load_audio(path)

    def open_file_dialog(self):
        filetypes = [
            ("音声ファイル（すべて）", "*.mp3 *.wav *.m4a *.aac *.flac *.wma *.ogg"),
            ("MP3", "*.mp3"), ("WAV", "*.wav"), ("M4A/AAC", "*.m4a *.aac"), ("FLAC", "*.flac"),
            ("すべてのファイル", "*.*")
        ]
        path = filedialog.askopenfilename(title="Dicta — 音声ファイルを選択", filetypes=filetypes)
        if path:
            self.load_audio(path)

    def load_audio(self, path):
        try:
            if self.engine.current_file:
                self.save_config()
            dur = self.engine.load_file(path, use_local_cache=self.config.get("use_ssd_cache", True))
            self.lbl_filename.configure(text=f"♪ {os.path.basename(path)}")
            self.lbl_duration.configure(text=f"/ {format_time(dur, include_ms=False)}")
            self.seekbar.set_duration(dur)
            self.mini_seekbar.set_duration(dur)
            self.set_status(f"● 準備完了{self._cache_badge()}", COLOR_NEON_CYAN)
            self.loop_a = None
            self.loop_b = None
            self.spec_history.clear()
            self._analyzer_idle_drawn = False
            self.config["last_file"] = path
            self.config["last_position"] = 0.0
            self.update_loop_ui()
            self.refresh_bookmarks_ui()
            self.apply_eq_gains(self.config.get("eq_gains", [-4.0, -1.0, 2.0, 6.0, 3.0, -2.0]))
            self.set_speed(self.config.get("speed", 1.0))
            self.set_pitch(self.config.get("pitch", 0.0))
            self.engine.set_volume(self.config.get("volume", 0.9))
            self.refresh_position_display(0.0)
            self.set_play_buttons(False)
        except Exception as e:
            messagebox.showerror("読み込みエラー", f"音声ファイルを開けませんでした:\n{e}")

    def resume_file(self, file_path, position):
        try:
            self.load_audio(file_path)
            if position > 0:
                self.engine.set_position_seconds(position)
                self.refresh_position_display(position)
                self.set_status(f"● 前回の続き（{format_time(position, include_ms=False)}）から再開できます{self._cache_badge()}", COLOR_NEON_CYAN)
        except Exception as e:
            print("Resume failed:", e)

    # -------------------------------------------------------------------------
    # Transport
    # -------------------------------------------------------------------------
    def refresh_jump_labels(self):
        rs = self.config.get("jump_rewind_sec", 5.0)
        fs = self.config.get("jump_forward_sec", 5.0)
        fmt = lambda v: f"{v:g}"
        self.btn_rewind.configure(text=f"◀◀ {fmt(rs)}秒戻る")
        self.btn_forward.configure(text=f"▶▶ {fmt(fs)}秒進む")
        if hasattr(self, "btn_mini_rew"):
            self.btn_mini_rew.configure(text=f"◀◀ {fmt(rs)}秒")
            self.btn_mini_fwd.configure(text=f"▶▶ {fmt(fs)}秒")

    def set_play_buttons(self, playing):
        if playing:
            self.btn_play.configure(text="⏸ 一時停止", fg_color=COLOR_PAUSE_ACTIVE, hover_color="#E0A000")
            self.btn_mini_play.configure(text="⏸ 停止", fg_color=COLOR_PAUSE_ACTIVE, hover_color="#E0A000")
        else:
            self.btn_play.configure(text="▶ 再生", fg_color=COLOR_PLAY_ACTIVE, hover_color="#00B87A")
            self.btn_mini_play.configure(text="▶ 再生", fg_color=COLOR_PLAY_ACTIVE, hover_color="#00B87A")
        self._buttons_show_playing = playing

    def refresh_position_display(self, pos):
        txt = format_time(pos, include_ms=True)
        self.lbl_time.configure(text=txt)
        self.lbl_mini_time.configure(text=txt)
        self.seekbar.set_position(pos)
        self.mini_seekbar.set_position(pos)

    def action_play_pause(self):
        if not self.engine.current_file:
            return
        if self.engine.is_playing():
            self.engine.pause()
            auto_rew = self.config.get("auto_rewind_sec", 1.0)
            if auto_rew > 0:
                self.engine.jump_relative(-auto_rew)
            self.set_play_buttons(False)
            self.set_status(f"● 一時停止中（{auto_rew:g}秒巻き戻し済み）", COLOR_PAUSE_ACTIVE)
            self.save_config()
        else:
            self.engine.play()
            self.set_play_buttons(True)
            self.set_status(f"● 再生中{self._cache_badge()}", COLOR_PLAY_ACTIVE)
        self._analyzer_idle_drawn = False

    def action_rewind(self):
        if self.engine.current_file:
            self.refresh_position_display(self.engine.jump_relative(-self.config.get("jump_rewind_sec", 5.0)))

    def action_forward(self):
        if self.engine.current_file:
            self.refresh_position_display(self.engine.jump_relative(self.config.get("jump_forward_sec", 5.0)))

    def action_stop(self):
        if not self.engine.current_file:
            return
        if self.loop_a is not None:
            self.engine.set_position_seconds(self.loop_a)
            self.refresh_position_display(self.loop_a)
        else:
            self.engine.stop()
            self.set_play_buttons(False)
            self.set_status("● 最初に戻りました", COLOR_TEXT_SUB)
            self.refresh_position_display(0.0)

    def on_copy_precision_change(self, val):
        self.config["counter_precision"] = "ms" if val == "ミリ秒まで" else "sec"

    def action_counter_copy(self):
        pos = self.engine.get_position_seconds()
        raw = format_time_copy(pos, self.config.get("counter_precision", "sec"))
        tag = self.config.get("counter_format", "{time}").replace("{time}", raw)
        self.clipboard_clear()
        self.clipboard_append(tag)
        self.btn_copy.configure(text="✓ コピー完了！", fg_color=COLOR_PLAY_ACTIVE, text_color=COLOR_TEXT_DARK)
        if getattr(self, "_copy_restore_job", None):
            self.after_cancel(self._copy_restore_job)
        self._copy_restore_job = self.after(1200, lambda: self.btn_copy.configure(
            text="📋 時間コピー", fg_color=COLOR_CYAN_MID, text_color=COLOR_TEXT_MAIN))
        self.flash_status(f"時間コピー: {tag}", COLOR_PLAY_ACTIVE, 1800)

    def action_range_copy(self):
        """A点からB点を『01:30:27,175 --> 01:30:37,420』形式でコピー"""
        prec = self.config.get("counter_precision", "sec")
        if self.loop_a is not None and self.loop_b is not None:
            s_start = min(self.loop_a, self.loop_b)
            s_end = max(self.loop_a, self.loop_b)
        elif self.loop_a is not None:
            pos = self.engine.get_position_seconds()
            s_start = min(self.loop_a, pos)
            s_end = max(self.loop_a, pos)
        elif self.loop_b is not None:
            pos = self.engine.get_position_seconds()
            s_start = min(pos, self.loop_b)
            s_end = max(pos, self.loop_b)
        else:
            self.flash_status("区間コピー: 先にA点・B点を指定してください（A点のみ指定で現在位置までコピー）", COLOR_PAUSE_ACTIVE, 3500)
            return

        t1 = format_time_copy(s_start, prec)
        t2 = format_time_copy(s_end, prec)
        range_str = f"{t1} --> {t2}"

        self.clipboard_clear()
        self.clipboard_append(range_str)
        self.btn_copy_range.configure(text="✓ コピー完了！", fg_color=COLOR_PLAY_ACTIVE, text_color=COLOR_TEXT_DARK)
        if getattr(self, "_copy_range_restore_job", None):
            self.after_cancel(self._copy_range_restore_job)
        self._copy_range_restore_job = self.after(1200, lambda: self.btn_copy_range.configure(
            text="⏱ 区間コピー", fg_color=COLOR_BG_BUTTON, text_color=COLOR_TEXT_MAIN))
        self.flash_status(f"区間コピー: {range_str}", COLOR_PLAY_ACTIVE, 2500)

    # -------------------------------------------------------------------------
    # A-B loop
    # -------------------------------------------------------------------------
    def action_toggle_loop_a(self):
        self.loop_a = self.engine.get_position_seconds() if self.loop_a is None else None
        self.update_loop_ui()

    def action_toggle_loop_b(self):
        self.loop_b = self.engine.get_position_seconds() if self.loop_b is None else None
        self.update_loop_ui()

    def action_clear_loop(self):
        self.loop_a = None
        self.loop_b = None
        self.update_loop_ui()

    def update_loop_ui(self):
        if self.loop_a is not None and self.loop_b is not None and self.loop_a > self.loop_b:
            self.loop_a, self.loop_b = self.loop_b, self.loop_a
        for val, b, name in ((self.loop_a, self.btn_loop_a, "A"), (self.loop_b, self.btn_loop_b, "B")):
            if val is not None:
                b.configure(text=f"{name} {format_time(val, False)}", font=self.F(16, mono=True))
                self.set_btn_kind(b, "primary", COLOR_REPEAT_RED)
            else:
                b.configure(text=f"{name}点", font=self.F(16))
                self.set_btn_kind(b, "normal")
        self.btn_stop.configure(text="A点から" if self.loop_a is not None else "最初から")
        self.update_seek_markers()

    # -------------------------------------------------------------------------
    # Bookmarks (進捗バー直結のしおり機能)
    # -------------------------------------------------------------------------
    def _get_current_file_bookmarks(self):
        f = self.engine.current_file
        if not f:
            return []
        b_dict = self.config.setdefault("bookmarks_dict", {})
        lst = b_dict.get(f)
        if not isinstance(lst, list):
            lst = []
            b_dict[f] = lst
        return lst

    def refresh_bookmarks_ui(self):
        self.update_seek_markers()

    def action_bookmark_add(self):
        """現在再生位置に進捗バー直結のしおり（黄色い縦線）を刻む"""
        f = self.engine.current_file
        if not f:
            return
        t = round(self.engine.get_position_seconds(), 2)
        lst = self._get_current_file_bookmarks()
        if any(abs(existing - t) < 1.0 for existing in lst):
            self.flash_status("この位置には既にしおりがあります", COLOR_BOOKMARK, 2000)
            return
        lst.append(t)
        lst.sort()
        self.refresh_bookmarks_ui()
        self.save_config()
        self.flash_status(f"しおりを追加しました: {format_time(t, False)}（進捗バーをクリックで戻れます）", COLOR_BOOKMARK, 2800)

    def action_bookmark_delete(self, target_sec):
        lst = self._get_current_file_bookmarks()
        self.config["bookmarks_dict"][self.engine.current_file] = [b for b in lst if abs(b - target_sec) >= 0.5]
        self.refresh_bookmarks_ui()
        self.save_config()
        self.flash_status(f"しおりを削除しました: {format_time(target_sec, False)}", COLOR_TEXT_SUB, 2000)

    def action_bookmark_clear_all(self):
        lst = self._get_current_file_bookmarks()
        if not lst:
            self.flash_status("しおりはありません", COLOR_TEXT_SUB, 1500)
            return
        if messagebox.askyesno("しおり消去", "この音声ファイルのすべてのしおりを消去しますか？"):
            self.config["bookmarks_dict"][self.engine.current_file] = []
            self.refresh_bookmarks_ui()
            self.save_config()
            self.flash_status("すべてのしおりを消去しました", COLOR_TEXT_SUB, 2000)

    def update_seek_markers(self):
        bms = self._get_current_file_bookmarks()
        for sbar in (self.seekbar, self.mini_seekbar):
            sbar.set_markers(self.loop_a, self.loop_b, bms)

    # -------------------------------------------------------------------------
    # Speed / pitch / volume / EQ
    # -------------------------------------------------------------------------
    def set_speed(self, speed):
        speed = round(max(0.2, min(3.0, float(speed))), 2)
        self.engine.set_speed(speed)
        self.slider_speed.set(speed)
        self.lbl_speed_val.configure(text=f"{speed:.2f}倍")
        self.lbl_mini_speed.configure(text=f"{speed:.2f}倍")
        self.config["speed"] = speed
        for s, b in self.speed_preset_btns.items():
            self.set_btn_kind(b, "primary" if abs(speed - s) < 0.01 else "normal")

    def adjust_speed(self, delta):
        self.set_speed(self.config.get("speed", 1.0) + delta)

    def set_pitch(self, semitones):
        semitones = round(max(-6.0, min(6.0, float(semitones))), 1)
        self.engine.set_pitch(semitones)
        self.lbl_pitch_val.configure(text=f"{'+' if semitones > 0 else ''}{semitones:.1f}")
        self.config["pitch"] = semitones

    def adjust_pitch(self, delta):
        self.set_pitch(self.config.get("pitch", 0.0) + delta)

    def set_volume_ui(self, vol):
        vol = max(0.0, min(1.0, float(vol)))
        self.slider_vol.set(vol * 100.0)
        self.on_volume_change(vol)

    def adjust_volume(self, delta):
        self.set_volume_ui(round(self.config.get("volume", 0.9) + delta, 3))

    def on_volume_change(self, vol):
        vol = max(0.0, min(1.0, float(vol)))
        self.engine.set_volume(vol)
        self.config["volume"] = vol
        pct = vol * 100.0
        self.lbl_vol_val.configure(text=f"{pct:.0f}%" if abs(pct - round(pct)) < 0.05 else f"{pct:.1f}%")

    def on_eq_preset_changed(self, choice):
        if choice in EQ_PRESETS:
            gains = list(EQ_PRESETS[choice])
            self.apply_eq_gains(gains)
            self.config["eq_preset"] = choice
            for s, g in zip(self.eq_sliders, gains):
                s.set(g)

    def on_eq_manual_change(self, band_index, gain_val):
        g = float(gain_val)
        self.engine.set_eq_band_gain(band_index, g)
        gains = list(self.config.get("eq_gains", [0.0] * 6))
        gains[band_index] = g
        self.config["eq_gains"] = gains
        self.opt_eq.set("カスタム")

    def apply_eq_gains(self, gains):
        for idx, g in enumerate(gains):
            self.engine.set_eq_band_gain(idx, g)
        self.config["eq_gains"] = list(gains)

    # -------------------------------------------------------------------------
    # Seek bar callbacks
    # -------------------------------------------------------------------------
    def on_seekbar_preview(self, sec):
        if sec is None:
            self.is_seeking = False
            return
        self.is_seeking = True
        txt = format_time(sec, include_ms=True)
        self.lbl_time.configure(text=txt)
        self.lbl_mini_time.configure(text=txt)

    def on_seekbar_seek(self, sec):
        if not self.engine.current_file:
            return
        self.engine.set_position_seconds(sec)
        self.refresh_position_display(sec)

    # -------------------------------------------------------------------------
    # Main-thread unified loop (40ms)
    # -------------------------------------------------------------------------
    def update_playback_timer(self):
        try:
            for _ in range(16):
                act = self.hotkey_mgr.poll_action()
                if not act:
                    break
                fn = self.action_dispatch.get(act)
                if fn:
                    try:
                        fn()
                    except Exception as e:
                        print("Action execution error:", e)

            if not self.is_seeking and self.engine.current_file:
                pos = self.engine.get_position_seconds()
                if self.loop_b is not None and pos >= self.loop_b:
                    pos = self.loop_a if self.loop_a is not None else 0.0
                    self.engine.set_position_seconds(pos)
                    if self.config.get("loop_beep", False):
                        try:
                            winsound.MessageBeep(winsound.MB_OK)
                        except Exception:
                            pass
                if not self.editing_time:
                    self.refresh_position_display(pos)

                playing = self.engine.is_playing()
                if playing != getattr(self, "_buttons_show_playing", False):
                    self.set_play_buttons(playing)
                    if not playing:
                        self.set_status("● 停止中", COLOR_TEXT_SUB)

                try:
                    self.render_acoustic_analyzer()
                except Exception:
                    pass

                now = time.monotonic()
                if playing and (now - self._last_autosave_time) > 30.0:
                    self._last_autosave_time = now
                    self.save_config()
        except Exception as e:
            print("Timer loop error:", e)
        finally:
            if not getattr(self, "_closing", False):
                self.after(40, self.update_playback_timer)

    # -------------------------------------------------------------------------
    # Window modes
    # -------------------------------------------------------------------------
    def toggle_always_on_top(self):
        self.config["always_on_top"] = not self.config.get("always_on_top", False)
        self.apply_always_on_top()

    def apply_always_on_top(self):
        val = self.config.get("always_on_top", False)
        self.attributes("-topmost", val or self.is_mini_mode)
        self.btn_top.configure(text="最前面: ON" if val else "最前面: OFF")
        self.set_btn_kind(self.btn_top, "primary" if val else "normal")

    def toggle_mini_mode(self):
        if self.editing_time:
            self.end_time_edit(commit=False)
        if not self.is_mini_mode:
            self.is_mini_mode = True
            self.state("normal")
            self.main_container.pack_forget()
            self.mini_container.pack(fill="both", expand=True)
            self.minsize(720, 180)
            self.geometry("900x205")
            self.attributes("-topmost", True)
        else:
            self.is_mini_mode = False
            self.mini_container.pack_forget()
            self.main_container.pack(fill="both", expand=True, padx=22, pady=10)
            self.minsize(1080, 760)
            self.apply_always_on_top()
            self.state("zoomed")
            self._analyzer_idle_drawn = False

    # -------------------------------------------------------------------------
    # Settings dialog (直接キーボード入力キャプチャ & 選択式 の完全両立)
    # -------------------------------------------------------------------------
    def show_settings_dialog(self):
        dlg = ctk.CTkToplevel(self)
        dlg.title(f"Dicta {self.version_str} — 設定・キー設定")
        dlg.geometry("960x820")
        dlg.minsize(840, 680)
        dlg.configure(fg_color=COLOR_BG_MAIN)
        dlg.transient(self)
        dlg.grab_set()

        bottom = ctk.CTkFrame(dlg, fg_color="#040811", height=64)
        bottom.pack(side="bottom", fill="x")

        tabview = ctk.CTkTabview(dlg, fg_color=COLOR_BG_CARD, segmented_button_selected_color=COLOR_CYAN_MID,
                                 segmented_button_selected_hover_color=COLOR_CYAN_DARK)
        tabview.pack(fill="both", expand=True, padx=18, pady=(8, 6))
        try:
            tabview._segmented_button.configure(font=self.F(16))
        except Exception:
            pass
        tab_keys = tabview.add("キー設定")
        tab_general = tabview.add("再生・コピー・安全設定")

        ctk.CTkLabel(tab_keys, text="各機能のショートカットキーを変更できます（キーボードを直接押すか、選択肢から指定できます）",
                     font=self.F(16)).pack(anchor="w", pady=(4, 6))

        scroll = ctk.CTkScrollableFrame(tab_keys, fg_color="#070C18")
        scroll.pack(fill="both", expand=True, padx=4, pady=4)

        current_hotkeys = dict(self.config.get("hotkeys", {}))
        key_vars = {}
        _ok, fb = self.hotkey_mgr.get_status()
        fb_actions = {a for a, _ in fb}

        def edit_key(action_key):
            ed = ctk.CTkToplevel(dlg)
            ed.title(f"キー変更: {HOTKEY_NAMES.get(action_key, action_key)}")
            ed.geometry("580x420")
            ed.configure(fg_color=COLOR_BG_MAIN)
            ed.transient(dlg)
            ed.grab_set()
            p = ctk.CTkFrame(ed, fg_color="transparent")
            p.pack(fill="both", expand=True, padx=24, pady=16)

            ctk.CTkLabel(p, text=f"機能: {HOTKEY_NAMES.get(action_key, action_key)}", font=self.F(17)).pack(anchor="w", pady=(0, 4))
            cur = current_hotkeys.get(action_key, "")
            _, _, canon_cur = parse_hotkey_string(cur)
            lbl_cur = ctk.CTkLabel(p, text=f"現在の設定: {canon_cur or '（なし）'}", font=self.F(16), text_color=COLOR_NEON_CYAN)
            lbl_cur.pack(anchor="w", pady=(0, 10))

            # --- 1. キーボード直接入力キャプチャ ---
            cap_box = ctk.CTkFrame(p, fg_color="#071224", corner_radius=10, border_width=2, border_color="#1E3A5F")
            cap_box.pack(fill="x", pady=(0, 12), ipady=2)
            ctk.CTkLabel(cap_box, text="⌨ キーボード直接入力（ここをクリックしてキーを押す）:", font=self.F(14), text_color=COLOR_TEXT_SUB).pack(anchor="w", padx=12, pady=(6, 2))

            btn_key_capture = ctk.CTkButton(
                cap_box,
                text="ここをクリックしてキーボードを押すと自動設定",
                font=self.F(15, bold=True),
                height=40,
                fg_color="#0C1B33",
                hover_color="#162E54",
                border_width=2,
                border_color=COLOR_NEON_CYAN,
                text_color=COLOR_TEXT_MAIN
            )
            btn_key_capture.pack(fill="x", padx=12, pady=(2, 8))

            # --- 2. 手動選択エリア ---
            ctk.CTkLabel(p, text="またはチェックボックスと一覧から手動で選択:", font=self.F(14), text_color=COLOR_TEXT_SUB).pack(anchor="w", pady=(2, 4))

            mf = ctk.CTkFrame(p, fg_color="transparent")
            mf.pack(fill="x", pady=2)
            chks = {}
            for m in ("Shift", "Ctrl", "Alt"):
                cb = ctk.CTkCheckBox(mf, text=m, width=95, font=self.F(16))
                cb.pack(side="left", padx=4)
                if m.upper() in cur.upper():
                    cb.select()
                chks[m] = cb

            kr = ctk.CTkFrame(p, fg_color="transparent")
            kr.pack(fill="x", pady=6)
            ctk.CTkLabel(kr, text="キー:", font=self.F(16)).pack(side="left", padx=4)
            keys_list = ["（なし）"] + [f"F{i}" for i in range(1, 13)] + list("ABCDEFGHIJKLMNOPQRSTUVWXYZ") + \
                list("0123456789") + ["SPACE", "UP", "DOWN", "LEFT", "RIGHT", "TAB", "ENTER", "HOME", "END", "PGUP", "PGDN", "INS", "DEL"]
            base_key = "（なし）"
            for pt in [x.strip().upper() for x in cur.replace(" ", "").split("+") if x.strip()]:
                if pt not in ("SHIFT", "CTRL", "ALT", "WIN"):
                    base_key = pt
            ok_ = ctk.CTkOptionMenu(kr, values=keys_list, width=170, height=36, font=self.F(16), dropdown_font=self.F(15),
                                    fg_color=COLOR_BG_BUTTON, button_color=COLOR_CYAN_MID)
            ok_.pack(side="left", padx=8)
            ok_.set(base_key if base_key in keys_list else "（なし）")

            # キーボードキャプチャのイベントリスナー
            is_capturing = [False]

            def start_capture():
                is_capturing[0] = True
                btn_key_capture.configure(
                    text="キーを押してください...（例: Ctrl+Alt+W）",
                    fg_color="#18365D",
                    border_color=COLOR_ISOLATOR_ON,
                    text_color=COLOR_ISOLATOR_ON
                )
                ed.focus_set()

            btn_key_capture.configure(command=start_capture)

            def on_key_press(event):
                if not is_capturing[0]:
                    return
                sym = event.keysym.upper()
                if sym in ("SHIFT_L", "SHIFT_R", "CONTROL_L", "CONTROL_R", "ALT_L", "ALT_R", "WIN_L", "WIN_R"):
                    s, c, a = get_current_modifiers()
                    parts = [m for m, val in [("Shift", s), ("Ctrl", c), ("Alt", a)] if val]
                    btn_key_capture.configure(text=" + ".join(parts) + " + ..." if parts else "キーを押してください...")
                    return "break"

                s, c, a = get_current_modifiers()
                key_map = {
                    "RETURN": "ENTER", "ESCAPE": "ESC", "BACKSPACE": "BACKSPACE",
                    "TAB": "TAB", "SPACE": "SPACE", "PRIOR": "PGUP", "NEXT": "PGDN",
                    "DELETE": "DEL", "INSERT": "INS", "UP": "UP", "DOWN": "DOWN",
                    "LEFT": "LEFT", "RIGHT": "RIGHT"
                }
                main_k = key_map.get(sym, sym)
                if len(main_k) == 1 and main_k.isalpha():
                    main_k = main_k.upper()
                elif main_k.startswith("F") and main_k[1:].isdigit():
                    pass

                if main_k in keys_list:
                    if s: chks["Shift"].select()
                    else: chks["Shift"].deselect()
                    if c: chks["Ctrl"].select()
                    else: chks["Ctrl"].deselect()
                    if a: chks["Alt"].select()
                    else: chks["Alt"].deselect()
                    ok_.set(main_k)

                    parts = [m for m, val in [("Shift", s), ("Ctrl", c), ("Alt", a)] if val] + [main_k]
                    res_str = "+".join(parts)
                    _, _, canon = parse_hotkey_string(res_str)
                    btn_key_capture.configure(
                        text=f"✓ 設定完了: {canon}（もう一度クリックで再入力）",
                        fg_color="#0B261A",
                        border_color=COLOR_PLAY_ACTIVE,
                        text_color=COLOR_PLAY_ACTIVE
                    )
                    is_capturing[0] = False
                return "break"

            ed.bind("<KeyPress>", on_key_press)

            def save_key():
                k = ok_.get()
                if k == "（なし）":
                    current_hotkeys[action_key] = ""
                    key_vars[action_key].set("（未設定）")
                else:
                    parts = [m for m in ("Shift", "Ctrl", "Alt") if chks[m].get()] + [k]
                    new_str = "+".join(parts)
                    _, _, canon = parse_hotkey_string(new_str)
                    for other, v in current_hotkeys.items():
                        if other != action_key and v and parse_hotkey_string(v)[2] == canon:
                            if not messagebox.askyesno("重複の確認", f"{canon} は「{HOTKEY_NAMES.get(other, other)}」に使われています。\nそちらを解除して、この機能に割り当てますか？", parent=ed):
                                return
                            current_hotkeys[other] = ""
                            key_vars[other].set("（未設定）")
                    current_hotkeys[action_key] = new_str
                    key_vars[action_key].set(canon)
                ed.destroy()

            br = ctk.CTkFrame(p, fg_color="transparent")
            br.pack(side="bottom", pady=4)
            self.btn(br, "この設定にする", save_key, size=15, height=38, width=140, kind="primary").pack(side="left", padx=6)
            self.btn(br, "閉じる", ed.destroy, size=15, height=38, width=90).pack(side="left", padx=6)

        for i, (action_key, action_name) in enumerate(HOTKEY_NAMES.items()):
            row = ctk.CTkFrame(scroll, fg_color="#111C33" if i % 2 == 0 else "#0B1324", corner_radius=8)
            row.pack(fill="x", pady=2, padx=4)
            ctk.CTkLabel(row, text=action_name, width=320, anchor="w", font=self.F(16)).pack(side="left", padx=10, pady=6)
            _, _, canon = parse_hotkey_string(current_hotkeys.get(action_key, ""))
            var = tk.StringVar(value=canon or "（未設定）")
            key_vars[action_key] = var
            ctk.CTkLabel(row, textvariable=var, width=220, anchor="w", font=self.F(15, mono=True),
                         text_color=COLOR_NEON_CYAN).pack(side="left", padx=4)
            if action_key in fb_actions:
                ctk.CTkLabel(row, text="[他アプリと重複]", font=self.F(13), text_color=COLOR_PAUSE_ACTIVE).pack(side="left", padx=4)
            self.btn(row, "変更", lambda ak=action_key: edit_key(ak), size=14, height=32, width=70, kind="primary", radius=6).pack(side="right", padx=6)

        def reset_defaults():
            if messagebox.askyesno("確認", "ショートカットキーを初期設定（Shift+Ctrl+Alt+W/E/Q/Z/X/A など）に戻しますか？", parent=dlg):
                current_hotkeys.clear()
                current_hotkeys.update(DEFAULT_CONFIG["hotkeys"])
                for ak in HOTKEY_NAMES:
                    key_vars[ak].set(parse_hotkey_string(current_hotkeys.get(ak, ""))[2] or "（未設定）")

        self.btn(tab_keys, "初期設定のキーに戻す", reset_defaults, size=15, height=38, width=260).pack(side="bottom", pady=6)

        # --- General tab ---
        pg = ctk.CTkScrollableFrame(tab_general, fg_color="transparent")
        pg.pack(fill="both", expand=True, padx=8, pady=6)

        def num_row(label, value, hint):
            r = ctk.CTkFrame(pg, fg_color="transparent")
            r.pack(fill="x", pady=6)
            ctk.CTkLabel(r, text=label, width=320, anchor="w", font=self.F(16)).pack(side="left")
            e = ctk.CTkEntry(r, width=90, height=36, font=self.F(16, mono=True))
            e.pack(side="left", padx=8)
            e.insert(0, str(value))
            ctk.CTkLabel(r, text=hint, font=self.F(14, bold=False), text_color=COLOR_TEXT_SUB).pack(side="left")
            return e

        e_rew = num_row("一時停止したときの自動巻き戻し", self.config.get("auto_rewind_sec", 1.0), "秒（推奨 1.0）")
        e_jr = num_row("巻き戻しの秒数", self.config.get("jump_rewind_sec", 5.0), "秒（推奨 5.0）")
        e_jf = num_row("早送りの秒数", self.config.get("jump_forward_sec", 5.0), "秒（推奨 5.0）")
        e_ss = num_row("速度変更＋／－ の変化刻み", self.config.get("speed_step", 0.05), "倍（推奨 0.05）")

        rf = ctk.CTkFrame(pg, fg_color="transparent")
        rf.pack(fill="x", pady=6)
        ctk.CTkLabel(rf, text="時間コピーの書式", width=320, anchor="w", font=self.F(16)).pack(side="left")
        cur_fmt = self.config.get("counter_format", "{time}")
        fmt_label = next((k for k, v in COUNTER_FORMATS.items() if v == cur_fmt), list(COUNTER_FORMATS)[0])
        opt_fmt = ctk.CTkOptionMenu(rf, values=list(COUNTER_FORMATS.keys()), width=230, height=36, font=self.F(15),
                                    dropdown_font=self.F(15), fg_color=COLOR_BG_BUTTON, button_color=COLOR_CYAN_MID)
        opt_fmt.pack(side="left", padx=8)
        opt_fmt.set(fmt_label)

        rp = ctk.CTkFrame(pg, fg_color="transparent")
        rp.pack(fill="x", pady=6)
        ctk.CTkLabel(rp, text="時間コピーの細かさ", width=320, anchor="w", font=self.F(16)).pack(side="left")
        seg_p = ctk.CTkSegmentedButton(rp, values=["秒まで（01:24:18）", "ミリ秒まで（01:24:18,492）"], font=self.F(15), height=36,
                                       selected_color=COLOR_CYAN_MID, unselected_color=COLOR_BG_BUTTON)
        seg_p.pack(side="left", padx=8)
        seg_p.set("ミリ秒まで（01:24:18,492）" if self.config.get("counter_precision") == "ms" else "秒まで（01:24:18）")

        def chk_row(text, val):
            r = ctk.CTkFrame(pg, fg_color="transparent")
            r.pack(fill="x", pady=6)
            cb = ctk.CTkCheckBox(r, text=text, font=self.F(16))
            cb.pack(side="left")
            if val:
                cb.select()
            return cb

        c_resume = chk_row("次回起動時に前回の音声ファイルと再生位置を自動で復元する", self.config.get("resume_last_file", True))
        c_cache = chk_row("安全キャッシュ再生（Googleドライブ等の音声をローカルSSD隔離してフリーズ防止）", self.config.get("use_ssd_cache", True))
        c_beep = chk_row("区間リピートで折り返すときに通知音を鳴らす", self.config.get("loop_beep", False))
        c_max = chk_row("起動時に全画面（最大化）で表示する", self.config.get("start_maximized", True))

        def save_and_close():
            try:
                self.config["auto_rewind_sec"] = max(0.0, float(e_rew.get()))
                self.config["jump_rewind_sec"] = max(0.1, float(e_jr.get()))
                self.config["jump_forward_sec"] = max(0.1, float(e_jf.get()))
                self.config["speed_step"] = max(0.01, float(e_ss.get()))
            except ValueError:
                messagebox.showerror("入力エラー", "秒数や刻みには半角数字を入力してください。", parent=dlg)
                return
            self.config["counter_format"] = COUNTER_FORMATS.get(opt_fmt.get(), "{time}")
            self.config["counter_precision"] = "ms" if seg_p.get().startswith("ミリ秒") else "sec"
            self.seg_copy.set("ミリ秒まで" if self.config["counter_precision"] == "ms" else "秒まで")
            self.config["resume_last_file"] = bool(c_resume.get())
            self.config["use_ssd_cache"] = bool(c_cache.get())
            self.config["loop_beep"] = bool(c_beep.get())
            self.config["start_maximized"] = bool(c_max.get())
            self.config["hotkeys"] = current_hotkeys
            self.refresh_jump_labels()
            self.setup_hotkeys()
            self.save_config()
            dlg.destroy()
            self.after(600, self.report_hotkey_status)
            self.flash_status("設定とショートカットキーを保存しました", COLOR_PLAY_ACTIVE, 3000)

        self.btn(bottom, "設定を保存して閉じる", save_and_close, size=16, height=42, width=210, kind="play").pack(side="right", padx=16, pady=10)
        self.btn(bottom, "キャンセル", dlg.destroy, size=15, height=42, width=120).pack(side="right", padx=6, pady=10)

    # -------------------------------------------------------------------------
    def on_close(self):
        if getattr(self, "_closing", False):
            return
        self._closing = True
        try:
            self.save_config()
        except Exception:
            pass
        try:
            self.hotkey_mgr.stop()
        except Exception:
            pass
        try:
            self.engine.close()
        except Exception:
            pass
        self.destroy()


if __name__ == "__main__":
    app = DictaApp()
    app.mainloop()
