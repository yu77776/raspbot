"""Debug YAMNet cry scores from a WAV/PCM file or synthetic audio.

Examples:
    python -m pc_modules.debug_yamnet_cry --wav sample.wav
    python -m pc_modules.debug_yamnet_cry --pcm sample.pcm
    python -m pc_modules.debug_yamnet_cry --synthetic tone600
"""

from __future__ import annotations

import argparse
import wave
from pathlib import Path
from typing import Iterable

import numpy as np

from .cry_detector import CryDetectorConfig, YamnetCryDetector


def _read_wav(path: Path, sample_rate: int) -> np.ndarray:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())

    if width != 2:
        raise RuntimeError(f"only 16-bit PCM WAV is supported, got sample width={width}")

    audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if rate != sample_rate:
        audio = _resample_linear(audio, rate, sample_rate)
    return audio.astype(np.float32).clip(-1.0, 1.0)


def _read_pcm16(path: Path) -> np.ndarray:
    data = path.read_bytes()
    usable = len(data) - (len(data) % 2)
    if usable <= 0:
        return np.empty(0, dtype=np.float32)
    return (np.frombuffer(data[:usable], dtype="<i2").astype(np.float32) / 32768.0).clip(-1.0, 1.0)


def _resample_linear(audio: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    if audio.size == 0 or from_rate == to_rate:
        return audio
    duration = audio.size / float(from_rate)
    old_x = np.linspace(0.0, duration, num=audio.size, endpoint=False)
    new_size = max(1, int(round(duration * to_rate)))
    new_x = np.linspace(0.0, duration, num=new_size, endpoint=False)
    return np.interp(new_x, old_x, audio).astype(np.float32)


def _synthetic(kind: str, sample_rate: int, duration: float) -> np.ndarray:
    samples = max(1, int(sample_rate * duration))
    t = np.arange(samples, dtype=np.float32) / float(sample_rate)
    if kind == "silence":
        return np.zeros(samples, dtype=np.float32)
    if kind == "tone440":
        return (0.2 * np.sin(2.0 * np.pi * 440.0 * t)).astype(np.float32)
    if kind == "tone600":
        return (0.2 * np.sin(2.0 * np.pi * 600.0 * t)).astype(np.float32)
    raise RuntimeError(f"unknown synthetic audio kind: {kind}")


def _pcm16_bytes(audio: np.ndarray) -> bytes:
    return (audio.clip(-1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def _windows(audio: np.ndarray, window_samples: int, hop_samples: int) -> Iterable[np.ndarray]:
    if audio.size < window_samples:
        yield np.pad(audio, (0, window_samples - audio.size))
        return
    start = 0
    while start + window_samples <= audio.size:
        yield audio[start:start + window_samples]
        start += hop_samples


def _top_classes(detector: YamnetCryDetector, waveform: np.ndarray, top_n: int) -> list[tuple[str, float]]:
    model = detector._ensure_model()
    if model is None:
        return []
    scores, _embeddings, _spectrogram = model(waveform.astype(np.float32))
    scores_np = scores.numpy() if hasattr(scores, "numpy") else np.asarray(scores)
    mean_scores = np.mean(scores_np, axis=0)
    class_names = detector._class_names
    top_indices = np.argsort(mean_scores)[::-1][:top_n]
    return [(class_names[i] if i < len(class_names) else str(i), float(mean_scores[i])) for i in top_indices]


def main() -> int:
    parser = argparse.ArgumentParser(description="Debug real YAMNet baby-cry scores")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--wav", type=Path, help="16-bit PCM WAV; resampled to 16 kHz if needed")
    source.add_argument("--pcm", type=Path, help="raw PCM16LE mono at 16 kHz")
    source.add_argument("--synthetic", choices=["silence", "tone440", "tone600"])
    parser.add_argument("--duration", type=float, default=3.0, help="synthetic duration in seconds")
    parser.add_argument("--top", type=int, default=8, help="top YAMNet classes to print for the first window")
    parser.add_argument("--frame-ms", type=int, default=20, help="streaming frame size for smoothed updates")
    args = parser.parse_args()

    cfg = CryDetectorConfig.from_env()
    detector = YamnetCryDetector(cfg)

    if args.wav:
        audio = _read_wav(args.wav, cfg.sample_rate)
        label = str(args.wav)
    elif args.pcm:
        audio = _read_pcm16(args.pcm)
        label = str(args.pcm)
    else:
        audio = _synthetic(args.synthetic, cfg.sample_rate, args.duration)
        label = args.synthetic

    window_samples = max(1, int(cfg.sample_rate * cfg.window_sec))
    hop_samples = max(1, int(cfg.sample_rate * cfg.hop_sec))
    rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float32)))) if audio.size else 0.0

    print(f"source={label}")
    print(f"samples={audio.size} sample_rate={cfg.sample_rate} duration={audio.size / cfg.sample_rate:.2f}s rms={rms:.5f}")
    print(
        "config="
        f"window={cfg.window_sec}s hop={cfg.hop_sec}s "
        f"trigger_score={cfg.trigger_score} release_score={cfg.release_score} "
        f"trigger_sec={cfg.trigger_sec} release_sec={cfg.release_sec} min_rms={cfg.min_rms}"
    )

    first_window = next(_windows(audio, window_samples, hop_samples))
    cry_classes = [detector._class_names[i] for i in detector._cry_indices] if detector._ensure_model() else []
    print(f"cry_classes={cry_classes}")
    print("top_classes_first_window:")
    for name, score in _top_classes(detector, first_window, max(1, int(args.top))):
        print(f"  {score:.4f}  {name}")

    print("cry_scores_by_window:")
    for index, window in enumerate(_windows(audio, window_samples, hop_samples), start=1):
        print(f"  window={index:03d} score={detector.score_window(window):.4f}")

    print("smoothed_updates:")
    frame_samples = max(1, int(cfg.sample_rate * max(1, int(args.frame_ms)) / 1000))
    update_index = 0
    for start in range(0, audio.size, frame_samples):
        chunk = audio[start:start + frame_samples]
        for crying, ratio in detector.feed_pcm16(_pcm16_bytes(chunk)):
            update_index += 1
            print(f"  update={update_index:03d} t={start / cfg.sample_rate:05.2f}s crying={crying} score={ratio:.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
