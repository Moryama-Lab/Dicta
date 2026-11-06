import os
import sys
import math
import shutil
import hashlib
import tempfile
import threading
import ctypes
from ctypes import wintypes

# BASS Constants & Configuration Flags
BASS_OK = 0
BASS_CONFIG_BUFFER = 0
BASS_CONFIG_UPDATEPERIOD = 1
BASS_CONFIG_DEV_DEFAULT = 36

BASS_ACTIVE_STOPPED = 0
BASS_ACTIVE_PLAYING = 1
BASS_ACTIVE_STALLED = 2
BASS_ACTIVE_PAUSED = 3

BASS_POS_BYTE = 0
BASS_STREAM_PRESCAN = 0x20000
BASS_STREAM_DECODE = 0x200000
BASS_UNICODE = 0x80000000
BASS_FX_FREESOURCE = 0x10000

BASS_ATTRIB_VOL = 2
BASS_ATTRIB_TEMPO = 0x10000
BASS_ATTRIB_TEMPO_PITCH = 0x10001
BASS_ATTRIB_TEMPO_FREQ = 0x10002

BASS_FX_BFX_PEAKEQ = 0x10004
BASS_FX_BFX_BQF = 0x10013
BASS_BFX_BQF_BANDPASS = 2

# FFT & Waveform Data Flags
BASS_DATA_FLOAT = 0x40000000
BASS_DATA_FFT1024 = 0x80000001
BASS_DATA_FFT2048 = 0x80000002


class BASS_BFX_PEAKEQ(ctypes.Structure):
    _fields_ = [
        ("lBand", ctypes.c_int),
        ("fBandwidth", ctypes.c_float),
        ("fQ", ctypes.c_float),
        ("fCenter", ctypes.c_float),
        ("fGain", ctypes.c_float),
        ("lChannel", ctypes.c_int),
    ]


class BASS_BFX_BQF(ctypes.Structure):
    _fields_ = [
        ("lFilter", ctypes.c_int),
        ("fCenter", ctypes.c_float),
        ("fGain", ctypes.c_float),
        ("fBandwidth", ctypes.c_float),
        ("fQ", ctypes.c_float),
        ("fS", ctypes.c_float),
        ("lChannel", ctypes.c_int),
    ]


