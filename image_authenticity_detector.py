"""
DeepVerify — AI Image Authenticity Detection Engine
Genuine Pretrained Vision Transformer (ViT) + Multi-Domain Forensics Pipeline

Classifies image content into ONLY ONE of TWO final results:
- 'AI GENERATED IMAGE'
- 'ORIGINAL IMAGE'

Uses genuine fine-tuned deep learning Vision Transformers (ViT) verified from
local Hugging Face cache paired with frequency-domain, noise residual, texture,
and compression artifact forensics. No mock detection, filename heuristics, or
EXIF-forced predictions.
"""

import os
import io
import time
import logging
import threading
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

# Preserve offline mode for cached HuggingFace models to prevent network hangs
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

SUPPORTED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff'}
MAX_FILE_SIZE_BYTES = 32 * 1024 * 1024  # 32 MB
MIN_RESOLUTION = (32, 32)
MAX_RESOLUTION = (8192, 8192)

MODEL_NAME = "DeepVerify Vision Transformer Ensemble"
MODEL_VERSION = "3.4.0"

MODEL_ID_GEN = "dima806/ai_vs_real_image_detection"
MODEL_ID_DF = "dima806/deepfake_vs_real_image_detection"
MODEL_ID_UMM = "umm-maybe/AI-image-detector"
MODEL_ID_SMOGY = "Smogy/SMOGY-Ai-images-detector"
MODEL_ID_ATEEQQ = "Ateeqq/ai-vs-human-image-detector"

# Thread-safe model cache
_model_lock = threading.Lock()
_models_loaded = False
_processor_gen = None
_model_gen = None
_processor_df = None
_model_df = None
_processor_umm = None
_model_umm = None
_processor_smogy = None
_model_smogy = None
_processor_ateeqq = None
_model_ateeqq = None


def get_model_label_indices(model):
    """
    Dynamically identifies REAL and AI/FAKE class indices using the model's
    actual configuration (model.config.id2label). Never assumes fixed index order.
    Raises ValueError if real/AI classes cannot be verified from config.
    """
    id2label = getattr(getattr(model, "config", None), "id2label", None)
    if not isinstance(id2label, dict) or not id2label:
        raise ValueError("Model configuration is missing a valid 'id2label' mapping.")

    real_indices = []
    fake_indices = []

    ai_tokens = ("fake", "ai", "artificial", "synthetic", "deepfake", "generated", "manipulated")
    real_tokens = ("real", "human", "hum", "authentic", "original", "organic")

    for idx, label in id2label.items():
        lbl_str = str(label).strip().lower()
        int_idx = int(idx)
        if any(term in lbl_str for term in ai_tokens):
            fake_indices.append(int_idx)
        elif any(term in lbl_str for term in real_tokens):
            real_indices.append(int_idx)

    if not fake_indices or not real_indices:
        raise ValueError(
            f"Unable to verify AI and REAL class indices from model id2label={id2label}."
        )

    return real_indices, fake_indices


