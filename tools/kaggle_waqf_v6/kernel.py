"""Kaggle GPU run of the waqf glyph v6 recipe (3 seeds), same flags as the CPU runs.

Input dataset must contain:
  multiprint_crops_v6.npz   (from data/cv/bundles/merge_v6.py on cloud/waqf-v6-training)
  code.tar.gz               (pipeline/ + requirements/ from that branch, with train_cnn_gpu_ckpt.patch applied)
Outputs land in /kaggle/working/kaggle_v6/: 4 model files per seed, logs, env.json.
"""
import glob
import json
import os
import subprocess
import sys
import tarfile
import time

W = '/kaggle/working'
REPO = f'{W}/repo'
OUT = f'{W}/kaggle_v6'
os.makedirs(REPO, exist_ok=True)
os.makedirs(OUT, exist_ok=True)


def find(name):
    hits = glob.glob(f'/kaggle/input/**/{name}', recursive=True)
    if not hits:
        raise SystemExit(f'{name} not found under /kaggle/input')
    return hits[0]


bundle = find('multiprint_crops_v6.npz')
code = glob.glob('/kaggle/input/**/code.tar.gz', recursive=True)
if code:
    with tarfile.open(code[0]) as t:
        t.extractall(REPO)
else:  # Kaggle sometimes unpacks archives on upload
    src = os.path.dirname(find('pipeline/cv_waqf/train_cnn.py'))
    subprocess.run(['cp', '-r', os.path.dirname(os.path.dirname(src)) + '/pipeline', REPO], check=True)
assert 'WAQF_DEVICE' in open(f'{REPO}/pipeline/cv_waqf/train_cnn.py').read(), \
    'train_cnn.py lacks the GPU patch (apply train_cnn_gpu_ckpt.patch before packing)'

# Same OpenCV as requirements/cv.txt; drop Kaggle's preinstalled cv2 builds first.
pip = [sys.executable, '-m', 'pip']
subprocess.run(pip + ['uninstall', '-y', '-q', 'opencv-python', 'opencv-python-headless',
                      'opencv-contrib-python', 'opencv-contrib-python-headless'], check=False)
subprocess.run(pip + ['install', '-q', 'opencv-python==5.0.0.93', 'onnx>=1.16', 'numpy>=2.0'], check=True)

import torch  # noqa: E402  (only to record the environment; training runs in subprocesses)

gpus = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
print('GPUs:', gpus, flush=True)
if not gpus:
    raise SystemExit('no GPU visible: enable a GPU accelerator for this notebook')
env = {'python': sys.version.split()[0], 'torch': torch.__version__,
       'cuda': torch.version.cuda, 'gpus': gpus, 'seeds': {}}

# One seed per GPU; the third shares GPU 0 (each run needs well under 2 GB of GPU memory).
plan = [(s, s % len(gpus)) for s in (0, 1, 2)]
procs = {}
for seed, gpu in plan:
    cmd = [sys.executable, '-m', 'pipeline.cv_waqf', 'train-cnn', '--bundle', bundle,
           '--out', f'{OUT}/v6_s{seed}.onnx', '--seed', str(seed),
           '--cap-none', '26000', '--augment', '2', '--epochs', '25']
    run_env = dict(os.environ, PYTHONPATH=REPO, OMP_NUM_THREADS='1',
                   CUDA_VISIBLE_DEVICES=str(gpu), WAQF_DEVICE='cuda',
                   WAQF_CKPT_DIR=f'{W}/ck/s{seed}')
    log = open(f'{OUT}/v6_s{seed}.log', 'a')
    procs[seed] = (subprocess.Popen(cmd, cwd=REPO, env=run_env, stdout=log, stderr=subprocess.STDOUT),
                   time.time(), gpu)
    print(f'started seed {seed} on GPU {gpu}', flush=True)

for seed, (p, t0, gpu) in procs.items():
    code_ = p.wait()
    env['seeds'][seed] = {'exit': code_, 'wall_s': round(time.time() - t0), 'gpu': gpu}
    print(f'seed {seed}: exit={code_} wall={time.time() - t0:.0f}s', flush=True)

json.dump(env, open(f'{OUT}/env.json', 'w'), indent=2)
for seed in (0, 1, 2):
    print(f'--- seed {seed}')
    print(''.join(l for l in open(f'{OUT}/v6_s{seed}.log') if 'epoch 25' in l or l.startswith('wrote')))
missing = [f for s in (0, 1, 2) for f in (f'v6_s{s}.onnx', f'v6_s{s}.json', f'v6_s{s}_gate.onnx', f'v6_s{s}_gate.json')
           if not os.path.exists(f'{OUT}/{f}')]
print('MISSING:', missing if missing else 'none (12/12 model files)')