class BassAudioEngine:
    """
    High-stability 64-bit BASS + BASS_FX Audio Engine for Dicta.
    Features:
      - BASS_STREAM_PRESCAN & BASS_FX_FREESOURCE for leak-free, accurate VBR seeking
      - Local SSD caching to isolate from Google Drive / cloud virtual FS I/O stalls
      - Real-time C-native FFT Spectrum & Waveform extraction (zero memory overhead)
      - Dual-stage Biquad Band-Pass Frequency Isolator for extracting target voice frequencies
    """
    def __init__(self, base_dir=None):
        if base_dir is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        self.base_dir = base_dir
        self._lock = threading.RLock()

        bass_dll_path = os.path.join(base_dir, "bass.dll")
        bass_fx_dll_path = os.path.join(base_dir, "bass_fx.dll")

        if not os.path.exists(bass_dll_path) or not os.path.exists(bass_fx_dll_path):
            raise FileNotFoundError("BASS DLLs not found in " + base_dir)

        self.bass = ctypes.WinDLL(bass_dll_path)
        self.bass_fx = ctypes.WinDLL(bass_fx_dll_path)

        # Configure ctypes signatures
        self.bass.BASS_SetConfig.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
        self.bass.BASS_SetConfig.restype = wintypes.BOOL

        self.bass.BASS_Init.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, wintypes.HWND, ctypes.c_void_p]
        self.bass.BASS_Init.restype = wintypes.BOOL
        self.bass.BASS_Free.restype = wintypes.BOOL
        self.bass.BASS_ErrorGetCode.restype = ctypes.c_int

        self.bass.BASS_PluginLoad.argtypes = [ctypes.c_char_p, ctypes.c_ulong]
        self.bass.BASS_PluginLoad.restype = ctypes.c_ulong

        self.bass.BASS_StreamCreateFile.argtypes = [wintypes.BOOL, ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_ulong]
        self.bass.BASS_StreamCreateFile.restype = ctypes.c_ulong

        self.bass.BASS_StreamFree.argtypes = [ctypes.c_ulong]
        self.bass.BASS_StreamFree.restype = wintypes.BOOL

        self.bass.BASS_ChannelPlay.argtypes = [ctypes.c_ulong, wintypes.BOOL]
        self.bass.BASS_ChannelPlay.restype = wintypes.BOOL

        self.bass.BASS_ChannelPause.argtypes = [ctypes.c_ulong]
        self.bass.BASS_ChannelPause.restype = wintypes.BOOL

        self.bass.BASS_ChannelStop.argtypes = [ctypes.c_ulong]
        self.bass.BASS_ChannelStop.restype = wintypes.BOOL

        self.bass.BASS_ChannelIsActive.argtypes = [ctypes.c_ulong]
        self.bass.BASS_ChannelIsActive.restype = ctypes.c_ulong

        self.bass.BASS_ChannelGetLength.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
        self.bass.BASS_ChannelGetLength.restype = ctypes.c_uint64

        self.bass.BASS_ChannelGetPosition.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
        self.bass.BASS_ChannelGetPosition.restype = ctypes.c_uint64

        self.bass.BASS_ChannelSetPosition.argtypes = [ctypes.c_ulong, ctypes.c_uint64, ctypes.c_ulong]
        self.bass.BASS_ChannelSetPosition.restype = wintypes.BOOL

        self.bass.BASS_ChannelBytes2Seconds.argtypes = [ctypes.c_ulong, ctypes.c_uint64]
        self.bass.BASS_ChannelBytes2Seconds.restype = ctypes.c_double

        self.bass.BASS_ChannelSeconds2Bytes.argtypes = [ctypes.c_ulong, ctypes.c_double]
        self.bass.BASS_ChannelSeconds2Bytes.restype = ctypes.c_uint64

        self.bass.BASS_ChannelSetAttribute.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_float]
        self.bass.BASS_ChannelSetAttribute.restype = wintypes.BOOL

        self.bass.BASS_ChannelGetAttribute.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.POINTER(ctypes.c_float)]
        self.bass.BASS_ChannelGetAttribute.restype = wintypes.BOOL

        self.bass.BASS_ChannelSetFX.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int]
        self.bass.BASS_ChannelSetFX.restype = ctypes.c_ulong

        self.bass.BASS_ChannelRemoveFX.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
        self.bass.BASS_ChannelRemoveFX.restype = wintypes.BOOL

        self.bass.BASS_FXSetParameters.argtypes = [ctypes.c_ulong, ctypes.c_void_p]
        self.bass.BASS_FXSetParameters.restype = wintypes.BOOL

        self.bass.BASS_FXGetParameters.argtypes = [ctypes.c_ulong, ctypes.c_void_p]
        self.bass.BASS_FXGetParameters.restype = wintypes.BOOL

        self.bass.BASS_ChannelGetData.argtypes = [ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong]
        self.bass.BASS_ChannelGetData.restype = ctypes.c_ulong

        self.bass_fx.BASS_FX_GetVersion.restype = ctypes.c_ulong
        self.bass_fx.BASS_FX_TempoCreate.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
        self.bass_fx.BASS_FX_TempoCreate.restype = ctypes.c_ulong

        self.bass_fx.BASS_FX_GetVersion()

        # Pre-init stability configuration
        self.bass.BASS_SetConfig(BASS_CONFIG_DEV_DEFAULT, 1)
        self.bass.BASS_SetConfig(BASS_CONFIG_BUFFER, 500)
        self.bass.BASS_SetConfig(BASS_CONFIG_UPDATEPERIOD, 40)

        self.bass.BASS_Init(-1, 44100, 0, 0, None)

        for plugin in ["bass_aac.dll", "bassflac.dll"]:
            p_path = os.path.join(base_dir, plugin)
            if os.path.exists(p_path):
                self.bass.BASS_PluginLoad(p_path.encode("utf-8"), 0)

        self.tempo_stream = 0
        self.current_file = None
        self.active_local_path = None
        self.is_cached_copy = False
        self.duration_seconds = 0.0
        self.volume = 1.0

        # EQ bands
        self.eq_fx_handle = 0
        self.eq_bands = [120.0, 200.0, 400.0, 1200.0, 4000.0, 10000.0]

        # Band-Pass Frequency Isolator handles (2-stage cascade for steep surgical isolation)
        self.isolator_fx1 = 0
        self.isolator_fx2 = 0
        self.isolator_enabled = False
        self.isolator_center_hz = 1200.0
        self.isolator_bw_oct = 1.2

        # Pre-allocated fixed C buffers for zero-allocation real-time FFT & Waveform analysis
        self._fft_buf = (ctypes.c_float * 1024)()
        self._wave_buf = (ctypes.c_float * 512)()

        # Setup local SSD cache directory
        self.cache_dir = os.path.join(tempfile.gettempdir(), "dicta_ssd_cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self._cleanup_old_cache()

    def _cleanup_old_cache(self, max_files=3):
        try:
            files = [
                os.path.join(self.cache_dir, f)
                for f in os.listdir(self.cache_dir)
                if os.path.isfile(os.path.join(self.cache_dir, f))
            ]
            files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            for old_f in files[max_files:]:
                try:
                    os.remove(old_f)
                except Exception:
                    pass
        except Exception:
            pass

    def _prepare_safe_local_path(self, file_path, enable_cache=True):
        self.is_cached_copy = False
        if not enable_cache:
            return file_path
        try:
            file_size = os.path.getsize(file_path)
            if file_size <= 350 * 1024 * 1024:
                stat = os.stat(file_path)
                key_src = f"{file_path}|{stat.st_size}|{int(stat.st_mtime)}"
                file_hash = hashlib.md5(key_src.encode("utf-8", errors="ignore")).hexdigest()[:12]
                ext = os.path.splitext(file_path)[1].lower()
                cached_path = os.path.join(self.cache_dir, f"dicta_{file_hash}{ext}")

                if not os.path.exists(cached_path) or os.path.getsize(cached_path) != file_size:
                    shutil.copy2(file_path, cached_path)
                else:
                    os.utime(cached_path, None)

                self._cleanup_old_cache(max_files=3)
                self.is_cached_copy = True
                return cached_path
        except Exception as e:
            print("Local cache fallback to direct path:", e)
        return file_path

    def load_file(self, file_path, use_local_cache=True):
        with self._lock:
            self.stop()
            if self.tempo_stream:
                self.bass.BASS_StreamFree(self.tempo_stream)
                self.tempo_stream = 0
                self.eq_fx_handle = 0
                self.isolator_fx1 = 0
                self.isolator_fx2 = 0

            if not os.path.exists(file_path):
                raise FileNotFoundError(f"Audio file not found: {file_path}")

            play_path = self._prepare_safe_local_path(file_path, enable_cache=use_local_cache)
            self.active_local_path = play_path

            flags = BASS_STREAM_DECODE | BASS_STREAM_PRESCAN | BASS_UNICODE
            path_wchar = ctypes.c_wchar_p(play_path)

            decode_stream = self.bass.BASS_StreamCreateFile(
                False, ctypes.cast(path_wchar, ctypes.c_void_p), 0, 0, flags
            )
            if not decode_stream:
                err = self.bass.BASS_ErrorGetCode()
                raise RuntimeError(f"Failed to create decode stream. BASS error code: {err}")

            self.tempo_stream = self.bass_fx.BASS_FX_TempoCreate(decode_stream, BASS_FX_FREESOURCE)
            if not self.tempo_stream:
                err = self.bass.BASS_ErrorGetCode()
                self.bass.BASS_StreamFree(decode_stream)
                raise RuntimeError(f"Failed to create tempo stream. BASS error code: {err}")

            len_bytes = self.bass.BASS_ChannelGetLength(self.tempo_stream, BASS_POS_BYTE)
            self.duration_seconds = float(self.bass.BASS_ChannelBytes2Seconds(self.tempo_stream, len_bytes))
            self.current_file = file_path

            # Setup 6-band PEAK EQ
            self.eq_fx_handle = self.bass.BASS_ChannelSetFX(self.tempo_stream, BASS_FX_BFX_PEAKEQ, 0)
            if self.eq_fx_handle:
                for idx, center_freq in enumerate(self.eq_bands):
                    eq = BASS_BFX_PEAKEQ()
                    eq.lBand = idx
                    eq.fBandwidth = 1.0
                    eq.fQ = 0.0
                    eq.fCenter = center_freq
                    eq.fGain = 0.0
                    eq.lChannel = -1
                    self.bass.BASS_FXSetParameters(self.eq_fx_handle, ctypes.byref(eq))

            # Re-apply remembered master volume
            self.bass.BASS_ChannelSetAttribute(self.tempo_stream, BASS_ATTRIB_VOL, ctypes.c_float(self.volume))

            # Re-apply frequency isolator if active
            if self.isolator_enabled:
                self.set_bandpass_isolator(True, self.isolator_center_hz, self.isolator_bw_oct)

            return self.duration_seconds

    def set_bandpass_isolator(self, enabled, center_hz=1200.0, bandwidth_oct=1.2):
        """
        Surgical Band-Pass Frequency Isolator using dual cascaded Biquad filters.
        Extracts only frequencies around `center_hz` (within `bandwidth_oct` octaves)
        and suppresses all surrounding low/high noise.
        """
        with self._lock:
            self.isolator_enabled = bool(enabled)
            self.isolator_center_hz = max(100.0, min(8000.0, float(center_hz)))
            self.isolator_bw_oct = max(0.3, min(3.5, float(bandwidth_oct)))

            if not self.tempo_stream:
                return False

            if not self.isolator_enabled:
                if self.isolator_fx1:
                    self.bass.BASS_ChannelRemoveFX(self.tempo_stream, self.isolator_fx1)
                    self.isolator_fx1 = 0
                if self.isolator_fx2:
                    self.bass.BASS_ChannelRemoveFX(self.tempo_stream, self.isolator_fx2)
                    self.isolator_fx2 = 0
                return True

            if not self.isolator_fx1:
                self.isolator_fx1 = self.bass.BASS_ChannelSetFX(self.tempo_stream, BASS_FX_BFX_BQF, 10)
            if not self.isolator_fx2:
                self.isolator_fx2 = self.bass.BASS_ChannelSetFX(self.tempo_stream, BASS_FX_BFX_BQF, 11)

            bqf = BASS_BFX_BQF()
            bqf.lFilter = BASS_BFX_BQF_BANDPASS
            bqf.fCenter = self.isolator_center_hz
            bqf.fGain = 0.0
            bqf.fBandwidth = self.isolator_bw_oct
            bqf.fQ = 0.0
            bqf.fS = 0.0
            bqf.lChannel = -1

            if self.isolator_fx1:
                self.bass.BASS_FXSetParameters(self.isolator_fx1, ctypes.byref(bqf))
            if self.isolator_fx2:
                self.bass.BASS_FXSetParameters(self.isolator_fx2, ctypes.byref(bqf))
            return True

    def get_realtime_analysis(self, num_bands=48, num_wave_pts=96):
        """
        Extracts real-time logarithmic frequency spectrum (80Hz - 10,000Hz)
        and oscilloscope waveform samples in <0.05ms using pre-allocated C buffers.
        Returns: (spectrum_list [0.0..1.0], wave_list [-1.0..1.0])
        """
        with self._lock:
            if not self.tempo_stream or not self.is_playing():
                return [0.0] * num_bands, [0.0] * num_wave_pts

            # 1. Get 2048-sample FFT (returns 1024 floats representing 0Hz..22050Hz)
            got_fft = self.bass.BASS_ChannelGetData(
                self.tempo_stream, ctypes.byref(self._fft_buf), BASS_DATA_FFT2048
            )
            spectrum = [0.0] * num_bands
            if got_fft != 0xFFFFFFFF and got_fft > 0:
                # Map bins logarithmically from ~80Hz (bin 3) to ~10,000Hz (bin 465)
                min_bin = 3
                max_bin = 465
                log_min = math.log10(min_bin)
                log_max = math.log10(max_bin)
                for i in range(num_bands):
                    b_start = int(10 ** (log_min + (log_max - log_min) * (i / num_bands)))
                    b_end = int(10 ** (log_min + (log_max - log_min) * ((i + 1) / num_bands)))
                    if b_end <= b_start:
                        b_end = b_start + 1
                    peak = 0.0
                    for b in range(b_start, min(b_end, 512)):
                        val = self._fft_buf[b]
                        if val > peak:
                            peak = val
                    # Perceptual dB/sqrt scaling for clear visual representation
                    scaled = min(1.0, math.sqrt(max(0.0, peak)) * 2.8)
                    spectrum[i] = scaled

            # 2. Get floating-point PCM waveform samples
            bytes_needed = min(512, num_wave_pts * 2) * 4
            got_wave = self.bass.BASS_ChannelGetData(
                self.tempo_stream, ctypes.byref(self._wave_buf), bytes_needed | BASS_DATA_FLOAT
            )
            wave_pts = [0.0] * num_wave_pts
            if got_wave != 0xFFFFFFFF and got_wave > 0:
                floats_read = min(512, got_wave // 4)
                step = max(1, floats_read // num_wave_pts)
                for i in range(num_wave_pts):
                    idx = min(floats_read - 1, i * step)
                    wave_pts[i] = max(-1.0, min(1.0, float(self._wave_buf[idx])))

            return spectrum, wave_pts

    def play(self):
        with self._lock:
            if not self.tempo_stream:
                return False
            return bool(self.bass.BASS_ChannelPlay(self.tempo_stream, False))

    def pause(self):
        with self._lock:
            if not self.tempo_stream:
                return False
            return bool(self.bass.BASS_ChannelPause(self.tempo_stream))

    def stop(self):
        with self._lock:
            if not self.tempo_stream:
                return False
            res = bool(self.bass.BASS_ChannelStop(self.tempo_stream))
            self.set_position_seconds(0.0)
            return res

    def unload(self):
        with self._lock:
            self.stop()
            if self.tempo_stream:
                self.bass.BASS_StreamFree(self.tempo_stream)
                self.tempo_stream = 0
                self.eq_fx_handle = 0
                self.isolator_fx1 = 0
                self.isolator_fx2 = 0
            self.current_file = None
            self.active_local_path = None
            self.duration_seconds = 0.0
            self.is_cached_copy = False
            return True

    def is_playing(self):
        with self._lock:
            if not self.tempo_stream:
                return False
            return self.bass.BASS_ChannelIsActive(self.tempo_stream) == BASS_ACTIVE_PLAYING

    def get_position_seconds(self):
        with self._lock:
            if not self.tempo_stream:
                return 0.0
            pos_bytes = self.bass.BASS_ChannelGetPosition(self.tempo_stream, BASS_POS_BYTE)
            sec = float(self.bass.BASS_ChannelBytes2Seconds(self.tempo_stream, pos_bytes))
            return max(0.0, sec)

    def set_position_seconds(self, seconds):
        with self._lock:
            if not self.tempo_stream:
                return False
            seconds = max(0.0, min(self.duration_seconds, float(seconds)))
            pos_bytes = self.bass.BASS_ChannelSeconds2Bytes(self.tempo_stream, ctypes.c_double(seconds))
            return bool(self.bass.BASS_ChannelSetPosition(self.tempo_stream, pos_bytes, BASS_POS_BYTE))

    def set_speed(self, speed_factor):
        with self._lock:
            if not self.tempo_stream:
                return False
            speed_factor = max(0.2, min(3.0, float(speed_factor)))
            tempo_val = (speed_factor - 1.0) * 100.0
            return bool(self.bass.BASS_ChannelSetAttribute(self.tempo_stream, BASS_ATTRIB_TEMPO, ctypes.c_float(tempo_val)))

    def get_speed(self):
        with self._lock:
            if not self.tempo_stream:
                return 1.0
            val = ctypes.c_float(0.0)
            if self.bass.BASS_ChannelGetAttribute(self.tempo_stream, BASS_ATTRIB_TEMPO, ctypes.byref(val)):
                return round((val.value / 100.0) + 1.0, 2)
            return 1.0

    def set_pitch(self, semitones):
        with self._lock:
            if not self.tempo_stream:
                return False
            semitones = max(-12.0, min(12.0, float(semitones)))
            return bool(self.bass.BASS_ChannelSetAttribute(self.tempo_stream, BASS_ATTRIB_TEMPO_PITCH, ctypes.c_float(semitones)))

    def get_pitch(self):
        with self._lock:
            if not self.tempo_stream:
                return 0.0
            val = ctypes.c_float(0.0)
            if self.bass.BASS_ChannelGetAttribute(self.tempo_stream, BASS_ATTRIB_TEMPO_PITCH, ctypes.byref(val)):
                return round(float(val.value), 1)
            return 0.0

    def set_volume(self, volume):
        with self._lock:
            # Remember the requested volume so it is re-applied when a file is (re)loaded
            # Range: 0.0 to 2.0 (1.0 = 100% normal max, >1.0 = digital boost / amplification up to 200%)
            self.volume = max(0.0, min(2.0, float(volume)))
            if not self.tempo_stream:
                return False
            return bool(self.bass.BASS_ChannelSetAttribute(self.tempo_stream, BASS_ATTRIB_VOL, ctypes.c_float(self.volume)))

    def set_eq_band_gain(self, band_index, gain_db):
        with self._lock:
            if not self.eq_fx_handle or band_index < 0 or band_index >= len(self.eq_bands):
                return False
            eq = BASS_BFX_PEAKEQ()
            eq.lBand = band_index
            if self.bass.BASS_FXGetParameters(self.eq_fx_handle, ctypes.byref(eq)):
                eq.fGain = max(-15.0, min(15.0, float(gain_db)))
                return bool(self.bass.BASS_FXSetParameters(self.eq_fx_handle, ctypes.byref(eq)))
            return False

    def jump_relative(self, delta_seconds):
        with self._lock:
            current = self.get_position_seconds()
            target = current + float(delta_seconds)
            self.set_position_seconds(target)
            return self.get_position_seconds()

    def close(self):
        with self._lock:
            self.stop()
            if self.tempo_stream:
                self.bass.BASS_StreamFree(self.tempo_stream)
                self.tempo_stream = 0
                self.eq_fx_handle = 0
                self.isolator_fx1 = 0
                self.isolator_fx2 = 0
            self.bass.BASS_Free()
