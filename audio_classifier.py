"""
audio_classifier.py - DeepVerify Voice & Audio Deepfake Detection Module

Strict authenticity contract:
- Supports WAV, MP3, M4A, WebM/Opus, OGG, AAC, and FLAC decoding to mono 16 kHz float32.
- Only returns 'AI-GENERATED VOICE' or 'ORIGINAL HUMAN VOICE' when genuine
  pretrained model inference is available and verified with explicit label mapping.
- Never classifies audio as AI or ORIGINAL from filename, extension, preset name,
  fabricated confidence values, or simple DSP thresholds (jitter/HNR/MFCC/flatness/HF).
- Never trains a replacement classifier from synthetic generate_voice_sample() audio.
- Returns 'UNCERTAIN' whenever no verified pretrained model is installed, or when
  input is missing, corrupted, silent, <0.50s, music without speech, or non-vocal noise.
"""

import json
import logging
import os
import struct
import wave

import joblib
import numpy as np
import scipy.fftpack
import scipy.io.wavfile
import scipy.signal

logger = logging.getLogger("SocialShield.AudioClassifier")

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "audio_deepfake_model.joblib")

_AUDIO_MODEL_STATE = {
    "checked": False,
    "available": False,
    "source": None,
    "model_name": None,
    "status_note": "",
    "rejected_models": [],
    "bundle": None,
}

# Accepted explicit class label keywords for dynamic id2label / model.classes_ verification
_FAKE_LABEL_TOKENS = ("fake", "spoof", "ai", "synthetic", "clone", "deepfake", "generated", "tts", "artificial")
_REAL_LABEL_TOKENS = ("real", "bonafide", "bona_fide", "bona-fide", "human", "original", "genuine", "authentic")

SUPPORTED_AUDIO_ARCHES = {
    "Wav2Vec2ForSequenceClassification",
    "HubertForSequenceClassification",
    "WavLMForSequenceClassification",
    "ASTForAudioClassification",
    "UniSpeechSatForSequenceClassification",
}


def _resolve_label_mapping(id2label):
    """
    Resolves exact integer indices for fake vs real classes from config id2label.
    Never assumes index 0 == real and index 1 == fake. Returns (fake_idx, real_idx) or (None, None).
    """
    if not isinstance(id2label, dict) or len(id2label) < 2:
        return None, None

    fake_idx = None
    real_idx = None
    for raw_k, raw_v in id2label.items():
        try:
            idx = int(raw_k)
        except (TypeError, ValueError):
            continue
        label = str(raw_v or "").strip().lower()
        if not label or label.startswith("label_"):
            # Generic LABEL_0 / LABEL_1 without human/spoof names cannot be safely trusted
            return None, None
        if any(tok in label for tok in _FAKE_LABEL_TOKENS) and fake_idx is None:
            fake_idx = idx
        elif any(tok in label for tok in _REAL_LABEL_TOKENS) and real_idx is None:
            real_idx = idx

    if fake_idx is None or real_idx is None or fake_idx == real_idx:
        return None, None
    return fake_idx, real_idx


def _inspect_local_joblib():
    """
    Inspects models/audio_deepfake_model.joblib without triggering training.
    Verifies classes_ and provenance metadata; rejects unverified synthetic models.
    """
    if not os.path.exists(MODEL_PATH):
        return None, f"Local joblib file not present at {MODEL_PATH}."

    try:
        payload = joblib.load(MODEL_PATH)
    except Exception as exc:
        return None, f"Failed to inspect {MODEL_PATH}: {exc}"

    if not isinstance(payload, dict) or "model" not in payload:
        return None, f"Rejected {MODEL_PATH}: unexpected structure without model entry."

    clf = payload["model"]
    classes = getattr(clf, "classes_", None)
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    report = payload.get("report") if isinstance(payload.get("report"), dict) else {}

    # Reject synthetic models trained from generate_voice_sample()
    if not metadata.get("verified_real_speech_dataset"):
        return None, (
            f"Rejected {os.path.basename(MODEL_PATH)} (classes_={list(classes) if classes is not None else None}, "
            f"report={report}): trained on synthetic/unverified waveforms rather than a verified real+deepfake speech dataset."
        )

    label_map = metadata.get("class_mapping")
    fake_idx, real_idx = _resolve_label_mapping(label_map)
    if classes is None or fake_idx is None or real_idx is None:
        return None, f"Rejected {os.path.basename(MODEL_PATH)}: missing explicit class_mapping verification."

    return {
        "kind": "sklearn_verified",
        "model": clf,
        "fake_idx": fake_idx,
        "real_idx": real_idx,
        "model_name": metadata.get("model_name", os.path.basename(MODEL_PATH)),
        "source": MODEL_PATH,
    }, None


