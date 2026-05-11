"""YAMNet-based baby cry detection for the PC audio pipeline."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np

from .logger_setup import setup_logger

logger = setup_logger("raspbot.cry")


@dataclass(frozen=True)
class CryDetectorConfig:
    sample_rate: int = 16000
    window_sec: float = 1.0
    hop_sec: float = 0.5
    trigger_score: float = 0.60
    release_score: float = 0.40
    trigger_sec: float = 2.0
    release_sec: float = 3.0
    min_rms: float = 0.004
    model_url: str = "https://tfhub.dev/google/yamnet/1"

    @classmethod
    def from_env(cls) -> "CryDetectorConfig":
        return cls(
            window_sec=_env_float("RASPBOT_CRY_WINDOW_SEC", cls.window_sec),
            hop_sec=_env_float("RASPBOT_CRY_HOP_SEC", cls.hop_sec),
            trigger_score=_env_float("RASPBOT_CRY_TRIGGER_SCORE", cls.trigger_score),
            release_score=_env_float("RASPBOT_CRY_RELEASE_SCORE", cls.release_score),
            trigger_sec=_env_float("RASPBOT_CRY_TRIGGER_SEC", cls.trigger_sec),
            release_sec=_env_float("RASPBOT_CRY_RELEASE_SEC", cls.release_sec),
            min_rms=_env_float("RASPBOT_CRY_MIN_RMS", cls.min_rms),
            model_url=os.getenv("RASPBOT_YAMNET_MODEL_URL", cls.model_url),
        )


@dataclass(frozen=True)
class CryState:
    crying: bool
    score: int


class CryStateSmoother:
    """Turns noisy per-window model scores into stable alarm state."""

    def __init__(self, config: CryDetectorConfig):
        self.cfg = config
        self._crying = False
        self._high_sec = 0.0
        self._low_sec = 0.0

    def update(self, score: float) -> CryState:
        score = float(max(0.0, min(1.0, score)))
        if score >= self.cfg.trigger_score:
            self._high_sec += self.cfg.hop_sec
        else:
            self._high_sec = 0.0

        if score <= self.cfg.release_score:
            self._low_sec += self.cfg.hop_sec
        else:
            self._low_sec = 0.0

        if not self._crying and self._high_sec >= self.cfg.trigger_sec:
            self._crying = True
            self._low_sec = 0.0
        elif self._crying and self._low_sec >= self.cfg.release_sec:
            self._crying = False
            self._high_sec = 0.0

        return CryState(crying=self._crying, score=int(round(score * 100.0)))


class YamnetCryDetector:
    """Streaming PCM16 detector that scores baby-cry related YAMNet classes."""

    def __init__(
        self,
        config: Optional[CryDetectorConfig] = None,
        *,
        model_loader: Optional[Callable[[str], object]] = None,
    ):
        self.cfg = config or CryDetectorConfig.from_env()
        self._model_loader = model_loader
        self._model = None
        self._class_names: List[str] = []
        self._cry_indices: List[int] = []
        self._buffer = np.empty(0, dtype=np.float32)
        self._new_samples = 0
        self._smoother = CryStateSmoother(self.cfg)
        self._load_failed = False

    def feed_pcm16(self, audio: bytes) -> List[Tuple[bool, float]]:
        samples = _pcm16_to_float32(audio)
        if samples.size == 0:
            return []

        self._buffer = np.concatenate((self._buffer, samples))
        self._new_samples += int(samples.size)

        window_samples = max(1, int(self.cfg.sample_rate * self.cfg.window_sec))
        hop_samples = max(1, int(self.cfg.sample_rate * self.cfg.hop_sec))
        max_buffer = max(window_samples * 2, window_samples + hop_samples)
        if self._buffer.size > max_buffer:
            self._buffer = self._buffer[-max_buffer:]

        updates: List[Tuple[bool, float]] = []
        while self._buffer.size >= window_samples and self._new_samples >= hop_samples:
            self._new_samples -= hop_samples
            window = self._buffer[-window_samples:]
            score = self.score_window(window)
            state = self._smoother.update(score)
            updates.append((state.crying, state.score / 100.0))
        return updates

    def score_window(self, waveform: np.ndarray) -> float:
        if waveform.size == 0:
            return 0.0
        rms = float(np.sqrt(np.mean(np.square(waveform, dtype=np.float32))))
        if rms < self.cfg.min_rms:
            return 0.0
        model = self._ensure_model()
        if model is None or not self._cry_indices:
            return 0.0
        try:
            scores, _embeddings, _spectrogram = model(waveform.astype(np.float32))
            scores_np = scores.numpy() if hasattr(scores, "numpy") else np.asarray(scores)
            mean_scores = np.mean(scores_np, axis=0)
            return float(np.max(mean_scores[self._cry_indices]))
        except Exception as exc:
            logger.warning("yamnet inference failed: %s", exc)
            return 0.0

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        if self._load_failed:
            return None
        try:
            loader = self._model_loader
            if loader is None:
                import tensorflow_hub as hub

                loader = hub.load
            model = loader(self.cfg.model_url)
            class_names = _load_class_names(model)
            cry_indices = _find_cry_indices(class_names)
            if not cry_indices:
                logger.warning("yamnet class map has no cry-like classes")
            else:
                logger.info(
                    "yamnet cry classes: %s",
                    ", ".join(class_names[i] for i in cry_indices),
                )
            self._model = model
            self._class_names = class_names
            self._cry_indices = cry_indices
            return self._model
        except Exception as exc:
            self._load_failed = True
            logger.warning("yamnet unavailable, cry detection disabled: %s", exc)
            return None


def _pcm16_to_float32(audio: bytes) -> np.ndarray:
    if not audio:
        return np.empty(0, dtype=np.float32)
    usable = len(audio) - (len(audio) % 2)
    if usable <= 0:
        return np.empty(0, dtype=np.float32)
    pcm = np.frombuffer(audio[:usable], dtype="<i2")
    return (pcm.astype(np.float32) / 32768.0).clip(-1.0, 1.0)


def _load_class_names(model) -> List[str]:
    if not hasattr(model, "class_map_path"):
        return []
    path = model.class_map_path()
    if hasattr(path, "numpy"):
        path = path.numpy()
    if isinstance(path, bytes):
        path = path.decode("utf-8")
    names: List[str] = []
    with open(str(path), newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            name = row.get("display_name") or row.get("name") or ""
            names.append(str(name).strip())
    return names


def _find_cry_indices(class_names: Sequence[str]) -> List[int]:
    preferred = []
    fallback = []
    for index, name in enumerate(class_names):
        lower = name.lower()
        if "baby cry" in lower or "infant cry" in lower:
            preferred.append(index)
        elif "cry" in lower and ("baby" in lower or "infant" in lower or "child" in lower):
            preferred.append(index)
        elif "cry" in lower or "sobbing" in lower:
            fallback.append(index)
    return preferred or fallback


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return float(default)
