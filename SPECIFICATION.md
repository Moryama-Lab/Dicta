# Dicta - Architecture & Technical Specification

> **AI・ソフトウェアエンジニア向け内部仕様書・設計思想ドキュメント**  
> 本ドキュメントは、AIアシスタント（Claude, GPT, Cursor等）や開発者が Dicta の内部構造、設計思想、C言語APIバインディング、原本保護規律、およびGUIライフサイクルを100%精緻に理解・拡張できるように記述された技術仕様書です。

---

## 1. プロジェクト概要と設計思想

### 1.1 開発の背景
従来のレガシーな文字起こし専用プレイヤー（2000年代初頭開発の32bitソフトウェア等）は、Windows 10/11における高DPI環境でのスケーリング崩れ、古いオーディオAPIによるレイテンシやクラッシュ、AAC/M4A/FLAC等の現代的コーデックへの非対応、大画面での操作性の悪化といった課題を抱えていました。
Dicta は、「文字起こしに最適化された操作感」「一時停止時の自動巻き戻し」「区間リピート」「文字入力と干渉しないグローバルホットキー（および6キー片手マクロキーボード連携）」の利便性を備えつつ、現代の最高水準のオーディオエンジニアリングとUI/UX設計でゼロからフルスクラッチ構築された完全オリジナルのソフトウェアです。

### 1.2 5大設計原則
1. **原本絶対保護（100% Read-Only Safety）**:
   - ユーザーの一次資料（ICレコーダー原本、インタビュー音声）を決して破損・改変・上書きしない。
2. **極低レイテンシ・ゼロフリーズ（Native C Engine）**:
   - PythonのGIL（Global Interpreter Lock）や高負荷な数値計算ライブラリ（librosa/scipy）に再生系を依存させず、BASS Native C DLL内で直接音声デコード・再生・エフェクト処理を完結させる。
3. **ユニバーサルデザイン・高視認性（Universal Design & High Contrast）**:
   - WCAG AAA準拠のダークネイビー＆ネオンシアン。長時間の作業でも眼精疲労が少なく、シークバー・タイムコード・各操作ボタンの視認性を極大化。
4. **非干渉グローバルホットキー（Non-Intrusive & Resilient Hotkeys）**:
   - テキスト入力作業を妨げない `Shift+Ctrl+Alt` プレフィックスを基本とし、OS標準API（`RegisterHotKey`）とポーリング（`GetAsyncKeyState`）の自動フォールバック自己修復を実装。
5. **ポータブル・プライバシー最優先（Portable & Zero Tracking）**:
   - 外部ネットワーク通信は一切遮断。自己完結型ディレクトリ構成。

---

## 2. システム構成とファイルツリー

```
dicta/
├── dicta.py             # メインアプリケーション（GUI、イベントループ、設定管理、解析描画）
├── bass_engine.py       # BASS Native C API ctypesバインディング＆再生エンジン
├── hotkey_manager.py    # 低遅延・自己修復型グローバルホットキー監視マネージャー
├── register_open_with.py# Windows 右クリック「プログラムから開く」登録・解除スクリプト
├── config.default.json  # 初期配布用デフォルト設定テンプレート（個人情報ゼロ）
├── config.json          # ユーザー環境ローカル設定ファイル（自動生成・Git除外）
├── README.md            # 一般利用者向け導入・操作ガイド
├── SPECIFICATION.md     # 本技術仕様書
├── dicta.ico            # Windows用マルチ解像度アプリアイコン（太枠ネオンシアン＋発光グロー）
├── dicta_logo.png       # アプリケーションヘッダー用ロゴ画像
├── 起動_Dicta.bat        # ワンクリック起動バッチ
├── bass.dll             # 64bit BASS Core Native DLL (v2.4.17)
├── bass_fx.dll          # 64bit BASS_FX DSP/Tempo/Pitch Native DLL (v2.4.12)
├── bass_aac.dll         # 64bit BASS_AAC Advanced Audio Coding Plugin (v2.4.5)
└── bassflac.dll         # 64bit BASS_FLAC Lossless Audio Plugin (v2.4.5)
```

---

## 3. オーディオエンジン設計 (`bass_engine.py`)

### 3.1 BASS Native C API の統合
- `ctypes.WinDLL` を通じて `bass.dll` およびプラグインDLLをロード。
- `BASS_PluginLoad` により `bass_aac.dll`（m4a/aac/mp4）および `bassflac.dll`（flac）を起動時に透過的プラグインとして登録。
- 標準の `BASS_StreamCreateFile` は行わず、再生速度変更（テンポ）とピッチシフトをリアルタイムかつ独立に処理するため、以下のパイプラインを構築：

