"""Experimental S3 conversion; calibration is NOT a biometric accuracy test."""
import json
import argparse
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader
from esp_ppq import QuantizationSettingFactory, TargetPlatform
from esp_ppq.api import espdl_quantize_onnx, export_ppq_graph
from esp_ppq.executor import TorchExecutor
from export_reference import cosine

ROOT = Path(__file__).parent / 'research'
parser = argparse.ArgumentParser()
parser.add_argument('--bits', type=int, choices=(8, 16), default=16)
parser.add_argument('--w8a16', action='store_true')
parser.add_argument('--hybrid', action='store_true')
args = parser.parse_args()
stem = 'sv_tdnn_3s_s3_w8a16' if args.w8a16 else f'sv_tdnn_3s_s3_int{args.bits}'
if args.hybrid:
    stem += '_hybrid'
torch.set_num_threads(4)
torch.manual_seed(927)
features = [torch.from_numpy(np.load(ROOT / f'features_{n}.npy')) for n in 'abc']
# These 3 public example clips only establish conversion integrity. A separate,
# speaker-disjoint evaluation set is required before enabling authentication.
dataset = [x for _ in range(4) for x in features]
setting = QuantizationSettingFactory.espdl_setting(num_of_bits=args.bits)
import onnx
model = onnx.load(ROOT / 'sv_reference_3s.onnx')
for n in model.graph.node:
    if (args.bits == 8 or args.hybrid) and ('/pool/' in n.name or '/seg_1/' in n.name or '/frame_1/' in n.name):
        setting.dispatching_table.append(n.name, TargetPlatform.ESPDL_S3_INT16)

graph = espdl_quantize_onnx(
    onnx_import_file=str(ROOT / 'sv_reference_3s.onnx'),
    espdl_export_file=str(ROOT / (stem + '.espdl')),
    calib_dataloader=DataLoader(dataset, batch_size=None), calib_steps=len(dataset),
    input_shape=[1, 300, 80], inputs=[features[0]],
    target='esp32s3', num_of_bits=args.bits, setting=setting,
    quant_type='w8a16' if args.w8a16 else None,
    collate_fn=lambda x: x, device='cpu', error_report=False,
    export_test_values=True, verbose=0,
)
export_ppq_graph(graph=graph, platform=TargetPlatform.NATIVE,
                 graph_save_to=str(ROOT / (stem + '.native')))
executor = TorchExecutor(graph, device='cpu')
values = [executor.forward(x)[0].detach().numpy() for x in features]
for name, value in zip('abc', values):
    np.save(ROOT / (stem + f'_embedding_{name}.npy'), value)
report = {'purpose': 'conversion only; no FAR/FRR established',
          'same_ab': cosine(values[0], values[1]),
          'different_bc': cosine(values[1], values[2]),
          'different_ac': cosine(values[0], values[2]),
          'reference_cosines': [cosine(y, np.load(ROOT / f'embedding_{n}_reference.npy'))
                                for n, y in zip('abc', values)],
          'model_bytes': (ROOT / (stem + '.espdl')).stat().st_size}
(ROOT / (stem + '_results.json')).write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