def _inspect_hf_offline_audio_cache():
    """
    Scans the local Hugging Face hub cache (offline only, no network calls) for any
    cached pretrained audio deepfake classification checkpoint with verified architecture & id2label.
    """
    hub_dir = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
    if not os.path.isdir(hub_dir):
        return None, f"Hugging Face cache directory not found at {hub_dir}."

    audio_cache_dirs = []
    for entry in sorted(os.listdir(hub_dir)):
        if not entry.startswith("models--"):
            continue
        snap_root = os.path.join(hub_dir, entry, "snapshots")
        if not os.path.isdir(snap_root):
            continue
        for snap in os.listdir(snap_root):
            cfg_path = os.path.join(snap_root, snap, "config.json")
            if not os.path.isfile(cfg_path):
                continue
            try:
                with open(cfg_path, "r", encoding="utf-8") as cf:
                    cfg = json.load(cf)
            except Exception:
                continue
            arches = set(cfg.get("architectures") or [])
            if arches & SUPPORTED_AUDIO_ARCHES:
                audio_cache_dirs.append((entry, os.path.join(snap_root, snap), cfg))

    if not audio_cache_dirs:
        return None, f"No pretrained speech deepfake model found in local Hugging Face cache ({hub_dir})."

    rejection_notes = []
    for entry, snap_path, cfg in audio_cache_dirs:
        repo_name = entry[len("models--"):].replace("--", "/")
        fake_idx, real_idx = _resolve_label_mapping(cfg.get("id2label"))
        if fake_idx is None or real_idx is None:
            rejection_notes.append(f"{repo_name}: unverified id2label={cfg.get('id2label')}")
            continue

        try:
            from transformers import AutoFeatureExtractor, AutoModelForAudioClassification
            extractor = AutoFeatureExtractor.from_pretrained(snap_path, local_files_only=True)
            model = AutoModelForAudioClassification.from_pretrained(snap_path, local_files_only=True)
            model.eval()
            return {
                "kind": "hf_audio_classifier",
                "model": model,
                "feature_extractor": extractor,
                "fake_idx": fake_idx,
                "real_idx": real_idx,
                "id2label": cfg.get("id2label"),
                "required_sr": int(getattr(extractor, "sampling_rate", 16000) or 16000),
                "model_name": repo_name,
                "source": snap_path,
            }, None
        except Exception as load_err:
            rejection_notes.append(f"{repo_name}: load error ({load_err})")

    return None, "; ".join(rejection_notes) if rejection_notes else "No usable cached audio model."


def verify_pretrained_audio_models(force_refresh=False):
    """
    Verifies whether a genuine pretrained speech deepfake model is installed locally.
    Never downloads weights and never trains a synthetic fallback model.
    Returns: (available: bool, status_note: str)
    """
    if _AUDIO_MODEL_STATE["checked"] and not force_refresh:
        return _AUDIO_MODEL_STATE["available"], _AUDIO_MODEL_STATE["status_note"]

    rejected = []

    hf_bundle, hf_err = _inspect_hf_offline_audio_cache()
    if hf_bundle is not None:
        note = (
            f"Verified pretrained speech deepfake model loaded from offline cache: "
            f"{hf_bundle['model_name']} (id2label={hf_bundle['id2label']}, sr={hf_bundle['required_sr']} Hz)."
        )
        logger.info(note)
        _AUDIO_MODEL_STATE.update({
            "checked": True,
            "available": True,
            "source": hf_bundle["source"],
            "model_name": hf_bundle["model_name"],
            "status_note": note,
            "rejected_models": [],
            "bundle": hf_bundle,
        })
        return True, note

    if hf_err:
        rejected.append(hf_err)

    sk_bundle, sk_err = _inspect_local_joblib()
    if sk_bundle is not None:
        note = f"Verified speech classification model loaded: {sk_bundle['model_name']} ({sk_bundle['source']})."
        logger.info(note)
        _AUDIO_MODEL_STATE.update({
            "checked": True,
            "available": True,
            "source": sk_bundle["source"],
            "model_name": sk_bundle["model_name"],
            "status_note": note,
            "rejected_models": rejected,
            "bundle": sk_bundle,
        })
        return True, note

    if sk_err:
        rejected.append(sk_err)

    note = (
        "No verified pretrained speech deepfake model is installed locally "
        f"({' | '.join(rejected)}). Returning UNCERTAIN instead of guessing."
    )
    logger.warning(f"[Audio Classifier] {note}")
    _AUDIO_MODEL_STATE.update({
        "checked": True,
        "available": False,
        "source": None,
        "model_name": None,
        "status_note": note,
        "rejected_models": rejected,
        "bundle": None,
    })
    return False, note


