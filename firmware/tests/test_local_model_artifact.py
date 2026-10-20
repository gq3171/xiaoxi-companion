"""Verify deployed model, integrity header and compiled operator requirements agree."""
import hashlib
import importlib.util
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LocalModelArtifactTests(unittest.TestCase):
    def test_artifact_hash_quantization_and_operator_kernel_coverage(self):
        spec = importlib.util.spec_from_file_location('owner_model_inspector', ROOT / 'experiments/local_owner/inspect_espdl.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        model = ROOT / 'models/pet_owner_sv_s3.espdl'
        data = model.read_bytes()
        header = (ROOT / 'main/pet_owner_model.h').read_text()
        self.assertIn(hashlib.sha256(data).hexdigest(), header)
        self.assertIn(f'{len(data)}u', header)
        graph = module.inspect(model)
        self.assertEqual(graph['value_info']['input']['dims'], [1, 300, 80])
        self.assertEqual(graph['value_info']['embedding']['dims'], [1, 512])
        self.assertTrue(all(len(t['exponents']) <= 1 for t in graph['tensors']))
        req = (ROOT / 'models/owner.compile_req.yml').read_text()
        ops_section, kernels_section = req.split('ops:\n')[1].split('kernels:\n')
        ops = set(re.findall(r'^  - (\w+)$', ops_section, re.M))
        kernels = set(re.findall(r'^  - (\w+)$', kernels_section, re.M))
        self.assertLessEqual(set(graph['op_counts']), ops)
        for node in graph['nodes']:
            if node['op'] not in ('Conv', 'Gemm'):
                continue
            attrs = node['attributes']
            self.assertEqual(attrs['quant_type'], 'S16')
            kshape = attrs.get('kernel_shape', [1, 1])
            base = '11cn' if kshape == [1, 1] else 'hwcn'
            activation = '_relu' if attrs.get('activation') == 'Relu' else ''
            self.assertIn(f'dl_tie728_s16_conv2d_{base}_bias{activation}', kernels)
