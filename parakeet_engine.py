"""Parakeet in-process transcription engine.

Wraps NVIDIA NeMo's Parakeet ASR model for direct (no-HTTP) transcription
within the main process.  All NeMo / torch imports are deferred so the app
starts normally on machines where these libraries are not installed.

Typical usage::

    from parakeet_engine import transcribe_file, is_available

    if is_available():
        text = transcribe_file(audio_path, "nvidia/parakeet-tdt-0.6b-v3", "de")
"""

from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

_model = None
_model_name_loaded: str | None = None
_model_lock = threading.Lock()


def is_available() -> bool:
    """Return True when torch and nemo_toolkit[asr] are importable."""
    try:
        import torch  # noqa: F401
        from nemo.collections.asr.models import ASRModel  # noqa: F401

        return True
    except ImportError:
        return False


def _load_model(model_name: str) -> None:
    """Load (or swap) the ASR model. Caller must hold *_model_lock*."""
    global _model, _model_name_loaded

    import torch
    from nemo.collections.asr.models import ASRModel

    if _model is not None and _model_name_loaded == model_name:
        return  # already loaded

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[parakeet] Loading {model_name!r} on {device} …")
    asr = ASRModel.from_pretrained(model_name)
    asr = asr.to(device)
    asr.eval()

    # Stabilise attention for long-form audio (mirrors the Docker app.py approach)
    try:
        asr.change_attention_model(
            self_attention_model="rel_pos_local_attn",
            att_context_size=[256, 256],
        )
    except Exception as exc:
        print(f"[parakeet] change_attention_model skipped: {exc}")

    _model = asr
    _model_name_loaded = model_name
    print("[parakeet] Model ready.")


def transcribe_file(audio_path: Path, model_name: str, language: str) -> str:
    """Transcribe *audio_path* using the Parakeet model in-process.

    *language* is accepted for interface parity; Parakeet v3 auto-detects the
    language and the parameter is not forwarded to the model.

    Raises ``RuntimeError`` when NeMo / torch is not installed.
    """
    if not is_available():
        raise RuntimeError(
            "NeMo is not installed. " "Install it with:  pip install nemo_toolkit[asr]"
        )

    import librosa
    import soundfile as sf
    import torch

    with _model_lock:
        _load_model(model_name)
        asr = _model

    # Resample to 16 kHz mono, matching the Docker server's preprocessing
    audio, _ = librosa.load(str(audio_path), sr=16000, mono=True)

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    try:
        sf.write(tmp.name, audio, 16000)
        with torch.inference_mode():
            output = asr.transcribe([tmp.name])
        result = output[0]
        text = result.text.strip() if hasattr(result, "text") else str(result).strip()
        return text
    finally:
        try:
            os.remove(tmp.name)
        except OSError:
            pass
