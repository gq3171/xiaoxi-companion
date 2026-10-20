import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import threading
import types
from http.server import ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from media import MediaStore,MediaUnavailable


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'real ffmpeg required')
class MediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.work=self.root/'work';self.work.mkdir();self.store=MediaStore(self.root/'media');self.job='a'*32
    def tearDown(self):self.tmp.cleanup()
    def generate(self,name,*args):
        path=self.work/name
        subprocess.run(['ffmpeg','-nostdin','-v','error',*args,'-threads','1',str(path)],check=True,capture_output=True,timeout=20)
        return path
    def test_audio_packets_reassemble_complete_pcm_with_no_flash_sized_blob(self):
        self.generate('tone.wav','-f','lavfi','-i','sine=frequency=330:sample_rate=16000','-t','0.7','-c:a','pcm_s16le')
        item=self.store.prepare(self.job,self.work,'tone.wav','音频夹具')
        self.assertEqual(item['kind'],'audio');self.assertEqual(item['fps'],4)
        packets=[self.store.chunk(self.job,item['id'],i) for i in range(item['frames'])]
        pcm=b''.join(base64.b64decode(p['audio']) for p in packets)
        self.assertEqual(len(pcm),22400);self.assertTrue(any(pcm))
        self.assertTrue(all(len(json.dumps(p).encode())<96*1024 for p in packets))
        self.assertEqual([p['eof'] for p in packets],[False,False,True])
        self.assertEqual(self.store.catalog()[0]['title'],'音频夹具')
    def test_video_has_distinct_jpegs_and_audio_clock_at_eight_fps(self):
        self.generate('clip.mp4','-f','lavfi','-i','testsrc=size=96x64:rate=8','-f','lavfi','-i','sine=sample_rate=16000','-t','0.5','-c:v','mpeg4','-c:a','aac')
        item=self.store.prepare(self.job,self.work,'clip.mp4');self.assertEqual(item['kind'],'video')
        packets=[self.store.chunk(self.job,item['id'],i) for i in range(item['frames'])]
        frames=[base64.b64decode(p['frame']) for p in packets]
        self.assertTrue(all(p.startswith(b'\xff\xd8') and p.endswith(b'\xff\xd9') for p in frames))
        self.assertGreater(len({hashlib.sha256(p).hexdigest() for p in frames}),1)
        self.assertTrue(all(len(base64.b64decode(p['audio']))==4000 and p['fps']==8 for p in packets))
        self.assertGreaterEqual(item['frames'],4)
        self.assertLessEqual(abs(item['frames']*125-item['duration_ms']),125)
    def test_still_image_prepares_one_frame_and_deduplicates(self):
        self.generate('picture.jpg','-f','lavfi','-i','color=c=red:s=80x120','-frames:v','1')
        item=self.store.prepare(self.job,self.work,'picture.jpg')
        self.assertEqual(item['kind'],'image');self.assertEqual(item['frames'],1)
        self.assertEqual((item['source_width'],item['source_height']),(80,120))
        from media import available_media
        inventory=available_media(types.SimpleNamespace(media=self.store))
        self.assertIn('picture.jpg',inventory);self.assertIn('80',inventory);self.assertNotIn(str(self.root),inventory)
        self.assertEqual(self.store.prepare(self.job,self.work,'picture.jpg')['id'],item['id'])
        self.assertEqual(len(self.store.catalog(self.job)),1)
        p=self.store.chunk(self.job,item['id'],0);self.assertTrue(p['eof']);self.assertEqual(p['audio'],'')
    def test_bad_files_cancel_and_outside_paths_never_publish_a_result(self):
        bad=self.work/'bad.bin';bad.write_text('not media')
        with self.assertRaises(MediaUnavailable):self.store.prepare(self.job,self.work,'bad.bin')
        self.assertTrue(bad.exists());self.assertEqual(self.store.catalog(self.job),[])
        outside=self.root/'outside';outside.write_text('unrelated')
        (self.work/'link').symlink_to(outside)
        for path in ('../outside',str(outside),'link'):
            with self.assertRaises((MediaUnavailable,OSError)):self.store.prepare(self.job,self.work,path)
        with self.assertRaises(MediaUnavailable):self.store.prepare(self.job,self.work,'bad.bin',cancelled=lambda:True)
        self.assertEqual(self.store.catalog(self.job),[])
        self.assertFalse(list(self.store.directory(self.job).glob('.prepare-*')))
    def test_unknown_jobs_ids_and_frame_offsets_are_rejected(self):
        for job,asset,index in [('../outside','b'*32,0),('a'*32,'../outside',0),('a'*32,'b'*32,-1),('a'*32,'b'*32,True),('a'*32,'b'*32,0)]:
            with self.assertRaises(MediaUnavailable):self.store.chunk(job,asset,index)

    def test_real_http_media_routes_require_pairing_and_return_actual_packets(self):
        import test_agent as fixtures
        self.generate('tone.wav','-f','lavfi','-i','sine=sample_rate=16000','-t','0.3','-c:a','pcm_s16le')
        item=self.store.prepare(self.job,self.work,'tone.wav')
        holder=types.SimpleNamespace(media=self.store)
        server=ThreadingHTTPServer(('127.0.0.1',0),fixtures.agent.handler(holder,'x'*48,lambda:True))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def call(operation,payload,token='x'*48):
            request=Request(f'http://127.0.0.1:{server.server_port}/v1/computer/'+operation,json.dumps(payload).encode(),{'Authorization':'Bearer '+token})
            with urlopen(request,timeout=3) as response:return json.load(response)
        try:
            with self.assertRaises(HTTPError) as error:call('media_list',{},'wrong')
            self.assertEqual(error.exception.code,401)
            self.assertTrue(base64.b64decode(call('media_probe',{})['frame']).startswith(b'\xff\xd8'))
            self.assertEqual(call('media_list',{})['media'][0]['id'],item['id'])
            result=call('media_chunk',dict(job_id=self.job,id=item['id'],index=0))
            self.assertEqual(len(base64.b64decode(result['audio'])),8000)
            with self.assertRaises(HTTPError) as error:call('media_chunk',dict(job_id=self.job,id=item['id'],index=-1))
            self.assertEqual(error.exception.code,409)
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