def load_verified_audio_model():
    """Returns the verified model bundle dict if available locally, else None."""
    avail, _ = verify_pretrained_audio_models()
    return _AUDIO_MODEL_STATE["bundle"] if avail else None


def get_audio_model():
    """Returns verified model inspection metadata (never uses mock/synthetic overrides)."""
    avail, note = verify_pretrained_audio_models()
    return {
        "model_available": avail,
        "pretrained_available": avail,
        "model_name": _AUDIO_MODEL_STATE["model_name"],
        "source": _AUDIO_MODEL_STATE["source"],
        "rejected_models": list(_AUDIO_MODEL_STATE["rejected_models"]),
        "status_note": note,
        "joblib_path": MODEL_PATH,
    }


def _resample_signal(samples, orig_sr, target_sr):
    """Resamples 1D float32 audio cleanly from orig_sr to target_sr."""
    if orig_sr <= 0 or orig_sr == target_sr or len(samples) == 0:
        return samples.astype(np.float32), target_sr if orig_sr <= 0 else orig_sr
    import math
    g = math.gcd(int(orig_sr), int(target_sr))
    up = int(target_sr) // g
    down = int(orig_sr) // g
    resampled = scipy.signal.resample_poly(samples, up, down).astype(np.float32)
    return resampled, int(target_sr)


