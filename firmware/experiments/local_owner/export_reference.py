"""Reconstruct a FLOAT research reference from MIT Espressif quantized weights.

This is not the original pre-quantization model. Quantization nodes are removed
and stored integer weights are dequantized. Deployment must be revalidated.
"""
import json
import wave
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
from onnx import helper as h, numpy_helper as nh, TensorProto as T
from inspect_espdl import inspect

ROOT = Path(__file__).parent
DATA = ROOT / 'research'
TYPES = {1: '<f4', 3: 'i1', 5: '<i2', 6: '<i4', 7: '<i8'}


def export(model_path, output):
    graph = inspect(model_path)
    raw = model_path.read_bytes()
    arrays = {}
    weights = {n['inputs'][1]: n['op'] for n in graph['nodes'] if n['op'] in ('Conv', 'Gemm')}
    for t in graph['tensors']:
        dtype = TYPES[t['dtype']]
        a = np.frombuffer(raw, dtype=dtype, count=int(np.prod(t['dims'])),
                          offset=t['data_offset']).reshape(t['dims'])
        exps = np.asarray(t['exponents'], dtype=np.float64)
        scale = np.exp2(exps)
        if t['name'] in weights:
            # SIMD storage is (N/align), spatial..., C, align; the recorded
            # WCN/HWCN dimensions alone do not describe its physical layout.
            n, c = t['dims'][-1], t['dims'][-2]
            spatial = t['dims'][:-2]
            align = 16 if t['dtype'] == 3 else 8
            assert n % align == 0
            packed = a.reshape(n // align, *spatial, c, align)
            a = np.moveaxis(packed, -1, 1).reshape(n, *spatial, c)
            a = a * scale.reshape((-1,) + (1,) * (a.ndim - 1))
            if weights[t['name']] == 'Conv':
                a = a.transpose(0, 2, 1)
            else:
                a = a.reshape(n, c).T
            arrays[t['name']] = a.astype(np.float32).copy()
        else:
            arrays[t['name']] = (a * scale).astype(np.float32)
    nodes, initializers, aliases, spatial_values, restored_values = [], {}, {}, {}, set()
    axes_names = {n['inputs'][1] for n in graph['nodes'] if n['op'] == 'ReduceMean'}
    for name in axes_names:
        arrays[name] = arrays[name].astype(np.int64)
    for n in graph['nodes']:
        inputs = [aliases.get(x, x) for x in n['inputs']]
        outputs, name, op = n['outputs'], n['name'], n['op']
        attrs = {k: v for k, v in n['attributes'].items()
                 if k not in ('quant_type', 'lut', 'activation')}
        if op == 'RequantizeLinear':
            aliases[outputs[0]] = inputs[0]
            continue
        if op != 'Conv':
            for value in inputs:
                if value in spatial_values and value not in restored_values:
                    axis = value + '_squeeze_axis'
                    initializers[axis] = nh.from_array(np.array([3], dtype=np.int64), axis)
                    nodes.append(h.make_node('Squeeze', [spatial_values[value], axis], [value + '_ncw'],
                                             name=value + '_restore_rank'))
                    nodes.append(h.make_node('Transpose', [value + '_ncw'], [value],
                                             name=value + '_restore_layout', perm=[0, 2, 1]))
                    restored_values.add(value)
        active = n['attributes'].get('activation') == 'Relu'
        intermediate = outputs[0] + '_pre_relu' if active else outputs[0]
        if op == 'Conv':
            # Place time on the HEIGHT axis of a 2-D convolution. ESP-DL's
            # dual-core scheduler splits height; the 1-D width mapping cannot
            # exploit both cores. This adds only singleton dimensions.
            arrays[inputs[1]] = arrays[inputs[1]][..., None]
            axes_name = name + '_height_axes'
            initializers[axes_name] = nh.from_array(np.array([3], dtype=np.int64), axes_name)
            attrs['kernel_shape'] = [attrs['kernel_shape'][0], 1]
            attrs['dilations'] = [attrs['dilations'][0], 1]
            attrs['strides'] = [attrs['strides'][0], 1]
            attrs['pads'] = [0, 0, 0, 0]
            if inputs[0] in spatial_values:
                conv_input = spatial_values[inputs[0]]
            else:
                nodes.append(h.make_node('Transpose', [inputs[0]], [name + '_ncw'],
                                         name=name + '_transpose_in', perm=[0, 2, 1]))
                nodes.append(h.make_node('Unsqueeze', [name + '_ncw', axes_name], [name + '_nchw'],
                                         name=name + '_unsqueeze'))
                conv_input = name + '_nchw'
            nodes.append(h.make_node(op, [conv_input] + inputs[1:], [name + '_conv'],
                                     name=name, **attrs))
            conv_out = name + '_conv'
            if active:
                conv_out = name + '_activated'
                nodes.append(h.make_node('Relu', [name + '_conv'], [conv_out], name=name + '_relu'))
            spatial_values[outputs[0]] = conv_out
            active = False
        else:
            nodes.append(h.make_node(op, inputs, [intermediate], name=name, **attrs))
        if active:
            nodes.append(h.make_node('Relu', [intermediate], outputs, name=name + '_relu'))
        for name in inputs:
            if name in arrays:
                initializers[name] = nh.from_array(arrays[name], name)
    shape = graph['value_info']['input']['dims']
    result = h.make_model(h.make_graph(nodes, 'reconstructed_sv_reference',
                          [h.make_tensor_value_info('input', T.FLOAT, shape)],
                          [h.make_tensor_value_info('embedding', T.FLOAT, [1, 512])],
                          list(initializers.values())), opset_imports=[h.make_opsetid('', 18)])
    result.ir_version = 10
    # Do not reuse ESP-PPQ's generated-variable namespace on a new import.
    for tensor in result.graph.initializer:
        if tensor.name.startswith('PPQ_'):
            tensor.name = 'reference_' + tensor.name
    for node in result.graph.node:
        for i, value in enumerate(node.input):
            if value.startswith('PPQ_'):
                node.input[i] = 'reference_' + value
    onnx.checker.check_model(result)
    onnx.save(result, output)
    return shape


def fbank(pcm, frames=300):
    # Matches the documented ESP-DL/Kaldi configuration, not librosa defaults.
    length = (frames - 1) * 160 + 400
    if len(pcm) > length:
        start = (len(pcm) - length) // 2
        pcm = pcm[start:start + length]
    else:
        pcm = np.pad(pcm, (0, length - len(pcm)))
    windows = np.lib.stride_tricks.sliding_window_view(pcm, 400)[::160].copy()
    windows -= windows.mean(axis=1, keepdims=True)
    windows[:, 1:] -= .97 * windows[:, :-1].copy()
    windows[:, 0] *= .03
    windows *= np.hamming(400).astype(np.float32)
    power = np.abs(np.fft.rfft(windows, n=512)) ** 2
    # Kaldi uses equally spaced mel vertices and the FFT bins below Nyquist.
    mel = lambda x: 1127. * np.log1p(x / 700.)
    centers = np.linspace(mel(20.), mel(8000.), 82)
    bins = mel(np.arange(257) * (16000. / 512))
    weights = np.maximum(0, np.minimum(
        (bins[None, :] - centers[:-2, None]) / np.diff(centers)[:-1, None],
        (centers[2:, None] - bins[None, :]) / np.diff(centers)[1:, None]))
    features = np.log(np.maximum(power @ weights.T, np.finfo(np.float32).eps)).astype(np.float32)
    return (features - features.mean(axis=0, keepdims=True))[None]


def cosine(a, b):
    return float(np.sum(a * b) / np.linalg.norm(a) / np.linalg.norm(b))


if __name__ == '__main__':
    output = DATA / 'sv_reference_3s.onnx'
    shape = export(DATA / 'sv_tdnn_tiny_3s.espdl', output)
    session = ort.InferenceSession(str(output), providers=['CPUExecutionProvider'])
    embeddings = []
    for name in ('a', 'b', 'c'):
        with wave.open(str(DATA / f'audio_{name}.wav')) as w:
            assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2').astype(np.float32) / 32768.
        features = fbank(pcm, shape[1])
        np.save(DATA / f'features_{name}.npy', features)
        embedding = session.run(None, {'input': features})[0]
        np.save(DATA / f'embedding_{name}_reference.npy', embedding)
        embeddings.append(embedding)
    report = {'reference': 'dequantized reconstruction, not original float weights',
              'same_ab': cosine(embeddings[0], embeddings[1]),
              'different_bc': cosine(embeddings[1], embeddings[2]),
              'different_ac': cosine(embeddings[0], embeddings[2])}
    (DATA / 'reference_results.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