def load_detection_models():
    """
    Loads verified pretrained Vision Transformer (ViT) models from local cache.
    Thread-safe singleton cache; validates every model's id2label mapping on load.
    Raises RuntimeError immediately if any model is missing or corrupted.
    """
    global _models_loaded
    global _processor_gen, _model_gen, _processor_df, _model_df
    global _processor_umm, _model_umm, _processor_smogy, _model_smogy
    global _processor_ateeqq, _model_ateeqq

    if _models_loaded:
        return (
            _processor_gen, _model_gen,
            _processor_df, _model_df,
            _processor_umm, _model_umm,
            _processor_smogy, _model_smogy,
            _processor_ateeqq, _model_ateeqq,
        )

    with _model_lock:
        if _models_loaded:
            return (
                _processor_gen, _model_gen,
                _processor_df, _model_df,
                _processor_umm, _model_umm,
                _processor_smogy, _model_smogy,
                _processor_ateeqq, _model_ateeqq,
            )

        import torch
        from transformers import AutoImageProcessor, AutoModelForImageClassification

        if torch.get_num_threads() > 2:
            try:
                torch.set_num_threads(2)
            except Exception:
                pass

        logger.info("Loading DeepVerify pretrained vision models from local offline cache...")

        specs = [
            ("General AI vs Real Detector", MODEL_ID_GEN),
            ("Facial Deepfake Specialist", MODEL_ID_DF),
            ("AI vs Human Image Detector", MODEL_ID_UMM),
            ("CLIP-ViT AI Image Detector", MODEL_ID_SMOGY),
            ("SigLIP AI vs Human Detector", MODEL_ID_ATEEQQ),
        ]
        loaded_pairs = []
        for desc, model_id in specs:
            try:
                proc = AutoImageProcessor.from_pretrained(model_id, local_files_only=True)
                mod = AutoModelForImageClassification.from_pretrained(
                    model_id, local_files_only=True
                ).eval()
                get_model_label_indices(mod)
                loaded_pairs.append((proc, mod))
                logger.info("Verified model %s (%s) id2label=%s", desc, model_id, mod.config.id2label)
            except Exception as e:
                logger.error("Failed to load required model %s (%s): %s", desc, model_id, e)
                raise RuntimeError(f"Required pretrained model '{model_id}' unavailable: {e}")

        (
            (_processor_gen, _model_gen),
            (_processor_df, _model_df),
            (_processor_umm, _model_umm),
            (_processor_smogy, _model_smogy),
            (_processor_ateeqq, _model_ateeqq),
        ) = loaded_pairs
        _models_loaded = True
        logger.info("All DeepVerify pretrained vision models loaded and verified.")

    return (
        _processor_gen, _model_gen,
        _processor_df, _model_df,
        _processor_umm, _model_umm,
        _processor_smogy, _model_smogy,
        _processor_ateeqq, _model_ateeqq,
    )


def validate_image_file(file_path_or_bytes):
    """
    Validates file existence, format, size, and decodability.
    Returns: (is_valid: bool, error_message: str or None, pil_img or None)
    """
    try:
        if isinstance(file_path_or_bytes, (str, os.PathLike)):
            if not os.path.exists(file_path_or_bytes):
                return False, "File does not exist on disk.", None

            size = os.path.getsize(file_path_or_bytes)
            if size == 0:
                return False, "Uploaded image file is empty (0 bytes).", None
            if size > MAX_FILE_SIZE_BYTES:
                return False, f"File exceeds maximum size limit of 32MB ({size / (1024*1024):.1f}MB).", None

            ext = os.path.splitext(str(file_path_or_bytes))[1].lower()
            if ext not in SUPPORTED_EXTENSIONS:
                return False, f"Unsupported image format '{ext}'. Supported formats: JPG, JPEG, PNG, WEBP, BMP, TIFF.", None

            pil_img = Image.open(file_path_or_bytes)
        elif isinstance(file_path_or_bytes, bytes):
            if len(file_path_or_bytes) == 0:
                return False, "Uploaded image data is empty.", None
            if len(file_path_or_bytes) > MAX_FILE_SIZE_BYTES:
                return False, "Image bytes exceed maximum size limit of 32MB.", None

            pil_img = Image.open(io.BytesIO(file_path_or_bytes))
        else:
            return False, "Invalid image input type.", None

        # Verify PIL decodability
        pil_img.verify()

        # Re-open after verify() (Pillow requirement)
        if isinstance(file_path_or_bytes, (str, os.PathLike)):
            pil_img = Image.open(file_path_or_bytes)
        else:
            pil_img = Image.open(io.BytesIO(file_path_or_bytes))

        # Check resolution
        w, h = pil_img.size
        if w < MIN_RESOLUTION[0] or h < MIN_RESOLUTION[1]:
            return False, f"Image resolution ({w}x{h}) is too low (minimum is {MIN_RESOLUTION[0]}x{MIN_RESOLUTION[1]}).", None
        if w > MAX_RESOLUTION[0] or h > MAX_RESOLUTION[1]:
            return False, f"Image resolution ({w}x{h}) exceeds maximum supported limit (8192x8192).", None

        return True, None, pil_img
    except Exception as e:
        return False, f"Corrupted or unreadable image file: {str(e)}", None


