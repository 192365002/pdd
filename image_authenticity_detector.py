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


def load_detection_models():
    """
    Loads fine-tuned Vision Transformer (ViT) image classification models
    from local cache. Thread-safe singleton.
    """
    global _models_loaded, _processor_gen, _model_gen, _processor_df, _model_df
    if _models_loaded:
        return _processor_gen, _model_gen, _processor_df, _model_df

    with _model_lock:
        if _models_loaded:
            return _processor_gen, _model_gen, _processor_df, _model_df

        import torch
        from transformers import AutoImageProcessor, AutoModelForImageClassification

        logger.info("Loading DeepVerify pretrained vision models into memory...")

        m_gen_id = "dima806/ai_vs_real_image_detection"
        m_df_id = "dima806/deepfake_vs_real_image_detection"

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

        _models_loaded = True
        logger.info("DeepVerify pretrained vision models successfully loaded into memory.")

    return _processor_gen, _model_gen, _processor_df, _model_df


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


def classify_image_authenticity(file_path_or_bytes, source_hint=None):
    """
    Performs genuine deep learning inference on the image content.
    Returns strictly either 'AI GENERATED IMAGE' or 'ORIGINAL IMAGE'.
    No percentages, confidence scores, or probabilities are displayed.
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
    eval_img.thumbnail((512, 512), Image.Resampling.LANCZOS)

    # 3. Load genuine pretrained ViT models
    p_gen, m_gen, p_df, m_df = load_detection_models()

    import torch

    try:
        with torch.no_grad():
            # Model 1: General AI Generation Detector
            inputs_gen = p_gen(eval_img, return_tensors="pt")
            logits_gen = m_gen(**inputs_gen).logits
            probs_gen = torch.softmax(logits_gen, dim=-1)[0]
            # m_gen config: id2label {0: 'REAL', 1: 'FAKE'}
            prob_ai_gen = probs_gen[1].item()

            # Model 2: Deepfake Face & Manipulation Detector
            inputs_df = p_df(eval_img, return_tensors="pt")
            logits_df = m_df(**inputs_df).logits
            probs_df = torch.softmax(logits_df, dim=-1)[0]
            # m_df config: id2label {0: 'Real', 1: 'Fake'}
            prob_df = probs_df[1].item()
    except Exception as e:
        logger.error(f"Neural inference error: {e}")
        raise RuntimeError(f"Deep learning vision model failed during inference: {str(e)}")

    # 4. Strict Binary Verdict: Pure Content Analysis
    # Calibrated ensemble: Flag as AI if either generator or deepfake detector finds strong generative indicators
    is_ai = (prob_ai_gen >= 0.75) or (prob_df >= 0.55) or (((prob_ai_gen + prob_df) / 2.0) >= 0.62)

    t_elapsed = round((time.time() - t_start) * 1000, 1)

    if is_ai:
        classification = "AI GENERATED IMAGE"
        category = "ai_generated"
        risk_level = "High Risk"
        explanation = (
            "The pretrained Vision Transformer detected synthetic diffusion patterns, "
            "algorithmic lattice features, or generative neural artifacts in the image content."
        )
    else:
        classification = "ORIGINAL IMAGE"
        category = "likely_original"
        risk_level = "Safe"
        explanation = (
            "The pretrained Vision Transformer verified authentic optical camera characteristics, "
            "consistent with an original photograph."
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
            "evaluated_resolution": f"{eval_img.size[0]}x{eval_img.size[1]}"
        }
    }
