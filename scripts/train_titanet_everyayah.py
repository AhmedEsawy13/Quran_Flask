#!/usr/bin/env python3
"""
Reciter Identification with TitaNet + EveryAyah (pre-split parquet).

Key robustness improvements:
- Uses direct parquet files (no HF streaming iterator).
- Handles both parquet schemas: `audio` struct and `audio.bytes` flattened column.
- Avoids `pd.isna` on raw bytes.
- Captures skip reasons for quick debugging.
- Builds train/val/test manifests.
"""

import io
import json
import os
import random
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import soundfile as sf
import torch
from huggingface_hub import HfApi, hf_hub_download
from tqdm.auto import tqdm


# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
WORK_DIR = Path("/kaggle/working/reciter_titanet")
AUDIO_DIR = WORK_DIR / "audio_subset"
MANIFEST_DIR = WORK_DIR / "manifests"
MODEL_DIR = WORK_DIR / "models"

for d in (AUDIO_DIR, MANIFEST_DIR, MODEL_DIR):
    d.mkdir(parents=True, exist_ok=True)

DATASET_REPO = "tarteel-ai/everyayah"
PRETRAINED_MODEL = "nvidia/speakerverification_en_titanet_large"

TRAIN_SAMPLES_PER_RECITER = 25
VAL_SAMPLES_PER_RECITER = 5
TEST_SAMPLES_PER_RECITER = 5
MIN_TRAIN_SAMPLES = 10

BATCH_SIZE = 32
NUM_EPOCHS = 20
LEARNING_RATE = 1e-5
SAMPLE_RATE = 16000

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)


def _safe_reciter_name(name: str) -> str:
    return str(name).strip().replace("/", "_").replace(" ", "_")


def _extract_audio_bytes(row: pd.Series) -> bytes | None:
    """Support both common HF parquet layouts for Audio feature."""
    # Case A: flattened column `audio.bytes`
    if "audio.bytes" in row.index:
        b = row.get("audio.bytes")
        if isinstance(b, memoryview):
            return b.tobytes()
        if isinstance(b, (bytes, bytearray)):
            return bytes(b)

    # Case B: struct-like column `audio` that may be dict-like
    if "audio" in row.index:
        audio_obj = row.get("audio")
        if isinstance(audio_obj, dict):
            b = audio_obj.get("bytes")
            if isinstance(b, memoryview):
                return b.tobytes()
            if isinstance(b, (bytes, bytearray)):
                return bytes(b)

    return None


def _read_split_parquet(path: str) -> pd.DataFrame:
    """Read parquet with pyarrow; fallback to all columns if projection fails."""
    preferred_cols = ["audio", "audio.bytes", "reciter", "duration"]
    try:
        return pd.read_parquet(path, engine="pyarrow", columns=preferred_cols)
    except Exception:
        return pd.read_parquet(path, engine="pyarrow")


def _maybe_resample(wav: np.ndarray, sr: int, target_sr: int) -> tuple[np.ndarray, int]:
    if sr == target_sr:
        return wav, sr

    # Optional resampling if scipy is available.
    try:
        from scipy.signal import resample_poly

        wav_f = wav.astype(np.float32)
        if wav_f.ndim > 1:
            wav_f = np.mean(wav_f, axis=1)
        out = resample_poly(wav_f, target_sr, sr)
        return out.astype(np.float32), target_sr
    except Exception:
        # Keep original sample rate if scipy missing.
        return wav, sr


def download_split_parquet(
    split_name: str,
    max_per_reciter: int,
    allowed_reciters: set[str] | None = None,
):
    print(f"\nDownloading split={split_name} using direct parquet...")

    split_audio_dir = AUDIO_DIR / split_name
    split_audio_dir.mkdir(parents=True, exist_ok=True)

    api = HfApi()
    repo_files = api.list_repo_files(DATASET_REPO, repo_type="dataset")
    parquet_files = [
        f for f in repo_files if f.startswith(f"data/{split_name}-") and f.endswith(".parquet")
    ]

    print(f"Found {len(parquet_files)} parquet files for {split_name}.")

    reciter_counts = defaultdict(int)
    saved_samples = []
    stats = Counter()

    pbar = tqdm(parquet_files, desc=f"{split_name} parquet")
    for pq_file in pbar:
        local_path = None
        try:
            local_path = hf_hub_download(
                repo_id=DATASET_REPO,
                filename=pq_file,
                repo_type="dataset",
            )
            df = _read_split_parquet(local_path)
        except Exception as e:
            print(f"Skip parquet {pq_file}: {e}")
            stats["parquet_read_error"] += 1
            continue

        for _, row in df.iterrows():
            reciter_name = row.get("reciter")
            if reciter_name is None or str(reciter_name).strip() == "":
                stats["missing_reciter"] += 1
                continue

            safe_reciter = _safe_reciter_name(reciter_name)

            if allowed_reciters is not None and safe_reciter not in allowed_reciters:
                stats["not_allowed_reciter"] += 1
                continue

            if reciter_counts[safe_reciter] >= max_per_reciter:
                stats["quota_reached"] += 1
                continue

            wav_bytes = _extract_audio_bytes(row)
            if wav_bytes is None or len(wav_bytes) == 0:
                stats["missing_audio_bytes"] += 1
                continue

            try:
                wav, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
            except Exception:
                stats["audio_decode_error"] += 1
                continue

            if wav is None or len(wav) == 0:
                stats["empty_audio"] += 1
                continue

            if wav.ndim > 1:
                wav = np.mean(wav, axis=1)

            duration = row.get("duration")
            if duration is None or (isinstance(duration, float) and np.isnan(duration)):
                duration = len(wav) / float(sr)

            if duration < 1.5 or duration > 30:
                stats["duration_out_of_range"] += 1
                continue

            wav, sr = _maybe_resample(wav, int(sr), SAMPLE_RATE)

            spk_dir = split_audio_dir / safe_reciter
            spk_dir.mkdir(parents=True, exist_ok=True)

            idx = reciter_counts[safe_reciter]
            out_path = spk_dir / f"sample_{idx:03d}.wav"
            sf.write(str(out_path), wav, sr)

            saved_samples.append(
                {
                    "audio_filepath": str(out_path.absolute()),
                    "duration": float(duration),
                    "label": safe_reciter,
                }
            )
            reciter_counts[safe_reciter] += 1
            stats["saved"] += 1

        if local_path:
            try:
                os.remove(local_path)
            except Exception:
                pass

        pbar.set_postfix({"saved": stats["saved"], "reciters": len(reciter_counts)})

    print(
        f"Collected {len(saved_samples):,} samples from {len(reciter_counts)} reciters "
        f"for split={split_name}."
    )
    print(f"Skip stats ({split_name}): {dict(stats)}")

    return saved_samples, reciter_counts, stats


