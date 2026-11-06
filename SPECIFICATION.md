# Dicta - Architecture & Technical Specification

> **AI・ソフトウェアエンジニア向け内部仕様書・設計思想ドキュメント**  
> 本ドキュメントは、AIアシスタント（Claude, GPT, Cursor等）や開発者が Dicta の内部構造、設計思想、C言語APIバインディング、原本保護規律、およびGUIライフサイクルを100%精緻に理解・拡張できるように記述された技術仕様書です。

---

## 1. プロジェクト概要と設計思想

### 1.1 開発の背景
長年、日本の学術・司法・医療・メディア界隈でデファクトスタンダードとして使用されてきた文字起こし専用プレイヤー「Okoshiyasu2」（2000年代初頭開発、32bit Delphi製）は、Windows 10/11における高DPI環境でのスケーリング崩れ、DirectSound / WaveOutの陳腐化によるレイテンシやクラッシュ、AAC/M4A等の現代的コーデックへの非対応、大画面での操作性の悪化といった課題を抱えていました。
Dicta は、Okoshiyasu2の持つ「テープ起こしに最適化された操作感」「自動巻き戻し」「区間リピート」「グローバルホットキー」の利便性を完全に継承しつつ、現代の最高水準のオーディオエンジニアリングとUI/UX設計でフルスクラッチ再構築されたソフトウェアです。

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
├── config.default.json  # 初期配布用デフォルト設定テンプレート（個人情報ゼロ）
├── config.json          # ユーザー環境ローカル設定ファイル（自動生成・Git除外）
├── README.md            # 一般利用者向け導入・操作ガイド
├── SPECIFICATION.md     # 本技術仕様書
├── dicta.ico            # Windows用マルチ解像度アプリアイコン
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
- **特定周波数アイソレーター（BASS_FX_BFX_BQF）**:
  - 双二次フィルター（Biquad Filter）のバンドパスモード（`BASS_BFX_BQF_BANDPASS`）を2段カスケード接続。
  - 選択された中心周波数 $f_0$ と帯域幅（Q値）に基づき、周囲の環境ノイズを最大 -48dB 急峻に減衰させ、目的の音声帯域のみを透過。

---

## 4. GUI & 描画アーキテクチャ (`dicta.py`)

### 4.1 CustomTkinterの採用とレスポンシブ設計
- Tkinterをベースにしつつ、Windows 11のFluentデザインに調和するモダンなUIライブラリ `customtkinter` を採用。
- ウィンドウレイアウトは2カラム構成：
  - **左カラム**: メイン操作部（特大タイムコード、超太シークバー、主要再生ボタン群、速度・ピッチ・音量スライダー、6バンドイコライザー、サブ操作ボタン）。
  - **右カラム**: 音響解析スタジオ（オシロスコープ/スペクトラム/声紋ウォーターフォール切替Canvas、周波数アイソレーター操作パネル、ブックマーク一覧）。

### 4.2 高視認性・アンチエイリアスシークバー (`SmoothSeekBar`)
- Canvas上に直接描画される独自カスタムウィジェット。
- **スムーズノブ（Thumb）の描画**:
  - Canvasの標準 `create_oval` では生じてしまう円周のジャギー（粗いフチ）を排除するため、Pillow（PIL）を用いて4倍解像度（Super-sampling）で真円をアンチエイリアス描画し、`ImageTk.PhotoImage` としてCanvasに配置。Retina級の超滑らかなノブ表示を実現。
- **直結型しおり（Bookmark）表示**:
  - 記録されたしおりは、シークバー上にゴールドイエロー（`#FFC820`）の細い縦線として直接描画。余計なアイコン（★等）を排除し、タイムラインを一望可能。
- **区間リピート（A-B Loop）の視覚化**:
  - A点からB点までの間を、鮮やかなレッド（`#FF3355`）の帯および境界線としてシークバー内にオーバーレイ描画。

### 4.3 ウィンドウライフサイクルと安定起動
- **初期化シーケンス**:
  - ウィンドウは標準のジオメトリで作成後、ユーザー設定（`start_maximized: true`）に応じて `self.state("zoomed")` を安全に呼び出し。
  - Tkinterの内部ウィンドウハンドル不整合を防ぐため、安易な `withdraw()` / `deiconify()` の非同期連打を排除し、初速かつ確実にOSのデスクトップ上にアクティブウィンドウとして展開されるよう最適化。

---

## 5. グローバルホットキーマネージャー (`hotkey_manager.py`)

### 5.1 二重化アーキテクチャ（Dual Hooking System）
Wordやブラウザが最前面にある状態でもバックグラウンドでショートカットを補足するため、以下のハイブリッド構成を採用：

1. **主系: Win32 `RegisterHotKey` (メッセージキュー方式)**:
   - バックグラウンドスレッドで非表示メッセージ専用ウィンドウ（`HWND_MESSAGE`）を生成し、`GetMessageW` ループでOSからの `WM_HOTKEY` を待機。CPU使用率0.00%。
2. **副系: Win32 `GetAsyncKeyState` (ポーリング自己修復方式)**:
   - 他の常駐ソフトウェアが既に同一のホットキーを独占・競合している場合、`RegisterHotKey` の失敗を検知し、自動的に `GetAsyncKeyState` による45msインターバルの高精度ポーリングにフォールバック。
   - ユーザー側で特別な再起動や権限昇格を行わなくても、常に確実にホットキーが反応する自己修復性を実現。

### 5.2 直接キー入力キャプチャ（Direct Key Capture）
- 設定画面上の「⌨ 手元のキーを押して設定」ボタンを押すと、モーダル入力待機状態へ移行。
- フォーカスイベントおよび `GetAsyncKeyState` による装飾キー（Shift, Ctrl, Alt）と通常キーの同時押下を検知し、ユーザーが手元で押した組み合わせ（例: `Shift+Ctrl+Alt+P`）を即座に文字列パースして設定に反映。

---

## 6. 設定ファイル管理 (`config.json` / `config.default.json`)

### 6.1 スキーマ仕様
```json
{
  "config_version": 3,
  "theme": "dark",
  "always_on_top": true,
  "start_maximized": true,
  "use_ssd_cache": true,
  "loop_beep": false,
  "analyzer_mode": "spectrum_wave",
  "counter_format": "{time}",
  "counter_precision": "sec",
  "volume": 0.8,
  "speed": 1.0,
  "pitch": 0.0,
  "speed_step": 0.05,
  "auto_rewind_sec": 1.0,
  "jump_rewind_sec": 5.0,
  "jump_forward_sec": 5.0,
  "resume_last_file": false,
  "last_file": "",
  "last_position": 0.0,
  "eq_preset": "フラット（標準）",
  "eq_gains": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
  "bookmarks_dict": {},
  "hotkeys": {
    "play_pause": "Shift+Ctrl+Alt+W",
    ...
  }
}
```

### 6.2 配布・共有時のセキュリティ規律
- `config.json` はローカル環境固有の最終再生ファイルパス（`last_file`）や個別音声のブックマーク履歴（`bookmarks_dict`）を保持するため、**Git管理から除外（.gitignore）**。
- 配布リポジトリには `config.default.json` のみを同梱し、アプリ起動時に `config.json` が存在しない場合は `config.default.json` から安全に自動生成される。これにより、開発者・配布者の個人ファイルパスや研究情報が第三者に漏洩するリスクを恒久的にゼロとする。
