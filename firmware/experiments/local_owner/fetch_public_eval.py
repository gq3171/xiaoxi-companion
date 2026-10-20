"""Download a small LibriSpeech test-clean subset for local engineering tests.

Uses public dataset rows only; never uploads device or user recordings.
"""
import concurrent.futures
import hashlib
import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent / 'research' / 'eval_public'
ROOT.mkdir(exist_ok=True)
BASE = ('https://datasets-server.huggingface.co/rows?dataset=openslr%2Flibrispeech_asr'
        '&config=clean&split=test&length=10&offset=')


def fetch(offset):
    data = json.load(urllib.request.urlopen(BASE + str(offset), timeout=25))
    result = []
    for item in data['rows']:
        row = item['row']
        path = ROOT / (row['id'] + '.flac')
        if not path.exists():
            for attempt in range(3):
                try:
                    audio = urllib.request.urlopen(row['audio'][0]['src'], timeout=30).read()
                    assert audio[:4] == b'fLaC'
                    path.write_bytes(audio)
                    break
                except Exception:
                    if attempt == 2: raise
                    time.sleep(.5)
        result.append(dict(id=row['id'], speaker_id=row['speaker_id'], row_idx=item['row_idx'],
                           file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    return result


if __name__ == '__main__':
    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for batch in pool.map(fetch, range(0, 2600, 200)):
            rows.extend(batch)
            print('public samples cached:', len(rows), flush=True)
    manifest = dict(dataset='openslr/librispeech_asr', config='clean', split='test',
                    revision='71cacbfb7e2354c4226d01e70d77d5fca3d04ba1',
                    source='https://www.openslr.org/12', license='CC-BY-4.0', rows=rows)
    (ROOT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
