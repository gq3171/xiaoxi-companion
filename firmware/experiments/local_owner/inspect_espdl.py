"""Inspect unencrypted EDL2 model structure using Espressif's espdl.fbs layout.

Read-only research tool; never converts a P4 model into an S3 model.
"""
import argparse
import collections
import hashlib
import json
import struct
from pathlib import Path


class Table:
    def __init__(self, data, pos):
        self.data, self.pos = data, pos

    def number(self, pos, fmt):
        return struct.unpack_from('<' + fmt, self.data, pos)[0]

    def field(self, index):
        vt = self.pos - self.number(self.pos, 'i')
        offset = 4 + index * 2
        if offset >= self.number(vt, 'H'):
            return 0
        value = self.number(vt + offset, 'H')
        return self.pos + value if value else 0

    def scalar(self, index, fmt='i', default=0):
        p = self.field(index)
        return self.number(p, fmt) if p else default

    def indirect(self, p):
        return p + self.number(p, 'I') if p else 0

    def table(self, index):
        return Table(self.data, self.indirect(self.field(index)))

    def string_at(self, p):
        p = self.indirect(p)
        return self.data[p + 4:p + 4 + self.number(p, 'I')].decode() if p else ''

    def string(self, index):
        return self.string_at(self.field(index))

    def vector(self, index, kind='q'):
        p = self.indirect(self.field(index))
        if not p:
            return []
        count = self.number(p, 'I')
        size = 4 if kind in ('table', 'string') else struct.calcsize('<' + kind)
        values = [p + 4 + n * size for n in range(count)]
        if kind == 'table':
            return [Table(self.data, self.indirect(v)) for v in values]
        if kind == 'string':
            return [self.string_at(v) for v in values]
        return [self.number(v, kind) for v in values]


def inspect(path):
    data = Path(path).read_bytes()
    assert data[:4] == b'EDL2' and struct.unpack_from('<I', data, 4)[0] == 0
    root = Table(data, 16 + struct.unpack_from('<I', data, 16)[0])
    graph = root.table(7)
    tensors = []
    for t in graph.vector(2, 'table'):
        tensors.append(dict(name=t.string(6), dims=t.vector(0), dtype=t.scalar(1),
                            exponents=t.vector(13), data_offset=t.indirect(t.field(8)) + 4))
    nodes = []
    for n in graph.vector(0, 'table'):
        attrs = {}
        for a in n.vector(5, 'table'):
            typ = a.scalar(3)
            if typ == 2:
                val = a.scalar(5, 'q')
            elif typ == 1:
                val = a.scalar(4, 'f')
            elif typ == 7:
                val = a.vector(11)
            elif typ == 3:
                val = bytes(a.vector(6, 'B')).decode()
            else:
                val = {'attribute_type': typ}
            attrs[a.string(0)] = val
        nodes.append(dict(name=n.string(2), op=n.string(3), inputs=n.vector(0, 'string'),
                          outputs=n.vector(1, 'string'), attributes=attrs))
    metadata = {x.string(0): x.string(1) for x in root.vector(8, 'table')}
    info = {}
    for field in (4, 5, 6):
        for v in graph.vector(field, 'table'):
            shape = v.table(1).table(1).table(1)
            dims = [d.table(0).scalar(1, 'q') for d in shape.vector(0, 'table')]
            info[v.string(0)] = dict(dims=dims, exponents=v.vector(3))
    return dict(file=str(path), bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                producer=root.string(2), metadata=metadata, nodes=nodes, tensors=tensors,
                value_info=info, op_counts=dict(collections.Counter(n['op'] for n in nodes)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('model')
    args = parser.parse_args()
    print(json.dumps(inspect(args.model), indent=2))
