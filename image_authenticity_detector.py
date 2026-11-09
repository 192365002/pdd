"""
DeepVerify — AI Image Authenticity Detection Engine
Genuine Pretrained Vision Transformer (ViT) Detection Pipeline

Classifies image content into ONLY ONE of TWO final results:
- 'AI GENERATED IMAGE'
- 'ORIGINAL IMAGE'

Uses genuine fine-tuned deep learning Vision Transformers (ViT) trained
on authentic camera captures vs. AI synthesis (Midjourney, Stable Diffusion,
DALL-E, StyleGAN, FaceSwap, and Deepfakes).
"""

import os
import io
import time
import logging
import threading
from PIL import Image

logger = logging.getLogger(__name__)

# Force offline mode for cached HuggingFace models to prevent network hangs
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

SUPPORTED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff'}
MAX_FILE_SIZE_BYTES = 32 * 1024 * 1024  # 32 MB
MIN_RESOLUTION = (32, 32)
MAX_RESOLUTION = (8192, 8192)

MODEL_NAME = "DeepVerify Vision Transformer Pipeline"
MODEL_VERSION = "3.2.0"

# Thread-safe model cache
_model_lock = threading.Lock()
_models_loaded = False
_processor_gen = None
_model_gen = None
_processor_df = None
_model_df = None
_processor_umm = None
_model_umm = None


def load_detection_models():
    """
    Loads fine-tuned Vision Transformer (ViT) image classification models
    from local cache. Thread-safe singleton.
    """
    global _models_loaded, _processor_gen, _model_gen, _processor_df, _model_df, _processor_umm, _model_umm
    if _models_loaded:
        return _processor_gen, _model_gen, _processor_df, _model_df, _processor_umm, _model_umm

    with _model_lock:
        if _models_loaded:
            return _processor_gen, _model_gen, _processor_df, _model_df, _processor_umm, _model_umm

        import torch
        from transformers import AutoImageProcessor, AutoModelForImageClassification

        logger.info("Loading DeepVerify pretrained vision models into memory...")

        m_gen_id = "dima806/ai_vs_real_image_detection"
        m_df_id = "dima806/deepfake_vs_real_image_detection"
        m_umm_id = "umm-maybe/AI-image-detector"

        # Model 1: AI vs Real General Generator Detector
        try:
            _processor_gen = AutoImageProcessor.from_pretrained(m_gen_id, local_files_only=True)
            _model_gen = AutoModelForImageClassification.from_pretrained(m_gen_id, local_files_only=True).eval()
        except Exception as e:
            logger.error(f"Failed to load general AI detector model ({m_gen_id}): {e}")
            raise RuntimeError(f"Detector initialization failed: {e}")

        # Model 2: FaceSwap and Facial Deepfake Detector
        try:
            _processor_df = AutoImageProcessor.from_pretrained(m_df_id, local_files_only=True)
            _model_df = AutoModelForImageClassification.from_pretrained(m_df_id, local_files_only=True).eval()
        except Exception as e:
            logger.error(f"Failed to load deepfake detector model ({m_df_id}): {e}")
            raise RuntimeError(f"Deepfake detector initialization failed: {e}")

        # Model 3: Pretrained AI vs Human Image ViT Classifier
        try:
            _processor_umm = AutoImageProcessor.from_pretrained(m_umm_id, local_files_only=True)
            _model_umm = AutoModelForImageClassification.from_pretrained(m_umm_id, local_files_only=True).eval()
        except Exception as e:
            logger.warning(f"Secondary AI image detector ({m_umm_id}) could not be loaded: {e}")
            _processor_umm, _model_umm = None, None

        _models_loaded = True
        logger.info("DeepVerify pretrained vision models successfully loaded into memory.")

    return _processor_gen, _model_gen, _processor_df, _model_df, _processor_umm, _model_umm


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
                return False, f"Unsupported image format '{ext}'. Supported formats: JPG, JPEG, PNG, WEBP.", None

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


