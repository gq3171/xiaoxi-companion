"""Small held-out recording smoke evaluation; not a deployment accuracy claim."""
import argparse
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
import soundfile as sf
import torch
from esp_ppq.api import load_native_graph
from esp_ppq.executor import TorchExecutor
from export_reference import fbank, cosine

ROOT = Path(__file__).parent / 'research'
parser = argparse.ArgumentParser()
parser.add_argument('--stem', default='sv_tdnn_3s_s3_int16')
parser.add_argument('--test-seconds', type=float, default=3.015)
args = parser.parse_args()
torch.set_num_threads(4)
rows = json.loads((ROOT / 'eval_public/manifest.json').read_text())['rows']
executor = TorchExecutor(load_native_graph(str(ROOT / (args.stem + '.native'))), device='cpu')
reference = ort.InferenceSession(str(ROOT / 'sv_reference_3s.onnx'), providers=['CPUExecutionProvider'])
groups = {}
short_groups = {}
agreement = []
for row in rows:
    pcm, rate = sf.read(ROOT / 'eval_public' / row['file'], dtype='float32')
    assert rate == 16000 and pcm.ndim == 1
    if len(pcm) < 3 * rate:
        continue
    features = fbank(pcm)
    value = executor.forward(torch.from_numpy(features))[0].detach().numpy().flatten()
    baseline = reference.run(None, {'input': features})[0].flatten()
    agreement.append(cosine(value, baseline))
    value /= np.linalg.norm(value)
    groups.setdefault(str(row['speaker_id']), []).append(value)
    # Separate inference with shortened audio; never reuse its long embedding.
    short_len = int(args.test_seconds * rate)
    start = max(0, (len(pcm) - short_len) // 2)
    short_feature = fbank(pcm[start:start + short_len])
    short_value = executor.forward(torch.from_numpy(short_feature))[0].detach().numpy().flatten()
    short_value /= np.linalg.norm(short_value)
    short_groups.setdefault(str(row['speaker_id']), []).append(short_value)
    print('processed', row['id'], flush=True)
groups = {k: v for k, v in groups.items() if len(v) >= 4}
centroids = {}
for name, vectors in groups.items():
    template = np.mean(vectors[:3], axis=0)
    centroids[name] = template / np.linalg.norm(template)
genuine, impostor = [], []
for owner, template in centroids.items():
    for speaker, vectors in groups.items():
        for vector in short_groups[speaker][3:]:
            (genuine if speaker == owner else impostor).append(float(template @ vector))
report = {'purpose': 'engineering smoke test, English clean read speech only; not owner accuracy',
          'enrollment': '3 independent recordings; test uses fourth recording',
          'test_audio_seconds': args.test_seconds,
          'speakers': len(groups), 'genuine_trials': len(genuine), 'impostor_trials': len(impostor),
          'quantization_agreement_cosine_min': min(agreement),
          'quantization_agreement_cosine_mean': float(np.mean(agreement)),
          'genuine_score_range': [min(genuine), max(genuine)],
          'impostor_score_range': [min(impostor), max(impostor)],
          'threshold_sweep_exploratory_not_independent_validation': [
              {'threshold': t, 'false_accepts': sum(x >= t for x in impostor),
               'false_rejects': sum(x < t for x in genuine)} for t in (.25, .35, .45, .5, .55, .6, .65, .7)],
          'limitations': ['small sample size', 'no Mandarin/noise/distance/replay test',
                         'no independent validation of a selected threshold',
                         'no claim of disjointness from original pretraining data']}
suffix = '_public_eval.json' if args.test_seconds == 3.015 else f'_public_eval_{args.test_seconds:g}s.json'
(ROOT / (args.stem + suffix)).write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
