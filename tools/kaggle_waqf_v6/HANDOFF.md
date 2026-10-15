# Kaggle GPU run of waqf glyph v6 — hand-off for a session on the Mac

Goal: train the 3 v6 seeds on a Kaggle GPU (T4) with exactly the CPU recipe, as a faster second set next
to the cloud CPU run (models/cloud5/, pushed separately to cloud/waqf-v4-training-zm81hi).
Report val_acc only; scoring against scans is a separate step.

Files in this folder (tools/kaggle_waqf_v6/ on branch cloud/waqf-v4-training-zm81hi):
- `train_cnn_gpu_ckpt.patch` — against cloud/waqf-v6-training @ be428e5. Adds two opt-in env vars to
  pipeline/cv_waqf/train_cnn.py: `WAQF_DEVICE` (cpu default; cuda for GPU) and `WAQF_CKPT_DIR` (per-epoch
  checkpoint + resume). With neither set, CPU weights are bit-identical to before (tested). The CUDA path was
  NOT tested (no GPU in the cloud box) — the first Kaggle run is its test.
- `kernel.py` — the Kaggle script. Finds the bundle + code in /kaggle/input, installs opencv-python 5.0.0.93
  and onnx, runs seeds 0/1/2 concurrently (seed s on GPU s % n_gpus) with the fixed flags
  `--cap-none 26000 --augment 2 --epochs 25`, writes /kaggle/working/kaggle_v6/{12 model files, logs, env.json}.
- `kernel-metadata.template.json` — fill in the Kaggle username.

## Steps (Mac, Kaggle CLI already logged in)

```bash
cd <repo>
git fetch origin cloud/waqf-v6-training cloud/waqf-v4-training-zm81hi
git worktree add /tmp/waqf-v6 origin/cloud/waqf-v6-training     # leaves your checkout alone
cd /tmp/waqf-v6
git show origin/cloud/waqf-v4-training-zm81hi:tools/kaggle_waqf_v6/train_cnn_gpu_ckpt.patch | git apply
python data/cv/bundles/merge_v6.py            # -> data/cv/bundles/multiprint_crops_v6.npz (87,053 crops)

mkdir -p /tmp/waqf-kaggle/data /tmp/waqf-kaggle/kernel
cp data/cv/bundles/multiprint_crops_v6.npz /tmp/waqf-kaggle/data/
tar czf /tmp/waqf-kaggle/data/code.tar.gz pipeline requirements
for f in kernel.py kernel-metadata.template.json; do
  git show origin/cloud/waqf-v4-training-zm81hi:tools/kaggle_waqf_v6/$f > /tmp/waqf-kaggle/kernel/$f
done
```

Dataset (private):
```bash
cd /tmp/waqf-kaggle/data
kaggle datasets init -p .        # edit dataset-metadata.json: title "waqf-v6-kit", id "<user>/waqf-v6-kit"
kaggle datasets create -p .      # later updates: kaggle datasets version -p . -m "..."
kaggle datasets status <user>/waqf-v6-kit   # wait for "ready"
```

Kernel:
```bash
cd /tmp/waqf-kaggle/kernel
sed "s/KAGGLE_USER/<user>/g" kernel-metadata.template.json > kernel-metadata.json
kaggle kernels push -p .
kaggle kernels status <user>/waqf-v6-gpu      # poll every few minutes until complete / error
kaggle kernels output <user>/waqf-v6-gpu -p ./out
```

Accelerator: the template sets `"enable_gpu": true` and `"machine_shape": "NvidiaTeslaT4"`. Check the
installed CLI's docs (`kaggle kernels push --help`, the kernel-metadata wiki) for the exact key/value that
selects **T4 x2**; if the CLI cannot pick it, open the notebook on kaggle.com → Settings → Accelerator →
"GPU T4 x2" and run it there (Save Version → Save & Run All). One GPU also works (all seeds share it).
The log line `GPUs: [...]` in the output confirms what it got.

## Deliver

- Copy `out/kaggle_v6/*.onnx`, `*.json` (12 files) to `models/kaggle_v6/` in the main checkout (local; do not
  touch models/waqf_glyph_*).
- Write `models/kaggle_v6/RESULTS.md`: per seed final `gate epoch 25` / `symbol epoch 25` val_acc and
  wall time (from the logs / env.json), torch + CUDA + GPU names, anything unusual. Note: GPU runs are not
  bit-identical to the CPU runs (cuDNN kernels, CUDA RNG for dropout), so expect val_acc close to, not equal
  to, models/cloud5/.
- If a seed fails on CUDA, paste the traceback back rather than changing the flags.
- Clean up: `git worktree remove /tmp/waqf-v6`.