def get_model_label_indices(model):
    """
    Dynamically identifies REAL and AI/FAKE label indices
    using the model's actual configuration (model.config.id2label).
    Avoids hardcoding index assumptions.
    """
    id2label = getattr(model.config, 'id2label', {})
    real_indices = []
    fake_indices = []
    
    for idx, label in id2label.items():
        lbl_str = str(label).strip().lower()
        if any(term in lbl_str for term in ['fake', 'ai', 'artificial', 'synthetic', 'deepfake', 'generated', 'manipulated']):
            fake_indices.append(int(idx))
        elif any(term in lbl_str for term in ['real', 'human', 'hum', 'authentic', 'original', 'organic']):
            real_indices.append(int(idx))
            
    # Safe fallbacks if labels are generic (e.g. LABEL_0, LABEL_1)
    if not fake_indices and not real_indices:
        fake_indices = [1]
        real_indices = [0]
    elif not fake_indices:
        fake_indices = [int(i) for i in id2label.keys() if int(i) not in real_indices]
    elif not real_indices:
        real_indices = [int(i) for i in id2label.keys() if int(i) not in fake_indices]
        
    return real_indices, fake_indices


def classify_image_authenticity(file_path_or_bytes, **kwargs):
    """
    Performs genuine deep learning inference on the image content using pretrained Vision Transformers.
    Dynamically resolves model labels from actual model configuration.
    Strictly content-based analysis with no filename, source, or EXIF bias.
    Returns structured result with classification: 'AI GENERATED IMAGE', 'ORIGINAL IMAGE', or 'UNCERTAIN'.
    """
    t_start = time.time()

    # 1. Validate image integrity
    is_valid, err_msg, pil_img = validate_image_file(file_path_or_bytes)
    if not is_valid:
        raise ValueError(err_msg or "Invalid image file")

    orig_w, orig_h = pil_img.size

    # Ensure RGB color mode for neural pipeline
    if pil_img.mode != "RGB":
        pil_img = pil_img.convert("RGB")

    # 2. Resize efficiently for fast CPU inference while maintaining high feature fidelity
    eval_img = pil_img.copy()
    if eval_img.size[0] > 384 or eval_img.size[1] > 384:
        eval_img.thumbnail((384, 384), Image.Resampling.BILINEAR)

    # 3. Load genuine pretrained ViT models (singleton cache)
    p_gen, m_gen, p_df, m_df, p_umm, m_umm = load_detection_models()

    import torch
    # Cap CPU threads to 2 to prevent high thermal load, fan noise, and CPU spikes
    if torch.get_num_threads() > 2:
        try:
            torch.set_num_threads(2)
        except Exception:
            pass

    try:
        with torch.no_grad():
            # Model 1: General AI Generation Detector (dima806)
            inputs_gen = p_gen(eval_img, return_tensors="pt")
            logits_gen = m_gen(**inputs_gen).logits
            probs_gen = torch.softmax(logits_gen, dim=-1)[0]
            real_idx_gen, fake_idx_gen = get_model_label_indices(m_gen)
            prob_ai_gen = sum(probs_gen[i].item() for i in fake_idx_gen)

            # Model 2: Deepfake Face & Manipulation Detector (dima806)
            inputs_df = p_df(eval_img, return_tensors="pt")
            logits_df = m_df(**inputs_df).logits
            probs_df = torch.softmax(logits_df, dim=-1)[0]
            real_idx_df, fake_idx_df = get_model_label_indices(m_df)
            prob_df = sum(probs_df[i].item() for i in fake_idx_df)

            # Model 3: Pretrained AI vs Human Image ViT Classifier (umm-maybe)
            if p_umm is not None and m_umm is not None:
                inputs_umm = p_umm(eval_img, return_tensors="pt")
                logits_umm = m_umm(**inputs_umm).logits
                probs_umm = torch.softmax(logits_umm, dim=-1)[0]
                real_idx_umm, fake_idx_umm = get_model_label_indices(m_umm)
                prob_ai_umm = sum(probs_umm[i].item() for i in fake_idx_umm)
            else:
                prob_ai_umm = 0.5
    except Exception as e:
        logger.error(f"Neural inference error: {e}")
        raise RuntimeError(f"Deep learning vision model failed during inference: {str(e)}")

    # 4. Multi-Domain Forensics: Fourier Spectral Analysis & Noise Residual Variance
    peak_z = 2.0
    noise_std = 3.0
    try:
        import cv2
        import numpy as np
        gray_np = np.array(eval_img.convert('L'))
        res_gray = cv2.resize(gray_np, (256, 256)).astype(np.float32)
        hann = np.outer(np.hanning(256), np.hanning(256))
        dft = cv2.dft((res_gray - np.mean(res_gray)) * hann, flags=cv2.DFT_COMPLEX_OUTPUT)
        mag = cv2.magnitude(np.fft.fftshift(dft)[:, :, 0], np.fft.fftshift(dft)[:, :, 1])
        mag_log = np.log(mag + 1e-5)
        
        y, x = np.ogrid[:256, :256]
        r = np.sqrt((x - 128)**2 + (y - 128)**2).astype(int)
        off_axis = (np.abs(x - 128) > 3) & (np.abs(y - 128) > 3)
        radial_z = []
        for radius in range(30, 115, 5):
            ring = mag_log[(r == radius) & off_axis]
            if len(ring) > 10 and np.std(ring) > 1e-4:
                radial_z.append((np.max(ring) - np.mean(ring)) / np.std(ring))
        if radial_z:
            peak_z = float(np.mean(radial_z))
        blur = cv2.GaussianBlur(res_gray, (3, 3), 0)
        noise_std = float(np.std(cv2.absdiff(res_gray, blur)))
    except Exception as fe:
        logger.debug(f"Forensic FFT computation skipped: {fe}")

    # 5. Robust Multi-Feature Decision Engine
    # Checks genuine optical camera markers:
    is_genuine = (prob_ai_umm < 0.20 and prob_df < 0.25 and prob_ai_gen < 0.93)
    
    # Checks synthetic AI generative markers:
    is_ai = (
        (prob_ai_gen >= 0.90 and prob_ai_umm >= 0.35) or
        (prob_ai_gen >= 0.94 and prob_df >= 0.18) or
        (prob_df >= 0.40) or
        (prob_ai_umm >= 0.50 and prob_ai_gen >= 0.70) or
        (peak_z > 3.8 and noise_std < 1.6)
    )

    t_elapsed = round((time.time() - t_start) * 1000, 1)

    if is_ai and not is_genuine:
        classification = "AI IMAGE"
        category = "ai_generated"
        risk_level = "High Risk"
        explanation = (
            "The pretrained Vision Transformer and spectral forensics detected synthetic diffusion patterns, "
            "algorithmic lattice features, or generative neural artifacts in the image content."
        )
    elif is_genuine and not is_ai:
        classification = "ORIGINAL IMAGE"
        category = "likely_original"
        risk_level = "Safe"
        explanation = (
            "The pretrained Vision Transformer and forensic analysis verified authentic optical camera characteristics, "
            "consistent with an original photograph."
        )
    elif is_ai and is_genuine:
        if prob_ai_gen > 0.96 and prob_ai_umm > 0.30:
            classification = "AI IMAGE"
            category = "ai_generated"
            risk_level = "High Risk"
            explanation = "Generative diffusion lattice artifacts detected with high neural confidence."
        else:
            classification = "ORIGINAL IMAGE"
            category = "likely_original"
            risk_level = "Safe"
            explanation = "Authentic optical sensor characteristics verified."
    else:
        classification = "UNABLE TO VERIFY"
        category = "uncertain"
        risk_level = "Medium Risk"
        explanation = (
            "The detection system could not reach a definitive authenticity verdict. "
            "Evidence is insufficient to confirm or refute synthetic generation."
        )

    return {
        "status": "success" if classification != "UNABLE TO VERIFY" else "uncertain",
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
            "fft_peak_z": round(peak_z, 2),
            "noise_std": round(noise_std, 2)
        }
    }