def load_audio_signal(filepath, target_sr=16000):
    """
    Safely decodes audio formats (WAV, MP3, M4A, WebM/Opus, OGG, AAC, FLAC)
    into mono float32 samples normalized to [-1.0, 1.0] at target_sr (default 16 kHz).
    Decode cascade: soundfile (linear-phase resample_poly for WAV/FLAC/OGG) -> PyAV -> scipy -> wave.
    Returns: (signal, sample_rate, error_reason)
    """
    if not filepath or not os.path.exists(filepath):
        return None, 0, "Audio file does not exist or was not received."

    file_size = os.path.getsize(filepath)
    if file_size < 100:
        return None, 0, f"Audio file is empty or corrupted ({file_size} bytes)."

    # 1. soundfile + linear-phase resample_poly (cleanest path for WAV, FLAC, OGG)
    try:
        import soundfile as sf
        data, sr = sf.read(filepath, dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        data, sr = _resample_signal(data, sr, target_sr)
        if len(data) > 0:
            return data, sr, None
    except Exception as e_sf:
        logger.debug(f"soundfile decode notice for {filepath}: {e_sf}")

    # 2. PyAV (WebM/Opus, MP3, M4A, AAC, MP4, fallback WAV/OGG/FLAC)
    try:
        import av
        container = av.open(filepath)
        try:
            audio_streams = container.streams.audio
            if len(audio_streams) > 0:
                resampler = av.AudioResampler(format="fltp", layout="mono", rate=target_sr)
                chunks = []
                for frame in container.decode(audio=0):
                    for r_frame in resampler.resample(frame):
                        chunks.append(r_frame.to_ndarray().flatten())
                if chunks:
                    signal = np.concatenate(chunks).astype(np.float32)
                    if len(signal) > 0:
                        return signal, target_sr, None
        finally:
            container.close()
    except Exception as e_av:
        logger.debug(f"PyAV decode notice for {filepath}: {e_av}")

    # 3. scipy.io.wavfile
    try:
        sr, data = scipy.io.wavfile.read(filepath)
        if data.ndim > 1:
            data = data.mean(axis=1)
        if data.dtype == np.int16:
            samples = data.astype(np.float32) / 32768.0
        elif data.dtype == np.int32:
            samples = data.astype(np.float32) / 2147483648.0
        elif data.dtype == np.uint8:
            samples = (data.astype(np.float32) - 128.0) / 128.0
        else:
            samples = data.astype(np.float32)
        samples, sr = _resample_signal(samples, sr, target_sr)
        if len(samples) > 0:
            return samples, sr, None
    except Exception as e_scipy:
        logger.debug(f"scipy decode notice for {filepath}: {e_scipy}")

    # 4. standard wave module
    try:
        with wave.open(filepath, "rb") as wf:
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            n_frames = wf.getnframes()
            raw = wf.readframes(n_frames)

        if n_frames > 0 and framerate > 0:
            if sampwidth == 2:
                fmt = f"<{n_frames * n_channels}h"
                samples = np.array(struct.unpack(fmt, raw), dtype=np.float32) / 32768.0
            elif sampwidth == 1:
                samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
            elif sampwidth == 4:
                fmt = f"<{n_frames * n_channels}i"
                samples = np.array(struct.unpack(fmt, raw), dtype=np.float32) / 2147483648.0
            else:
                samples = np.frombuffer(raw, dtype=np.float32)

            if n_channels > 1:
                samples = samples.reshape(-1, n_channels).mean(axis=1)
            samples, framerate = _resample_signal(samples, framerate, target_sr)
            if len(samples) > 0:
                return samples, framerate, None
    except Exception as e_wave:
        logger.debug(f"wave decode notice for {filepath}: {e_wave}")

    return None, 0, "Audio format could not be decoded or stream is corrupted. Supported formats: WAV, MP3, M4A, WebM, OGG, AAC, FLAC."


def convert_to_wav_16k(input_path, output_wav_path):
    """Decodes any supported audio file and writes a 16 kHz mono PCM WAV."""
    sig, sr, err = load_audio_signal(input_path, target_sr=16000)
    if sig is None or err:
        return False, err
    try:
        scaled = np.clip(sig * 32767.0, -32768.0, 32767.0).astype(np.int16)
        scipy.io.wavfile.write(output_wav_path, sr, scaled)
        return True, None
    except Exception as e:
        return False, str(e)


def _preprocess_vocal_band(signal, sr):
    """
    Removes DC offset and sub-80 Hz room/laptop fan rumble using zero-phase
    Butterworth filtering (sosfiltfilt) so phase & male/female F0 harmonics
    remain intact for neural deepfake inference and pitch tracking.
    """
    if signal.ndim > 1:
        signal = signal.mean(axis=1)
    sig = signal.astype(np.float32) - float(np.mean(signal))
    if sr > 400 and len(sig) > 32:
        sos = scipy.signal.butter(4, 80.0 / (sr / 2.0), btype="highpass", output="sos")
        if len(sig) > 64:
            sig = scipy.signal.sosfiltfilt(sos, sig).astype(np.float32)
        else:
            sig = scipy.signal.sosfilt(sos, sig).astype(np.float32)
    peak_amp = float(np.max(np.abs(sig)))
    if peak_amp > 0:
        sig = sig / peak_amp
    return sig, peak_amp


def extract_acoustic_features(signal, sr):
    """
    Extracts acoustic diagnostics (MFCCs, spectral flux/flatness/rolloff,
    100-1000 Hz peak-tracked F0 pitch count, pause ratio, and sub-band ratios)
    used strictly for non-speech/music/noise quality validation and diagnostics.
    Never used directly to claim AI vs ORIGINAL without a verified model.
    """
    sig, raw_peak = _preprocess_vocal_band(signal, sr)

    win_len = int(0.025 * sr)
    hop_len = int(0.010 * sr)
    if len(sig) < win_len:
        sig = np.pad(sig, (0, win_len - len(sig)))

    frames = np.array(
        [sig[i:i + win_len] * np.hanning(win_len) for i in range(0, len(sig) - win_len + 1, hop_len)]
    )
    if len(frames) == 0:
        frames = np.array([sig[:win_len] * np.hanning(win_len)])
    n_frames = len(frames)

    n_fft = 512
    mag = np.abs(np.fft.rfft(frames, n=n_fft)) + 1e-10
    power = (mag ** 2) / n_fft
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)

    frame_rms = np.sqrt(np.mean(frames ** 2, axis=1))
    max_rms = float(np.max(frame_rms)) if len(frame_rms) > 0 else 0.0
    active_mask = frame_rms > (0.15 * max_rms) if max_rms > 0 else np.ones(n_frames, dtype=bool)
    if np.sum(active_mask) < 3:
        active_mask = np.ones(n_frames, dtype=bool)

    act_frames = frames[active_mask]
    act_mag = mag[active_mask]
    act_pow = power[active_mask]
    n_act = len(act_frames)

    # 1. MFCC statistics
    low_mel = 2595.0 * np.log10(1.0 + 100.0 / 700.0)
    high_mel = 2595.0 * np.log10(1.0 + (sr / 2.0) / 700.0)
    n_mels = 26
    mel_points = np.linspace(low_mel, high_mel, n_mels + 2)
    hz_points = 700.0 * (10.0 ** (mel_points / 2595.0) - 1.0)
    bins = np.floor((n_fft + 1) * hz_points / sr).astype(int)

    fbank = np.zeros((n_mels, n_fft // 2 + 1))
    for m in range(1, n_mels + 1):
        f_m_minus, f_m, f_m_plus = bins[m - 1], bins[m], bins[m + 1]
        for k in range(f_m_minus, f_m):
            if f_m != f_m_minus:
                fbank[m - 1, k] = (k - f_m_minus) / (f_m - f_m_minus)
        for k in range(f_m, f_m_plus):
            if f_m_plus != f_m:
                fbank[m - 1, k] = (f_m_plus - k) / (f_m_plus - f_m)

    filter_banks = np.where(np.dot(power, fbank.T) <= 0, 1e-10, np.dot(power, fbank.T))
    mfcc = scipy.fftpack.dct(np.log(filter_banks), type=2, axis=-1, norm="ortho")[:, :13]
    mfcc_act = mfcc[active_mask]
    mfcc_mean = np.mean(mfcc_act, axis=0)
    mfcc_var = np.var(mfcc_act, axis=0)

    if n_act > 1:
        mfcc_delta = np.diff(mfcc_act, axis=0)
        delta_mean = float(np.mean(np.linalg.norm(mfcc_delta, axis=1)))
        delta_var = float(np.var(np.linalg.norm(mfcc_delta, axis=1)))
    else:
        delta_mean, delta_var = 0.0, 0.0

    # 2. Spectral diagnostics
    pow_sums = np.sum(act_pow, axis=1) + 1e-10
    sc_list = np.sum(act_pow * freqs, axis=1) / pow_sums
    sc_mean = float(np.mean(sc_list))
    sc_var = float(np.var(sc_list))

    rolloffs = []
    for i in range(n_act):
        cum_p = np.cumsum(act_pow[i])
        cutoff = np.searchsorted(cum_p, 0.85 * cum_p[-1])
        rolloffs.append(freqs[min(cutoff, len(freqs) - 1)])
    rolloff_mean = float(np.mean(rolloffs))

    geo_mean = np.exp(np.mean(np.log(act_pow + 1e-12), axis=1))
    ari_mean = np.mean(act_pow, axis=1) + 1e-12
    flatness_mean = float(np.mean(geo_mean / ari_mean))

    if n_act > 1:
        norm_mag = act_mag / (np.linalg.norm(act_mag, axis=1, keepdims=True) + 1e-10)
        flux_mean = float(np.mean(np.sum(np.diff(norm_mag, axis=0) ** 2, axis=1)))
    else:
        flux_mean = 0.0

    # 3. 100-1000 Hz vocal fundamental F0 tracking via autocorrelation peak search
    if sr > 2200 and len(sig) > 32:
        f0_sos = scipy.signal.butter(4, 1000.0 / (sr / 2.0), btype="lowpass", output="sos")
        sig_f0 = scipy.signal.sosfilt(f0_sos, sig).astype(np.float32)
        f0_frames = np.array(
            [sig_f0[i:i + win_len] * np.hanning(win_len) for i in range(0, len(sig_f0) - win_len + 1, hop_len)]
        )
        act_f0_frames = f0_frames[active_mask] if len(f0_frames) == n_frames else act_frames
    else:
        act_f0_frames = act_frames

    min_lag = max(1, int(sr / 380))
    max_lag = min(win_len - 2, int(sr / 75))
    f0_vals = []
    hnr_vals = []
    for f, f_lp in zip(act_frames, act_f0_frames):
        corr = np.correlate(f, f, mode="full")[len(f) - 1:]
        c0 = corr[0] + 1e-10
        seg = corr[min_lag:max_lag]
        pks, _ = scipy.signal.find_peaks(seg)
        if len(pks) > 0:
            best_pk = pks[np.argmax(seg[pks])]
            hnr_vals.append(float(seg[best_pk] / c0))

        corr_lp = np.correlate(f_lp, f_lp, mode="full")[len(f_lp) - 1:]
        c0_lp = corr_lp[0] + 1e-10
        seg_lp = corr_lp[min_lag:max_lag]
        pks_lp, _ = scipy.signal.find_peaks(seg_lp)
        if len(pks_lp) > 0:
            best_lp = pks_lp[np.argmax(seg_lp[pks_lp])]
            if float(seg_lp[best_lp] / c0_lp) >= 0.40:
                f0_vals.append(float(sr / (min_lag + best_lp)))

    med_f0 = float(np.median(f0_vals)) if len(f0_vals) >= 3 else 0.0
    if len(f0_vals) >= 4 and med_f0 > 0:
        f0_arr = np.array(f0_vals)
        inliers = f0_arr[(f0_arr > med_f0 * 0.60) & (f0_arr < med_f0 * 1.50)]
        jitter_proxy = float(np.median(np.abs(np.diff(inliers))) / (med_f0 + 1e-6)) if len(inliers) >= 3 else 0.0
    else:
        jitter_proxy = 0.0
    hnr_mean = float(np.mean(hnr_vals)) if hnr_vals else 0.0

    # 4. ZCR, RMS modulation & pauses
    zcr_list = [np.mean(np.abs(np.diff(np.where(f == 0, 1, np.sign(f)))) / 2.0) for f in act_frames]
    zcr_mean = float(np.mean(zcr_list))
    zcr_var = float(np.var(zcr_list))

    energy_list = np.mean(frames ** 2, axis=1)
    energy_var = float(np.var(energy_list))
    en_arr = energy_list + 1e-10
    en_norm = en_arr / np.sum(en_arr)
    energy_entropy = float(-np.sum(en_norm * np.log2(en_norm)))

    rms_cv = float(np.std(frame_rms) / (np.mean(frame_rms) + 1e-10))
    pause_frac = float(np.mean(frame_rms < 0.08 * max_rms)) if max_rms > 0 else 0.0

    tot_pow = float(np.sum(act_pow)) + 1e-10
    hf_ratio = float(np.sum(act_pow[:, freqs >= 3500]) / tot_pow)

    peak_counts = [len(scipy.signal.find_peaks(m, height=np.max(m) * 0.18, distance=3)[0]) for m in act_mag]
    avg_peaks = float(np.mean(peak_counts)) if peak_counts else 0.0

    feature_vec = np.hstack([
        mfcc_mean,
        mfcc_var,
        [delta_mean, delta_var],
        [sc_mean, sc_var, rolloff_mean, flatness_mean, flux_mean],
        [zcr_mean, zcr_var, energy_var, energy_entropy],
        [jitter_proxy, hnr_mean, hf_ratio],
    ])

    metrics_dict = {
        "median_f0_hz": round(med_f0, 1),
        "n_voiced_f0_frames": len(f0_vals),
        "spectral_centroid": round(sc_mean, 1),
        "spectral_rolloff": round(rolloff_mean, 1),
        "spectral_flatness": round(flatness_mean, 4),
        "spectral_flux": round(flux_mean, 4),
        "zcr": round(zcr_mean, 4),
        "rms_cv": round(rms_cv, 3),
        "pause_fraction": round(pause_frac, 3),
        "hf_ratio": round(hf_ratio, 4),
        "avg_spectral_peaks": round(avg_peaks, 2),
        "duration_s": round(float(len(signal) / sr), 3),
        "framerate": sr,
        "peak_amplitude": round(raw_peak, 4),
    }
    return feature_vec, metrics_dict


def generate_voice_sample(label_type="human", sr=16000, duration=2.5, rng=None, difficulty="normal"):
    """Utility helper retained for unit-test waveform generation; never used to train classifiers."""
    if rng is None:
        rng = np.random.default_rng()

    n_samples = int(sr * duration)
    t = np.linspace(0, duration, n_samples, endpoint=False)
    base_f0 = rng.uniform(100.0, 220.0)
    if label_type == "human":
        f0_contour = np.clip(base_f0 + 18.0 * np.sin(2 * np.pi * 0.5 * t), 75.0, 360.0)
        phase = np.cumsum(2 * np.pi * f0_contour / sr)
        glottal = np.sin(phase) + 0.5 * np.sin(2 * phase) + 0.25 * np.sin(3 * phase)
        audio = glottal * np.clip(np.sin(2 * np.pi * 3.0 * t) ** 2, 0.05, 1.0) + rng.normal(0, 0.03, n_samples)
    else:
        phase = np.cumsum(2 * np.pi * np.full(n_samples, base_f0) / sr)
        audio = (np.sin(phase) + 0.45 * np.sin(2 * phase)) * 0.7 + rng.normal(0, 0.01, n_samples)
    m = np.max(np.abs(audio))
    return (audio / m).astype(np.float32) if m > 0 else audio.astype(np.float32)


def detect_music_and_clarity(signal, sr, metrics):
    """
    Identifies pure polyphonic instrumental music or pure non-vocal static noise so
    they are not automatically fed through the speech deepfake classifier as AI speech.
    Noisy human speech and mobile speaker playback with voiced F0 frames pass through.
    """
    avg_peaks = float(metrics.get("avg_spectral_peaks", 0.0))
    flatness = float(metrics.get("spectral_flatness", 0.0))
    sc = float(metrics.get("spectral_centroid", 0.0))
    n_f0 = int(metrics.get("n_voiced_f0_frames", 0))
    pause_frac = float(metrics.get("pause_fraction", 0.0))
    rms_cv = float(metrics.get("rms_cv", 0.0))

    is_music = (
        (avg_peaks >= 11.5 and flatness >= 0.085 and pause_frac < 0.05 and rms_cv < 0.55)
        or (avg_peaks >= 16.5 and pause_frac < 0.05 and rms_cv < 0.55 and n_f0 < 100)
    )
    is_non_vocal_noise = (n_f0 < 4 and flatness > 0.20) or (sc > 5000 and n_f0 < 3)
    return is_music, is_non_vocal_noise, {"avg_peaks": avg_peaks, "flatness": flatness, "sc": sc}


def _infer_with_verified_model(bundle, signal, sr, feature_vec):
    """
    Runs genuine model inference using verified id2label / classes_ mapping.
    Applies sub-100 Hz rumble removal + peak normalization before Wav2Vec2 feature
    extraction so microphone/laptop fan hum does not bias speech predictions.
    """
    if bundle["kind"] == "hf_audio_classifier":
        import torch
        req_sr = bundle["required_sr"]
        audio_in, _ = _resample_signal(signal, sr, req_sr)
        audio_in, _ = _preprocess_vocal_band(audio_in, req_sr)
        extractor = bundle["feature_extractor"]
        inputs = extractor(audio_in, sampling_rate=req_sr, return_tensors="pt", padding=True)
        with torch.no_grad():
            logits = bundle["model"](**inputs).logits
            probs = torch.softmax(logits, dim=-1)[0].cpu().numpy()
        fake_prob = float(probs[bundle["fake_idx"]])
        real_prob = float(probs[bundle["real_idx"]])
        return fake_prob, real_prob

    if bundle["kind"] == "sklearn_verified":
        probs = bundle["model"].predict_proba(np.asarray(feature_vec, dtype=np.float64).reshape(1, -1))[0]
        fake_prob = float(probs[bundle["fake_idx"]])
        real_prob = float(probs[bundle["real_idx"]])
        return fake_prob, real_prob

    raise RuntimeError(f"Unsupported model bundle kind: {bundle.get('kind')}")


def _error_response(err_msg, explanations=None, details=None):
    """
    Structured technical error response when decoding, audio validity, or model
    inference fails. Avoids inventing AI or ORIGINAL classifications on failure.
    """
    return {
        "classification": "TECHNICAL ERROR (UNKNOWN)",
        "verdict": "TECHNICAL ERROR (UNKNOWN)",
        "confidence": None,
        "fake_probability": None,
        "real_probability": None,
        "score": 0,
        "risk_level": "Error",
        "error": err_msg,
        "explanation": f"Technical Error: {err_msg}",
        "explanations": explanations or [err_msg],
        "details": details or {"error": err_msg},
    }


def predict_audio_voice_clone(filepath, filename=None):
    """
    Verifies uploaded audio using genuine pretrained speech deepfake inference.
    Normal valid predictions return strictly 'AI-GENERATED VOICE' or
    'ORIGINAL HUMAN VOICE' directly from verified class probabilities.
    Failures, missing models, or non-speech recordings return a technical error.
    """
    avail, model_note = verify_pretrained_audio_models()
    model_bundle = load_verified_audio_model() if avail else None

    # 1. Decode and validate audio across formats & sample rates
    signal, sr, err = load_audio_signal(filepath, target_sr=16000)
    if signal is None:
        return _error_response(
            err or "Audio could not be decoded.",
            explanations=[
                "Audio decoding failed — cannot perform speech authenticity verification",
                err or "Unsupported or corrupted audio stream",
            ],
            details={
                "analysis_method": "signal_validation",
                "error": err or "Audio could not be decoded.",
                "model_available": avail,
                "model_name": _AUDIO_MODEL_STATE["model_name"],
                "pretrained_model_status": model_note,
            },
        )

    duration = float(len(signal) / sr)
    peak_amp = float(np.max(np.abs(signal)))
    rms = float(np.sqrt(np.mean(signal ** 2)))

    # 2. Digital silence check
    if peak_amp < 0.005 or rms < 0.0008:
        msg = "Audio recording contains digital silence with no detectable vocal signal."
        return _error_response(
            msg,
            explanations=[
                "Peak amplitude is below vocal speech threshold (< 0.5%)",
                "No pitch contour or vocal harmonics present in recording",
            ],
            details={
                "error": msg,
                "peak_amplitude": round(peak_amp, 5),
                "rms": round(rms, 5),
                "duration_s": round(duration, 3),
                "model_available": avail,
                "pretrained_model_status": model_note,
            },
        )

    # 3. Minimum clip length check
    if duration < 0.50:
        msg = f"Audio clip is too short ({duration:.2f}s). Minimum 0.50s of speech is required."
        return _error_response(
            msg,
            explanations=[
                f"Clip duration ({duration:.2f}s) is below minimum 0.50s analysis window",
                "Insufficient audio frames for speech deepfake inference",
            ],
            details={
                "error": msg,
                "duration_s": round(duration, 3),
                "peak_amplitude": round(peak_amp, 4),
                "model_available": avail,
                "pretrained_model_status": model_note,
            },
        )

    # 4. Extract diagnostic metrics and prevent non-speech music/noise from being auto-flagged as AI
    feature_vec, metrics = extract_acoustic_features(signal, sr)
    metrics["model_available"] = avail
    metrics["model_name"] = _AUDIO_MODEL_STATE["model_name"]
    metrics["pretrained_model_status"] = model_note

    is_music, is_non_vocal, clarity_info = detect_music_and_clarity(signal, sr, metrics)
    if is_music or is_non_vocal:
        reason = (
            "Polyphonic music or instrumental audio detected rather than spoken speech."
            if is_music else
            "Non-vocal static noise detected without sufficient spoken vocal pitch frames."
        )
        return _error_response(
            reason,
            explanations=[
                reason,
                f"Spectral peaks/frame: {metrics['avg_spectral_peaks']:.1f}, voiced F0 frames: {metrics['n_voiced_f0_frames']}",
                "Upload an isolated spoken voice sample for speech deepfake inference",
            ],
            details={**metrics, **clarity_info, "error": reason},
        )

    # 5. Require genuine verified pretrained model inference — never invent a verdict if missing
    if model_bundle is None:
        logger.error(f"[Audio Classifier] Model unavailable: {model_note}")
        return _error_response(
            model_note,
            explanations=[
                "Missing verified speech deepfake model in offline cache",
                model_note,
            ],
            details={**metrics, "error": model_note},
        )

    # 6. Genuine verified model inference — return strictly AI-GENERATED VOICE or ORIGINAL HUMAN VOICE
    try:
        fake_prob, real_prob = _infer_with_verified_model(model_bundle, signal, sr, feature_vec)
    except Exception as infer_err:
        logger.error(f"[Audio Classifier] Model inference failed: {infer_err}", exc_info=True)
        return _error_response(
            f"Model inference failed: {infer_err}",
            explanations=[
                f"Verified model ({model_bundle['model_name']}) inference failed",
                str(infer_err),
            ],
            details={**metrics, "error": str(infer_err)},
        )

    metrics["model_fake_probability"] = round(fake_prob, 4)
    metrics["model_real_probability"] = round(real_prob, 4)

    if fake_prob >= real_prob:
        verdict = "AI-GENERATED VOICE"
        risk_level = "High Risk"
        score = int(round(fake_prob * 100))
        conf = round(fake_prob * 100, 1)
        explanation = (
            f"AI-GENERATED VOICE detected via {model_bundle['model_name']} "
            f"(fake probability {fake_prob * 100:.1f}%, real probability {real_prob * 100:.1f}%)."
        )
    else:
        verdict = "ORIGINAL HUMAN VOICE"
        risk_level = "Safe"
        score = int(round(fake_prob * 100))
        conf = round(real_prob * 100, 1)
        explanation = (
            f"ORIGINAL HUMAN VOICE verified via {model_bundle['model_name']} "
            f"(human probability {real_prob * 100:.1f}%, synthetic probability {fake_prob * 100:.1f}%)."
        )

    return {
        "classification": verdict,
        "verdict": verdict,
        "confidence": conf,
        "fake_probability": round(fake_prob, 4),
        "real_probability": round(real_prob, 4),
        "score": score,
        "risk_level": risk_level,
        "explanation": explanation,
        "explanations": [
            explanation,
            f"Model: {model_bundle['model_name']} (id2label={model_bundle.get('id2label')})",
            f"Analyzed {duration:.2f}s audio @ {sr} Hz mono",
        ],
        "details": metrics,
    }