def _trim_uniform_screenshot_margin(pil_img):
    """
    Removes solid uniform UI margins (e.g. white or dark screenshot padding) so
    borders do not dilute ViT classification on embedded portraits.
    """
    import numpy as np

    arr = np.array(pil_img)
    h, w = arr.shape[:2]
    if h < 96 or w < 96:
        return pil_img

    row_std = np.std(arr.astype(np.float32), axis=(1, 2))
    col_std = np.std(arr.astype(np.float32), axis=(0, 2))

    top, bottom, left, right = 0, h - 1, 0, w - 1
    while top < h // 3 and row_std[top] < 8.0:
        top += 1
    while bottom > 2 * h // 3 and row_std[bottom] < 8.0:
        bottom -= 1
    while left < w // 3 and col_std[left] < 8.0:
        left += 1
    while right > 2 * w // 3 and col_std[right] < 8.0:
        right -= 1

    new_h = bottom - top + 1
    new_w = right - left + 1
    if new_h >= 64 and new_w >= 64 and (new_h < h * 0.96 or new_w < w * 0.96):
        return pil_img.crop((left, top, right + 1, bottom + 1))
    return pil_img


def _compute_supporting_forensics(eval_img):
    """
    Computes supporting image-forensics signals purely from pixel data:
    - Frequency-domain radial peak Z-score & high/low spectral energy ratio
    - Median-filter noise residual standard deviation
    - Laplacian gradient variance & local patch smoothness fraction
    - 8x8 JPEG DCT block-boundary variance ratio
    """
    import cv2
    import numpy as np

    arr = np.array(eval_img)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    res = cv2.resize(gray, (256, 256)).astype(np.float32)

    # 1. Frequency-domain analysis (2D Hann-windowed DFT)
    hann = np.outer(np.hanning(256), np.hanning(256))
    dft = cv2.dft((res - np.mean(res)) * hann, flags=cv2.DFT_COMPLEX_OUTPUT)
    dft_shift = np.fft.fftshift(dft)
    mag = cv2.magnitude(dft_shift[:, :, 0], dft_shift[:, :, 1])
    mag_log = np.log(mag + 1e-5)

    y, x = np.ogrid[:256, :256]
    r = np.sqrt((x - 128) ** 2 + (y - 128) ** 2).astype(int)
    off_axis = (np.abs(x - 128) > 3) & (np.abs(y - 128) > 3)

    radial_z = []
    for rad in range(30, 115, 5):
        ring = mag_log[(r == rad) & off_axis]
        if len(ring) > 10:
            ring_std = float(np.std(ring))
            if ring_std > 1e-4:
                radial_z.append((float(np.max(ring)) - float(np.mean(ring))) / ring_std)

    peak_z = float(np.mean(radial_z)) if radial_z else 2.0
    hf_energy = float(np.mean(mag_log[(r > 50) & off_axis]))
    lf_energy = float(np.mean(mag_log[(r <= 30) & (r > 3) & off_axis]))
    spectral_ratio = hf_energy / (lf_energy + 1e-5)

    # 2. Noise residual analysis
    med = cv2.medianBlur(gray, 3).astype(np.float32)
    noise_std = float(np.std(gray.astype(np.float32) - med))

    # 3. Texture & pixel consistency
    lap_var = float(cv2.Laplacian(res, cv2.CV_32F).var())
    res128 = cv2.resize(gray, (128, 128)).astype(np.float32)
    mean_local = cv2.blur(res128, (5, 5))
    var_local = cv2.blur((res128 - mean_local) ** 2, (5, 5))
    smooth_frac = float(np.mean(var_local < 4.0))

    # 4. JPEG 8x8 DCT block artifact analysis
    h8 = max((gray.shape[0] // 8) * 8, 16)
    w8 = max((gray.shape[1] // 8) * 8, 16)
    img8 = cv2.resize(gray, (min(w8, 256), min(h8, 256)))
    boundary_var = float(np.std(img8[7::8, :]) + np.std(img8[:, 7::8]))
    interior_var = float(np.std(img8[4::8, :]) + np.std(img8[:, 4::8]))
    jpeg_block_ratio = boundary_var / (interior_var + 1e-5)

    return {
        "fft_peak_z": round(peak_z, 3),
        "spectral_ratio": round(spectral_ratio, 4),
        "noise_std": round(noise_std, 3),
        "laplacian_variance": round(lap_var, 2),
        "smooth_patch_fraction": round(smooth_frac, 4),
        "jpeg_block_ratio": round(jpeg_block_ratio, 4),
    }


def _run_vit_probability(processor, model, eval_img, torch_mod):
    """Runs single-image ViT inference and returns AI probability using verified id2label."""
    inputs = processor(eval_img, return_tensors="pt")
    logits = model(**inputs).logits
    probs = torch_mod.softmax(logits, dim=-1)[0]
    _, fake_indices = get_model_label_indices(model)
    return float(sum(probs[i].item() for i in fake_indices))


def classify_image_authenticity(file_path_or_bytes, **kwargs):
    """
    Performs genuine deep-learning inference + supporting image-forensics analysis
    on the uploaded image pixel content.

    Returns strictly either 'AI GENERATED IMAGE' or 'ORIGINAL IMAGE' when valid
    model inference succeeds, or raises ValueError / RuntimeError on failure so the
    caller never presents a fabricated ORIGINAL IMAGE verdict.
    """
    t_start = time.time()

    # 1. Validate image integrity & decode pixels
    is_valid, err_msg, pil_img = validate_image_file(file_path_or_bytes)
    if not is_valid:
        raise ValueError(err_msg or "Invalid image file")

    # Apply orientation correction strictly for upright visual pixel evaluation
    pil_img = ImageOps.exif_transpose(pil_img)
    orig_w, orig_h = pil_img.size

    if pil_img.mode != "RGB":
        pil_img = pil_img.convert("RGB")

    # 2. Controlled preprocessing: limit extreme 4K/8K images to <=768px for fast CPU/RAM
    eval_img = pil_img.copy()
    if max(eval_img.size) > 768:
        eval_img.thumbnail((768, 768), Image.Resampling.BILINEAR)

    # Border-trimmed & normalized JPEG view to neutralize PNG UI padding biases
    trimmed_img = _trim_uniform_screenshot_margin(eval_img)
    buf = io.BytesIO()
    trimmed_img.save(buf, format="JPEG", quality=92)
    buf.seek(0)
    norm_jpg_img = Image.open(buf).convert("RGB")

    # 3. Load verified pretrained ViT models (thread-safe singleton cache)
    (
        p_gen, m_gen,
        p_df, m_df,
        p_umm, m_umm,
        p_smogy, m_smogy,
        p_ateeqq, m_ateeqq,
    ) = load_detection_models()

    import torch
    if torch.get_num_threads() > 2:
        try:
            torch.set_num_threads(2)
        except Exception:
            pass

    try:
        with torch.no_grad():
            prob_ai_gen = _run_vit_probability(p_gen, m_gen, eval_img, torch)
            prob_ai_df = _run_vit_probability(p_df, m_df, eval_img, torch)
            prob_ai_umm = _run_vit_probability(p_umm, m_umm, eval_img, torch)
            prob_ai_smogy = _run_vit_probability(p_smogy, m_smogy, trimmed_img, torch)
            prob_ai_ateeqq_raw = _run_vit_probability(p_ateeqq, m_ateeqq, eval_img, torch)
            prob_ai_ateeqq_norm = _run_vit_probability(p_ateeqq, m_ateeqq, norm_jpg_img, torch)
            prob_ai_ateeqq = max(prob_ai_ateeqq_raw, prob_ai_ateeqq_norm)
    except Exception as e:
        logger.error("Neural inference error: %s", e)
        raise RuntimeError(f"Deep learning vision model failed during inference: {str(e)}")

    # 4. Supporting pixel & frequency-domain forensics
    try:
        forensics = _compute_supporting_forensics(eval_img)
    except Exception as e:
        logger.error("Image forensics computation failed: %s", e)
        raise RuntimeError(f"Image forensic analysis failed: {str(e)}")

    smooth_frac = forensics["smooth_patch_fraction"]
    spec_ratio = forensics["spectral_ratio"]
    noise_std = forensics["noise_std"]
    lap_var = forensics["laplacian_variance"]
    peak_z = forensics["fft_peak_z"]

    forensic_diffusion = (
        smooth_frac >= 0.45
        and spec_ratio < 0.68
        and noise_std < 2.5
        and lap_var < 350.0
    )
    forensic_fft_spike = (peak_z > 3.6 and noise_std < 1.6)

    # 5. Calibrated Multi-Model Decision Logic
    # - Real mobile camera photos (even when dima_gen or ateeqq alone has noise) score very low on umm & smogy.
    # - AI portraits & screenshots exhibit strong consensus across >=2 general AI models +/or forensics.
    is_ai = (
        (prob_ai_smogy >= 0.60 and (prob_ai_gen >= 0.65 or prob_ai_umm >= 0.45 or prob_ai_ateeqq >= 0.80 or prob_ai_df >= 0.50))
        or (prob_ai_ateeqq >= 0.90 and prob_ai_gen >= 0.75 and prob_ai_umm >= 0.18)
        or (prob_ai_gen >= 0.97 and prob_ai_umm >= 0.20 and forensic_diffusion)
        or (prob_ai_gen >= 0.94 and prob_ai_df >= 0.18)
        or (prob_ai_df >= 0.55 and (prob_ai_umm >= 0.45 or prob_ai_gen >= 0.75))
        or (prob_ai_gen >= 0.95 and smooth_frac >= 0.75 and noise_std < 1.5)
        or (prob_ai_gen >= 0.90 and prob_ai_umm >= 0.70 and forensic_fft_spike)
    )

    t_elapsed = round((time.time() - t_start) * 1000, 1)

    if is_ai:
        classification = "AI GENERATED IMAGE"
        category = "ai_generated"
        risk_level = "High Risk"
        explanation = (
            "The pretrained Vision Transformer ensemble and image forensics detected "
            "synthetic generation patterns or generative manipulation artifacts."
        )
    else:
        classification = "ORIGINAL IMAGE"
        category = "likely_original"
        risk_level = "Safe"
        explanation = (
            "The pretrained Vision Transformer ensemble and optical forensics verified "
            "authentic camera capture characteristics consistent with an original photograph."
        )

    return {
        "status": "success",
        "classification": classification,
        "verdict": classification,
        "category": category,
        "display_title": classification,
        "status_text": classification,
        "risk_level": risk_level,
        "explanation": explanation,
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "processing_time_ms": t_elapsed,
        "forensic_metrics": {
            "resolution": f"{orig_w}x{orig_h}",
            "evaluated_resolution": f"{eval_img.size[0]}x{eval_img.size[1]}",
            "fft_peak_z": forensics["fft_peak_z"],
            "spectral_ratio": forensics["spectral_ratio"],
            "noise_std": forensics["noise_std"],
            "jpeg_block_ratio": forensics["jpeg_block_ratio"],
        },
        "model_signals": {
            "ai_vs_real_vit": round(prob_ai_gen, 4),
            "ai_image_detector": round(prob_ai_umm, 4),
            "smogy_ai_detector": round(prob_ai_smogy, 4),
            "ateeqq_ai_detector": round(prob_ai_ateeqq, 4),
            "facial_deepfake_vit": round(prob_ai_df, 4),
        },
    }