def _write_manifest(path: Path, rows: list[dict]):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def prepare_datasets():
    train_samples, train_counts, _ = download_split_parquet(
        "train", TRAIN_SAMPLES_PER_RECITER
    )

    valid_reciters = {r for r, c in train_counts.items() if c >= MIN_TRAIN_SAMPLES}
    train_samples = [s for s in train_samples if s["label"] in valid_reciters]

    print(f"\nAccepted reciters for training: {len(valid_reciters)}")

    val_samples, _, _ = download_split_parquet(
        "validation", VAL_SAMPLES_PER_RECITER, allowed_reciters=valid_reciters
    )
    test_samples, _, _ = download_split_parquet(
        "test", TEST_SAMPLES_PER_RECITER, allowed_reciters=valid_reciters
    )

    train_path = MANIFEST_DIR / "train_manifest.json"
    val_path = MANIFEST_DIR / "val_manifest.json"
    test_path = MANIFEST_DIR / "test_manifest.json"

    _write_manifest(train_path, train_samples)
    _write_manifest(val_path, val_samples)
    _write_manifest(test_path, test_samples)

    labels = sorted(valid_reciters)
    with open(MANIFEST_DIR / "labels.json", "w", encoding="utf-8") as f:
        json.dump(labels, f, indent=2, ensure_ascii=False)

    print("\nBuilt NeMo manifests:")
    print(f"  Train: {len(train_samples):,} -> {train_path}")
    print(f"  Val:   {len(val_samples):,} -> {val_path}")
    print(f"  Test:  {len(test_samples):,} -> {test_path}")
    print(f"  Labels: {len(labels)} classes")

    return str(train_path), str(val_path), str(test_path), labels


def fine_tune_titanet(train_manifest: str, val_manifest: str, labels: list[str]):
    try:
        import nemo.collections.asr as nemo_asr
        import pytorch_lightning as pl
        from omegaconf import open_dict
    except Exception as e:
        raise RuntimeError(
            "NeMo dependencies are not available. Install compatible versions for Kaggle."
        ) from e

    print(f"\nFine-tuning TitaNet on {len(labels)} reciters...")

    speaker_model = nemo_asr.models.EncDecSpeakerLabelModel.from_pretrained(
        model_name=PRETRAINED_MODEL
    )

    cfg = speaker_model.cfg
    with open_dict(cfg):
        cfg.decoder.num_classes = len(labels)

        cfg.train_ds.manifest_filepath = train_manifest
        cfg.train_ds.labels = labels
        cfg.train_ds.batch_size = BATCH_SIZE
        cfg.train_ds.shuffle = True

        cfg.validation_ds.manifest_filepath = val_manifest
        cfg.validation_ds.labels = labels
        cfg.validation_ds.batch_size = BATCH_SIZE * 2
        cfg.validation_ds.shuffle = False

        cfg.optim.lr = LEARNING_RATE
        cfg.optim.weight_decay = 1e-3

    speaker_model.setup_training_data(cfg.train_ds)
    speaker_model.setup_validation_data(cfg.validation_ds)
    speaker_model.change_labels(new_labels=labels)

    # Freeze preprocessor only.
    for name, param in speaker_model.named_parameters():
        if "preprocessor" in name:
            param.requires_grad = False

    trainer = pl.Trainer(
        max_epochs=NUM_EPOCHS,
        accelerator="gpu" if DEVICE == "cuda" else "cpu",
        devices=1,
        precision=16 if DEVICE == "cuda" else 32,
        log_every_n_steps=50,
        enable_progress_bar=True,
        default_root_dir=str(MODEL_DIR),
    )
    trainer.fit(speaker_model)

    final_path = MODEL_DIR / "titanet_everyayah.nemo"
    speaker_model.save_to(str(final_path))
    print(f"Saved model: {final_path}")
    return str(final_path)


def main():
    print("=" * 70)
    print("Reciter ID: EveryAyah + TitaNet")
    print("=" * 70)

    train_manifest, val_manifest, test_manifest, labels = prepare_datasets()

    if len(labels) == 0:
        print("No valid reciters found after filtering.")
        return

    model_path = fine_tune_titanet(train_manifest, val_manifest, labels)
    print("\nTraining complete.")
    print(f"Model: {model_path}")
    print(f"Test manifest ready: {test_manifest}")


if __name__ == "__main__":
    main()