```
[Audio File on Disk]
        │ (Read-Only Stream)
        ▼
   BASS_StreamCreateFile(..., BASS_STREAM_DECODE | BASS_STREAM_PRESCAN)
        │ (Raw PCM Decode Stream)
        ▼
   BASS_FX_TempoCreate(decode_handle, BASS_FX_FREEDSP)
        │ (Tempo / Pitch Shift / DSP Effects Stream)
        ├──────► BASS_ChannelSetAttribute(tempo_handle, BASS_ATTRIB_TEMPO, ...)
        ├──────► BASS_ChannelSetAttribute(tempo_handle, BASS_ATTRIB_TEMPO_PITCH, ...)
        ├──────► BASS_ChannelSetFX(tempo_handle, BASS_FX_BFX_PEAKEQ, ...)  [6-Band EQ]
        ├──────► BASS_ChannelSetFX(tempo_handle, BASS_FX_BFX_BQF, ...)     [Cascade BPF]
        │
        ▼
   BASS_ChannelPlay(tempo_handle, FALSE) ──► DirectSound / WASAPI Output
```

### 3.2 100% 原本保護の実装原理
- **ファイルオープンモード**: `BASS_StreamCreateFile` 呼び出し時、Windows APIレベルで `GENERIC_READ` かつ共有モード `FILE_SHARE_READ | FILE_SHARE_WRITE` を要求。OS側でファイルを排他ロックせず、一切の書き込みハンドルを作成しない。
- **一時ファイル・変更の非存在**: タグ書き換えやメタデータ編集関数はエンジン内に定義すら存在しない。
- **安全なシーク**: `BASS_ChannelSetPosition` はデコードポインタのオフセット移動のみを行い、ディスクアクセスは純粋なシーケンシャル/ランダムリードにとどまる。

### 3.3 自動巻き戻し（Auto-Rewind）ロジック
- 一時停止（Pause）時、現在の再生位置（秒）を `last_pause_pos` に記録。
- 再生（Play）時、`auto_rewind_sec`（例: 1.0秒）が設定されている場合、直前の位置から `target = max(0, last_pause_pos - auto_rewind_sec)` を計算し、即座にシークしてから再生を開始。
- これにより、聞き取り作業を再開した際に直前の2〜3単語が自然に耳に入り、思考の中断を防止。

### 3.4 リアルタイム音響解析（FFT）と周波数アイソレーター
- **解析データ取得**: 40msごとのGUI描画ループ内にて、`BASS_ChannelGetData(tempo_handle, buffer, BASS_DATA_FFT2048)` を呼び出し。
  - C言語DLLのリングバッファから、現在スピーカーから出力されている瞬間の周波数スペクトラム（1024ビン）を0.05ms未満で取得。
  - Pythonのメモリを一切圧迫しないゼロコピーに近い超高速描画。
- **3種のリアルタイム解析モード**:
  1. **波形＋スペクトル (`spectrum_wave`)**: 44バンド対数周波数バーグラフ＋88点オシロスコープ波形。
  2. **倍音・ピーク (`formant_peak`)**: 母音・子音帯域ガイド背景、連続スペクトル塗りつぶし曲線、減衰付きピークホールド残像曲線＆最大声紋ピーク周波数マーカー（`▼ ピーク Hz`）、上部対称エンベロープ波形。追加のFFT計算負荷ゼロで描画。
  3. **スペクトログラム (`spectrogram`)**: 時間×周波数×強度カラーの2Dウォーターフォール声紋表示。
- **特定周波数アイソレーター（BASS_FX_BFX_BQF）＆ 黄色枠ドラッグ伸縮**:
  - 双二次フィルター（Biquad Filter）のバンドパスモード（`BASS_BFX_BQF_BANDPASS`）を2段カスケード接続。
  - 選択された中心周波数 $f_0$ と帯域幅（オクターブ幅 `bw`）に基づき、周囲の環境ノイズを急峻に減衰させ、目的の音声帯域のみを透過。
  - 解析Canvas上の黄色い選択枠の左右端（グリップハンドル付き）をマウスでドラッグすることで、下限周波数 $f_{\text{lo}}$・上限周波数 $f_{\text{hi}}$ から中心周波数 $f_0 = \sqrt{f_{\text{lo}} \cdot f_{\text{hi}}}$ とオクターブ幅 $bw = \log_2(f_{\text{hi}} / f_{\text{lo}})$ をリアルタイム逆算し、直感的に抽出範囲を伸縮可能。

---

## 4. GUI & 描画アーキテクチャ (`dicta.py`)

### 4.1 CustomTkinterの採用とレスポンシブ設計
- Tkinterをベースにしつつ、Windows 11のFluentデザインに調和するモダンなUIライブラリ `customtkinter` を採用。
- ウィンドウレイアウトは上部カウンター・極太シークバー・トランスポート列と、下部2カラムスタジオ構成（左：精密音響解析＆周波数アイソレーター、右：再生速度・ピッチ・区間リピート・6バンドイコライザー・マスター音量）。

