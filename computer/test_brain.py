import importlib.util
import io
import os
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
import zlib
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

spec = importlib.util.spec_from_file_location('brain', Path(__file__).with_name('brain.py'))
brain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brain)
ROOT = Path(__file__).resolve().parents[1]


class FakeProvider:
    key = 'private-test-provider-key'
    def __init__(self, replies=()):
        self.replies = iter(replies)
        self.searches, self.prompts = [], []
    def complete(self, system, messages, reflection=False, live=None):
        self.prompts.append((system, messages))
        return next(self.replies)
    def search(self, query):
        self.searches.append(query)
        return [{'title': '公开资料', 'link': 'https://example.org', 'snippet': '测试资料，不能作为主人事实。'}]


class BrainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiled = tempfile.TemporaryDirectory()
        if os.environ.get('DESKPET_TEST_NATIVE_LIBRARY'):
            cls.library = Path(os.environ['DESKPET_TEST_NATIVE_LIBRARY'])
            return
        cls.library = Path(cls.compiled.name) / 'memory.so'
        cjson = ROOT / 'firmware/managed_components/espressif__cjson/cJSON'
        if not (cjson/'cJSON.c').is_file():
            cjson=ROOT/'computer/vendor/cjson'
        subprocess.run(['cc', '-std=c17', '-D_POSIX_C_SOURCE=200809L', '-shared', '-fPIC', '-O2',
                        '-I', str(ROOT / 'firmware/main'), '-I', str(cjson),
                        str(ROOT / 'computer/brain_native.c'), str(ROOT / 'computer/brain_native_util.c'),
                        str(cjson / 'cJSON.c'), '-lm', '-o', str(cls.library)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.compiled.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = brain.BrainStore(Path(self.tmp.name) / 'brain.sqlite3', brain.NativeMemory(self.library))
        self.env = dict(device='001122334455', boot=1, session='a' * 32, generation=1)
        raw = brain.encode(brain.empty_memory()).decode()
        self.open = self.env | dict(memory_raw=raw, memory_crc=zlib.crc32(raw.encode()),
                                    identity_raw=json.dumps({'name': '小溪', 'soul': '逐渐成长'}))
        self.store.open(self.open)

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def add(self, text='我喜欢茶', op_id='b' * 32, **kwargs):
        return self.store.mutate(self.env | {'operation': dict(kind='add', op_id=op_id, role='user', text=text, owner=True) | kwargs})

    def test_ack_loss_retry_is_durable_and_reconnect_cannot_overwrite_newer_memory(self):
        first = self.add()
        self.assertEqual(first['result'], 1)
        again = self.add()
        self.assertTrue(again['duplicate'])
        self.assertEqual(again['revision'], first['revision'])
        self.assertEqual(len(again['memory']['history']), 1)
        other = brain.BrainStore(self.store.path, brain.NativeMemory(self.library))
        try:
            restored = other.open(self.open | {'boot': 2, 'session': 'c' * 32})
            self.assertEqual(restored['memory']['history'][0]['content'], '我喜欢茶')
            self.assertEqual(restored['identity']['name'], '小溪')
            self.assertEqual(other.db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        finally:
            other.db.close()

    def test_conflicting_id_stale_turn_and_old_boot_cannot_commit(self):
        self.add()
        with self.assertRaises(brain.Conflict): self.add('其他内容')
        self.store.admit(self.env | {'generation': 2})
        with self.assertRaises(brain.Conflict): self.add(op_id='c' * 32)
        self.store.open(self.open | {'boot': 2, 'session': 'd' * 32})
        with self.assertRaises(brain.Conflict): self.store.open(self.open)
        with self.assertRaises(brain.Conflict): self.store.open(self.open | {'device': 'ffeeddccbbaa', 'boot': 3})
        self.assertEqual(len(self.store.snapshot()['memory']['history']), 1)

    def test_transport_crc_and_memory_schema_are_checked_without_losing_state(self):
        with self.assertRaises(ValueError): self.store.open(self.open | {'memory_crc': 0})
        raw = json.dumps({'cards': [], 'history': 'bad', 'next_id': 1})
        with self.assertRaises(ValueError): self.store.open(self.open | {'memory_raw': raw, 'memory_crc': zlib.crc32(raw.encode())})
        self.assertEqual(self.store.snapshot()['identity']['name'], '小溪')

    def test_reordered_retry_deduplicates_and_torn_mirror_metadata_recovers(self):
        first = self.add()
        operation = dict(owner=True, text='我喜欢茶', role='user', op_id='b' * 32, kind='add')
        retry = self.store.mutate(self.env | {'operation': operation})
        self.assertTrue(retry['duplicate'])
        self.assertEqual(retry['revision'], first['revision'])
        raw = brain.encode(first['memory']).decode()
        recovered = self.store.open(self.open | dict(memory_raw=raw, memory_crc=zlib.crc32(raw.encode()), mirror_revision=1, mirror_crc=0))
        self.assertEqual(recovered['revision'], first['revision'])
        with self.assertRaises(brain.Conflict):
            self.store.open(self.open | dict(mirror_revision=1, mirror_crc=0))
        self.assertEqual(len(self.store.snapshot()['memory']['history']), 1)

    def test_bad_reflection_is_acknowledged_without_poisoning_following_operations(self):
        initial = self.store.snapshot()
        for i, raw in enumerate(('broken-json', json.dumps({'ops': [{}] * 9}))):
            request = self.env | {'operation': dict(kind='reflection', op_id=str(i) * 32, json=raw)}
            failed = self.store.mutate(request)
            self.assertTrue(failed['ok'])
            self.assertEqual(failed['result'], -1)
            self.assertEqual(failed['revision'], initial['revision'])
            self.assertEqual(failed['memory'], initial['memory'])
            self.assertTrue(self.store.mutate(request)['duplicate'])
        self.assertEqual(self.add()['result'], 1)

    def test_existing_reducer_rejects_invented_evidence_and_accepts_real_correction(self):
        source = self.add()['result']
        reflection = {'ops': [{'op': 'upsert', 'kind': 'preference', 'slot': '饮料', 'text': '喜欢咖啡', 'importance': 3, 'source_id': 999}], 'growth_ops': []}
        self.store.mutate(self.env | {'operation': dict(kind='reflection', op_id='c' * 32, json=json.dumps(reflection))})
        self.assertEqual(self.store.snapshot()['memory']['cards'], [])
        # Fresh admitted evidence, not assistant words or webpage text.
        source = self.add('现在更喜欢茶', 'd' * 32)['result']
        reflection['ops'][0].update(text='目前更喜欢茶', source_id=source)
        self.store.mutate(self.env | {'operation': dict(kind='reflection', op_id='e' * 32, json=json.dumps(reflection))})
        self.assertIn('目前更喜欢茶', self.store.query('饮料')['context'])

    def test_background_candidate_never_calls_search_or_enters_memory(self):
        provider = FakeProvider([json.dumps({'input': 'background', 'action': 'search', 'query': '电视剧情', 'remember': False})])
        service = brain.Brain(self.store, provider, 'x' * 48)
        service.model(self.env | dict(kind='dialogue', candidate='萧将军弄回来的猪肉', microphone=True, system='设备在床上'))
        self.assertEqual(provider.searches, [])
        self.assertEqual(self.store.snapshot()['memory']['history'], [])
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM archive').fetchone()[0], 0)

    def test_search_orchestration_uses_server_memory_and_actual_tool_result(self):
        self.add()
        provider = FakeProvider([json.dumps({'input': 'direct', 'action': 'search', 'query': '北京天气'}),
                                 json.dumps({'input': 'direct', 'action': 'speak', 'say': '这次资料不够明确。'})])
        service = brain.Brain(self.store, provider, 'x' * 48)
        reply = service.model(self.env | dict(kind='dialogue', candidate='查天气', microphone=True, system='设备当前北京时间'))
        self.assertEqual(provider.searches, ['北京天气'])
        self.assertIn('公开资料', provider.prompts[-1][1][-1]['content'])
        self.assertIn('小溪', provider.prompts[0][0])
        self.assertEqual(json.loads(reply['text'])['action'], 'speak')
        self.assertEqual(len(self.store.snapshot()['memory']['history']), 1)

    def test_cancellation_during_inference_prevents_late_search_and_actions(self):
        entered, release = threading.Event(), threading.Event()
        provider = FakeProvider()
        def blocked(*args, **kwargs):
            entered.set(); release.wait(3)
            return json.dumps({'input': 'direct', 'action': 'search', 'query': '不应执行'})
        provider.complete = blocked
        service = brain.Brain(self.store, provider, 'x' * 48)
        failures = []
        def run():
            try: service.model(self.env | dict(kind='dialogue', candidate='测试', microphone=True, system=''))
            except Exception as err: failures.append(err)
        thread = threading.Thread(target=run); thread.start(); self.assertTrue(entered.wait(2))
        self.store.admit(self.env | {'generation': 2})
        release.set(); thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(failures[0], brain.Conflict)
        self.assertEqual(provider.searches, [])

    def test_http_pairing_replay_voice_transport_and_device_isolation(self):
        other_spec = importlib.util.spec_from_file_location('computer_agent_brain_test', Path(__file__).with_name('agent.py'))
        agent = importlib.util.module_from_spec(other_spec); other_spec.loader.exec_module(agent)
        provider = FakeProvider()
        seen = []
        def upstream(path, body, content_type='application/json', language=False):
            seen.append((path, content_type, language))
            if path == '/v1/speech_to_text':
                return io.BytesIO(brain.encode({'text': '模拟转写', 'base_resp': {'status_code': 0}}))
            return io.BytesIO(b'data: {"data":{"status":1,"audio":"00000000"}}\n\ndata: {"data":{"status":2,"audio":""}}\n\n')
        provider.request = upstream
        service = brain.Brain(self.store, provider, 'x' * 48)
        jobs = agent.Store(Path(self.tmp.name) / 'jobs.sqlite3')
        server = ThreadingHTTPServer(('127.0.0.1', 0), agent.handler(jobs, 'y' * 48, lambda: True, service))
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        def rpc(path, value, token='x' * 48, content_type='application/json', **headers):
            raw = value if isinstance(value, bytes) else brain.encode(value)
            request = Request('http://127.0.0.1:' + str(server.server_port) + path, raw,
                              {'Authorization': 'Bearer ' + token, 'Content-Type': content_type, **headers})
            with urlopen(request, timeout=3) as response:
                return response.read()
        try:
            with self.assertRaises(HTTPError) as denied:
                rpc('/v1/brain/health', self.env, token='wrong')
            self.assertEqual(denied.exception.code, 401); denied.exception.close()
            health = json.loads(rpc('/v1/computer/health', {}, token='y' * 48))
            self.assertTrue(health['brain_ready'])
            self.assertTrue(json.loads(rpc('/v1/brain/health', self.env))['ready'])
            with self.assertRaises(HTTPError) as wrong_body:
                rpc('/v1/brain/health', self.env | {'device': 'ffeeddccbbaa'})
            self.assertEqual(wrong_body.exception.code, 409); wrong_body.exception.close()
            result = json.loads(rpc('/v1/brain/asr', b'------deskpet\r\nContent-Disposition: form-data; name="model"\r\n\r\nasr-1.0\r\n------deskpet\r\nRIFF simulated PCM only',
                                    content_type='multipart/form-data; boundary=----deskpet',
                                    **{'X-Pet-Session': json.dumps(self.env)}))
            self.assertEqual(result['text'], '模拟转写')
            self.assertTrue(seen[-1][2])
            speech = dict(model='speech-2.8-turbo', text='模拟音频，无实际播放', stream=True,
                          voice_setting={'voice_id': 'female-shaonv'},
                          audio_setting={'sample_rate': 16000, 'format': 'pcm', 'channel': 1})
            streamed = rpc('/v1/brain/tts', self.env | {'speech': speech})
            self.assertIn(b'"status":2', streamed)
            self.assertNotIn(b'HTTP/', streamed)
            rpc('/v1/brain/cancel', self.env | {'generation': 2})
            with self.assertRaises(HTTPError) as stale:
                rpc('/v1/brain/snapshot', self.env)
            self.assertEqual(stale.exception.code, 409); stale.exception.close()
            self.assertEqual(self.store.snapshot()['memory']['history'], [])
        finally:
            server.shutdown(); server.server_close(); thread.join(3); jobs.db.close()


if __name__ == '__main__':
    unittest.main()