### 4.2 高視認性・アンチエイリアスシークバー (`MainSeekBar`)
- Canvas上に直接描画される独自カスタムウィジェット。
- **スムーズノブ（Thumb）の描画**:
  - Canvasの標準 `create_oval` では生じてしまう円周のジャギー（粗いフチ）を排除するため、Pillow（PIL）を用いて4倍解像度（Super-sampling）で真円をアンチエイリアス描画し、`ImageTk.PhotoImage` としてCanvasに配置。ホバー時も視認性を損なう黄色変化を行わず、常に高コントラストなネオンシアン枠＋ホワイト円を維持。
- **直結型しおり（Bookmark）表示**:
  - 記録されたしおりは、シークバー上にゴールドイエロー（`#FFC820`）の細い縦線として直接描画。余計なアイコン（★等）を排除し、タイムラインを一望可能。
- **区間リピート（A-B Loop）の視覚化**:
  - A点からB点までの間を、鮮やかなレッド（`#FF3355`）の帯および境界線としてシークバー内にオーバーレイ描画。

### 4.3 ウィンドウライフサイクルとゼロラグ全画面（最大化）起動
- **CustomTkinter内部 `mainloop()` の二重描画・最大化解除バグのバイパス**:
  - `customtkinter.CTk` の標準実装（`ctk_tk.py`）では、`mainloop()` 突入時に `if not self._window_exists:` 分岐に入り、`_windows_set_titlebar_color()` 内で強制的に `withdraw()` ➔ `update()` ➔ `deiconify()`（`"normal"` 状態への復帰）を実行する仕様となっている。そのため、`__init__` 内で単純に `self.state("zoomed")` を呼ぶだけでは `mainloop()` 開始直後に通常ウィンドウへ引き戻され、2段階描画によるカクつきが発生する。
  - Dicta では、`__init__` の末尾にてダークタイトルバー属性（`DwmSetWindowAttribute`）を適用した上で `self._window_exists = True` を先行セットし、`self.update_idletasks()` 後に直接 `self.state("zoomed")` を呼び出す。これにより、`mainloop()` 突入時の冗長な再非表示・通常復帰を100%バイパスし、最初から画面全体（最大化状態）のままカクつきゼロで一発表示される。
- **リサイズ時のレイアウトスラッシング防止と固定セル設計**:
  - `<Configure>` イベント内での動的 `CTkLabel.configure(wraplength=...)` 呼び出しによる親フレームへの再帰的リサイズ連鎖（Layout Thrashing）を排除し、シークバーの `<Configure>` も横幅変化量が閾値（2px）以上のときのみ再計算を行うデバウンス処理を導入。
  - 特大タイムコード表示部は、固定サイズセル（`width=460, height=84` かつ `pack_propagate(False)`）内に配置。クリックしてインライン編集（`CTkEntry`）へ移行しても外枠サイズが1ピクセルも変動せず、画面全体のかくつき・ブレを完全排除。また、編集枠外をクリックした際はグローバル `<Button-1>` イベントを通じて即座に変更をキャンセル・非表示化する直感的なUXを実装。
- **トランスポート操作ボタンとコピーボタンの統一設計**:
  - 最左端の「⏮ 最初から」ボタンと右端の「しおり追加」「しおり全消去」ボタンは、同一サイズ（`width=155, height=48, size=16`）に完全統一され、鮮明なパープル／アンバー／ローズのカラーコードで直感的に識別可能。
  - 主要操作である「◀◀ 5秒戻る」「▶ 再生」「▶▶ 5秒進む」の3ボタンは、`grid_columnconfigure(..., weight=1, uniform="main_transport")` により中央で均等に広がる均一グリッドとして配置。
  - 「📋 時間コピー」と「⏱ 区間コピー」は同一のアクセントスタイル（ダークネイビー `#16243D` ＆ ネオンシアン枠 `#00F0FF`、幅160px）に統一。どちらのボタンを押した際も必ず「✓ コピー完了！」のグリーンフラッシュフィードバック（1.2秒）が表示された後、元のスタイルに自動復帰。

---

## 5. グローバルホットキーマネージャー (`hotkey_manager.py`)

### 5.1 二重化アーキテクチャ（Dual Hooking System）
Wordやブラウザが最前面にある状態でもバックグラウンドでショートカットを補足するため、以下のハイブリッド構成を採用：

1. **主系: Win32 `RegisterHotKey` (メッセージキュー方式)**:
   - バックグラウンドスレッドでOSからの `WM_HOTKEY` を待機。CPU使用率0.00%。
2. **副系: Win32 `GetAsyncKeyState` (ポーリング自己修復方式)**:
   - 他の常駐ソフトウェアが既に同一のホットキーを独占・競合している場合、`RegisterHotKey` の失敗を検知し、自動的に `GetAsyncKeyState` による15msインターバルの高精度ポーリングにフォールバック。

### 5.2 選択式キー設定ダイアログ（Checkbox + Dropdown Selection & Large Tab UI）
- 設定ダイアログ上部には高視認性の大型2連タブボタン（高さ52px・20pt太字：「⌨ キー設定」「⚙ 再生・コピー・安全設定」）を配置。
- 「変更」ボタンを押すと、修飾キー（`Shift`, `Ctrl`, `Alt` の3つの明確なチェックボックス）とメインキー（F1〜F12、英数字、方向キー、テンキーNumPad、無変換/変換などを網羅したドロップダウンメニュー）の組み合わせによる選択式エディタが起動。
- マウス操作のみで誰でも100%確実に好みの組み合わせ（単体キー、`Shift+Ctrl+Alt+任意のキー` 等）を設定可能。
- リアルタイムで「設定プレビュー（例: `Ctrl + Shift + F5`）」が表示され、他の機能との重複が存在する場合は警告メッセージが即時提示される安全設計。

---

## 6. Windows シェル連携 ＆ マルチモニター最適化

### 6.1 Windows「プログラムから開く」への安全な登録 (`register_open_with.py`)
- 音源ファイル（.mp3, .wav, .m4a, .aac, .flac, .wma, .ogg 等）の右クリックメニュー「プログラムから開く」の選択肢一覧に Dicta を登録。
- **絶対規律**: ユーザーの「既定のアプリ（デフォルトプレーヤー）」は一切変更せず、`HKEY_CURRENT_USER\Software\Classes\Applications\Dicta.exe` および各拡張子の `OpenWithList\Dicta.exe` のみに登録。
- GUI設定画面（「⚙ 再生・コピー・安全設定」タブ）から現在の登録状況をリアルタイム確認でき、ワンクリックで登録／解除が可能。
- `dicta.py` は `sys.argv[1]` のコマンドライン引数を解釈し、エクスプローラーから選択された音源を起動直後に自動ロード。

### 6.2 マルチモニター（画面拡張）におけるDPI安定化
- ノートPC等の高スケーリング画面（125%〜150%）と、外付けの大型モニター（100%）間でウィンドウを移動した際、CustomTkinterがPer-Monitor DPI変更を検知してウィンドウサイズ（geometry）を強制再計算・縮小拡大してしまう現象を抑止。
- `ctypes.windll.shcore.SetProcessDpiAwareness(1)`（System DPI Aware）および `ctk.deactivate_automatic_dpi_awareness()` の適用により、Windows OSのDWM側で単一空間スケーリングを完結させ、モニター跨ぎ時のチラつき・カクつき・サイズ急変を完全に防止。

### 6.3 高視認性ネオンアイコン (`dicta.ico` / `dicta_logo.png`)
- 黒背景のデスクトップ環境でも埋もれず明瞭に視認できるよう、外枠に幅24pxの鮮明なネオンシアン（`#00F5FF`）ソリッド境界線と多層発光グロー（Cyan Glow）を施したマルチ解像度ICO（256, 128, 64, 48, 32, 16）を生成。

---

## 7. 設定ファイル管理 (`config.json` / `config.default.json`)

### 7.1 スキーマ仕様
```json
{
  "config_version": 3,
  "theme": "dark",
  "always_on_top": false,
  "start_maximized": true,
  "use_ssd_cache": true,
  "loop_beep": false,
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
  "resume_last_file": true,
  "last_file": "",
  "last_position": 0.0,
  "eq_preset": "クリアボイス（会話強調）",
  "eq_gains": [-4.0, -1.0, 2.0, 6.0, 3.0, -2.0],
  "bookmarks_dict": {},
  "hotkeys": {
    "play_pause": "Shift+Ctrl+Alt+W",
    ...
  }
}
```

### 7.2 配布・共有時のセキュリティ規律
- `config.json` はローカル環境固有の最終再生ファイルパス（`last_file`）や個別音声のブックマーク履歴（`bookmarks_dict`）を保持するため、**Git管理から除外（.gitignore）**。
- 配布リポジトリには `config.default.json` のみを同梱し、アプリ起動時に `config.json` が存在しない場合は `config.default.json` から安全に自動生成される。これにより、開発者・配布者の個人ファイルパスや研究情報が第三者に漏洩するリスクを恒久的にゼロとする。

---

## 8. 開発・クレジット
- **Author & Developer**: **Moryama-Lab** & **Google Antigravity (Gemini 4 Argon)**
