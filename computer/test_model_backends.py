"""Protocol, key routing and real local HTTP checks; never call a paid provider."""
import io,json,os,shutil,threading,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
import backend_config as cfg
import brain
from model_protocols import payload,read_text,InferenceCancelled
from runtime_config import DEFAULTS
import service_adapters as audio


def sse(*values):
    return b''.join(b'data: '+(x.encode() if isinstance(x,str) else json.dumps(x).encode())+b'\n\n' for x in values)


def chat(text='{"say":"hello"}',reason='stop',done=True):
    values=[dict(choices=[dict(index=0,delta=dict(reasoning_content='PRIVATE_THOUGHT'))]),dict(choices=[dict(index=0,delta=dict(content=text))]),dict(choices=[dict(index=0,delta={},finish_reason=reason)])]
    if done:values.append('[DONE]')
    return sse(*values)


class BackendTests(unittest.TestCase):
    def configured(self,provider='custom',**kwargs):
        values=dict(LLM_PROVIDER=provider,LLM_BASE_URL='https://models.example/v1',LLM_MODEL='fixture-model',LLM_API_KEY='fixture-key')
        values.update(kwargs);return cfg.text_config(values,DEFAULTS['llm'])
    def test_every_preset_resolves_without_private_data_or_foreign_credentials(self):
        for name,preset in cfg.PRESETS.items():
            with self.subTest(provider=name):
                values=dict(LLM_PROVIDER=name,LLM_MODEL='actual-model',LLM_API_KEY='fixture-key',MINIMAX_API_KEY='foreign-key')
                if name=='custom':values['LLM_BASE_URL']='https://gateway.example/compatible/v1'
                config=cfg.text_config(values,DEFAULTS['llm'])
                self.assertEqual(config.key,'fixture-key');self.assertEqual(config.api_type,preset['api_type'])
                self.assertTrue(config.ready)
        with self.assertRaises(ValueError):cfg.text_config(dict(LLM_PROVIDER='deepseek'),DEFAULTS['llm'])
    def test_other_provider_does_not_inherit_minimax_key_host_or_speech(self):
        config=cfg.text_config(dict(LLM_PROVIDER='deepseek',LLM_MODEL='chosen',MINIMAX_API_KEY='private-minimax',MINIMAX_API_HOST='https://api.minimax.io'),DEFAULTS['llm'])
        self.assertEqual(config.key,'');self.assertEqual(config.base_url,cfg.PRESETS['deepseek']['base_url']);self.assertFalse(config.ready)
        for kind in ('ASR','TTS','SEARCH'):self.assertEqual(cfg.auxiliary(kind,config,{})['provider'],'none')
    def test_explicit_local_models_can_be_ready_without_a_key(self):
        config=cfg.text_config(dict(LLM_PROVIDER='ollama',LLM_MODEL='local-model'),DEFAULTS['llm'])
        self.assertTrue(config.ready);self.assertEqual(config.key,'')
    def test_unsafe_base_urls_and_header_injection_are_rejected_without_secret_echo(self):
        for url in ('http://cloud.example/v1','https://u:private-key@cloud.example/v1','https://cloud.example/v1?api_key=private-key','file:///tmp/test','http://169.254.169.254/v1','https://cloud.example/../v1','https://cloud.example/\n'):
            with self.subTest(url=url),self.assertRaises(ValueError) as e:cfg.base_url(url)
            self.assertNotIn('private-key',str(e.exception))
        with self.assertRaises(ValueError):self.configured(LLM_API_KEY='bad\nheader')
    def test_chat_payload_rewrites_system_and_inline_images_and_omits_vendor_effort(self):
        config=self.configured()
        path,body=payload(config,'system',[dict(role='user',content=[dict(type='text',text='look'),dict(type='image',source=dict(type='base64',media_type='image/png',data='AA=='))])],DEFAULTS['llm'])
        self.assertEqual(path,'/chat/completions');self.assertEqual(body['messages'][0]['content'],'system')
        self.assertEqual(body['messages'][1]['content'][1]['image_url']['url'],'data:image/png;base64,AA==')
        self.assertNotIn('output_config',body);self.assertNotIn('reasoning_effort',body);self.assertNotIn('temperature',body)
    def test_responses_payload_and_terminal_event(self):
        config=self.configured(LLM_API_TYPE='openai-responses')
        path,body=payload(config,'system',[dict(role='user',content='hello')],DEFAULTS['llm'],True)
        self.assertEqual(path,'/responses');self.assertEqual(body['max_output_tokens'],8192);self.assertFalse(body['store'])
        raw=sse(dict(type='response.reasoning_summary_text.delta',delta='PRIVATE_THOUGHT'),dict(type='response.output_text.delta',delta='ok'),dict(type='response.completed',response=dict(status='completed')))
        self.assertEqual(read_text(io.BytesIO(raw),config.api_type),'ok')
    def test_anthropic_native_uses_messages_without_minimax_output_config(self):
        config=self.configured('anthropic');path,body=payload(config,'system',[],DEFAULTS['llm'])
        self.assertEqual(path,'/messages');self.assertEqual(body['system'],'system');self.assertNotIn('output_config',body)
        raw=sse(dict(type='content_block_delta',delta=dict(type='text_delta',text='ok')),dict(type='message_stop'))
        self.assertEqual(read_text(io.BytesIO(raw),config.api_type),'ok')
    def test_chat_reasoning_is_not_exposed_and_complete_json_reaches_brain(self):
        self.assertEqual(brain.parse_answer(read_text(io.BytesIO(chat()),'openai-chat')),dict(say='hello'))
    def test_truncation_tool_calls_filtering_and_missing_terminal_are_not_success(self):
        for raw in (chat(reason='length'),chat(reason='tool_calls'),chat(reason='content_filter'),chat(done=False),sse(dict(type='response.output_text.delta',delta='half'),dict(type='response.incomplete'))):
            with self.assertRaises(ValueError):read_text(io.BytesIO(raw),'openai-chat' if b'choices' in raw else 'openai-responses')
    def test_sse_multiline_and_cancellation_and_budgets(self):
        raw=b': ping\r\nevent: delta\r\ndata: {"choices":\r\ndata: [{"delta":{"content":"ok"}}]}\r\n\r\n'+sse(dict(choices=[dict(delta={},finish_reason='stop')]),'[DONE]')
        self.assertEqual(read_text(io.BytesIO(raw),'openai-chat'),'ok')
        with self.assertRaises(InferenceCancelled):read_text(io.BytesIO(chat()),'openai-chat',lambda:False)
        with self.assertRaises(ValueError):read_text(io.BytesIO(chat('x'*65536)),'openai-chat')
    def test_model_and_protocol_selection_reaches_tasks_as_well_as_dialogue(self):
        with patch.dict(os.environ,dict(LLM_PROVIDER='custom',LLM_MODEL='custom-model',LLM_BASE_URL='http://127.0.0.1:12345/v1',LLM_API_KEY='')):
            import agent
            from tempfile import TemporaryDirectory
            from pathlib import Path
            with TemporaryDirectory() as root:
                store=agent.Store(Path(root)/'jobs.sqlite3');worker=agent.Worker(store)
                def request(path,body):
                    value=json.loads(body);self.assertEqual(value['model'],'custom-model');self.assertEqual(path,'/chat/completions')
                    return io.BytesIO(chat('{"action":"finish","state":"failed","message":"fixture"}'))
                worker.provider.request=request
                try:self.assertEqual(worker.complete([dict(role='user',content='task')])['state'],'failed')
                finally:store.db.close()


class LocalTransportTests(unittest.TestCase):
    def setUp(self):
        self.seen=[];test=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_POST(self):
                body=self.rfile.read(int(self.headers.get('Content-Length','0')));test.seen.append((self.path,{k.lower():v for k,v in self.headers.items()},body))
                if self.path.endswith('/redirect'):
                    self.send_response(307);self.send_header('Location',test.origin+'/sink');self.send_header('Content-Length','0');self.end_headers();return
                response=chat() if self.path.endswith('/chat/completions') else sse(dict(type='response.output_text.delta',delta='{"say":"hello"}'),dict(type='response.completed',response=dict(status='completed'))) if self.path.endswith('/responses') else sse(dict(type='content_block_delta',delta=dict(type='text_delta',text='{"say":"hello"}')),dict(type='message_stop'))
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(response)));self.end_headers();self.wfile.write(response)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.origin='http://127.0.0.1:'+str(self.server.server_port)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join(3)
    def test_real_http_three_protocols_authentication_base_paths_and_completion(self):
        for protocol,suffix in [('openai-chat','/chat/completions'),('openai-responses','/responses'),('anthropic','/messages')]:
            provider=brain.Provider(values=dict(LLM_PROVIDER='custom',LLM_API_TYPE=protocol,LLM_BASE_URL=self.origin+'/tenant/v1',LLM_MODEL='fixture',LLM_API_KEY='fixture-text-key'))
            self.assertEqual(brain.parse_answer(provider.complete('system',[dict(role='user',content='hello')])),dict(say='hello'))
            path,headers,body=self.seen[-1];self.assertEqual(path,'/tenant/v1'+suffix)
            if protocol=='anthropic':self.assertEqual(headers.get('x-api-key'),'fixture-text-key');self.assertNotIn('authorization',headers)
            else:self.assertEqual(headers.get('authorization'),'Bearer fixture-text-key');self.assertNotIn('x-api-key',headers)
    def test_redirect_never_resends_credentials_to_another_endpoint(self):
        with self.assertRaises(HTTPError) as error:audio.remote(self.origin,'/redirect','fixture-key',b'{}')
        error.exception.close()
        self.assertEqual(len(self.seen),1)


class AuxiliaryTests(unittest.TestCase):
    def text(self):return cfg.text_config(dict(LLM_PROVIDER='deepseek',LLM_MODEL='fixture',LLM_API_KEY='text-only-key'),DEFAULTS['llm'])
    def test_foreign_chat_key_is_never_implicitly_used_by_speech_or_search(self):
        for kind in ('ASR','TTS','SEARCH'):
            selected=cfg.auxiliary(kind,self.text(),{kind+'_PROVIDER':'minimax'})
            self.assertEqual(selected['key'],'')
    def test_asr_has_its_own_key_origin_and_model_and_preserves_audio_bytes(self):
        calls=[]
        def opener(base,path,key,body,*args,**kwargs):calls.append((base,path,key,body));return io.BytesIO(b'{"text":"hello"}')
        env=dict(ASR_PROVIDER='openai-compatible',ASR_BASE_URL='https://asr.example/v1',ASR_API_KEY='asr-only-key',ASR_MODEL='configured-asr')
        body=b'------deskpet\r\nContent-Disposition: form-data; name="model"\r\n\r\nasr-1.0\r\n------deskpet\r\nRIFF audio asr-1.0 sentinel'
        with patch.dict(os.environ,env):
            with audio.speech_request(self.text(),'ASR',body,'multipart/form-data; boundary=----deskpet',opener) as response:self.assertEqual(json.load(response)['text'],'hello')
        base,path,key,sent=calls[0];self.assertEqual((base,path,key),('https://asr.example/v1','/audio/transcriptions','asr-only-key'));self.assertIn(b'configured-asr',sent);self.assertTrue(sent.endswith(b'RIFF audio asr-1.0 sentinel'))
    def test_tts_is_credential_separated_and_converts_to_existing_board_wire_format(self):
        calls=[]
        def opener(base,path,key,body,**kwargs):calls.append((base,path,key,json.loads(body)));return io.BytesIO(b'\0\1'*100)
        env=dict(TTS_PROVIDER='openai-compatible',TTS_BASE_URL='https://tts.example/v1',TTS_API_KEY='tts-only-key',TTS_MODEL='configured-tts',TTS_VOICE='chosen-voice')
        request=dict(text='hello',voice_setting=dict(voice_id='female-shaonv',speed=1))
        with patch.dict(os.environ,env),patch.object(audio,'resample_pcm',return_value=b'\0\1'*100) as resample:
            for stream in (False,True):
                request['stream']=stream
                with audio.speech_request(self.text(),'TTS',json.dumps(request).encode(),'application/json',opener) as result:raw=result.read()
                if stream:self.assertIn(b'"status": 2',raw)
                else:self.assertEqual(bytes.fromhex(json.loads(raw)['data']['audio']),b'\0\1'*100)
            resample.assert_called_with(b'\0\1'*100,24000)
        for base,path,key,body in calls:
            self.assertEqual((base,path,key),('https://tts.example/v1','/audio/speech','tts-only-key'))
            self.assertEqual((body['model'],body['voice'],body['response_format']),('configured-tts','chosen-voice','pcm'))
    @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg unavailable')
    def test_real_pcm_resampling_preserves_duration_and_board_sample_rate(self):
        pcm=audio.resample_pcm(b'\0\0'*2400,24000)
        self.assertEqual(len(pcm),3200)
    def test_provider_snapshot_routes_auxiliary_keys_and_reports_capabilities_without_secrets(self):
        values=dict(LLM_PROVIDER='deepseek',LLM_MODEL='fixture',LLM_API_KEY='chat-only-key',ASR_PROVIDER='openai-compatible',ASR_BASE_URL='https://asr.example/v1',ASR_API_KEY='asr-only-key',ASR_MODEL='actual-asr',TTS_PROVIDER='none',SEARCH_PROVIDER='none')
        provider=brain.Provider(values=values);seen=[]
        def remote(base,path,key,body,*args,**kwargs):seen.append((base,path,key,body));return io.BytesIO(b'{"text":"ok"}')
        form=b'------deskpet\r\nContent-Disposition: form-data; name="model"\r\n\r\nasr-1.0\r\n------deskpet\r\nRIFF test'
        with patch.dict(os.environ,dict(ASR_API_KEY='unrelated-global-key')),patch.object(audio,'remote',side_effect=remote):
            with provider.request('/v1/speech_to_text',form,'multipart/form-data; boundary=----deskpet') as response:self.assertEqual(json.load(response)['text'],'ok')
        self.assertEqual(seen[0][:3],('https://asr.example/v1','/audio/transcriptions','asr-only-key'));self.assertIn(b'actual-asr',seen[0][3])
        caps=provider.capabilities();self.assertTrue(caps['asr']['configured']);self.assertFalse(caps['tts']['configured']);self.assertFalse(caps['network_verified'])
        self.assertNotIn('only-key',json.dumps(caps))
    def test_legacy_international_minimax_speech_keeps_the_same_origin(self):
        text=cfg.text_config(dict(MINIMAX_API_HOST='https://api.minimax.io',MINIMAX_MODEL='fixture',MINIMAX_API_KEY='fixture-key'),DEFAULTS['llm'])
        for kind in ('ASR','TTS','SEARCH'):
            value=cfg.auxiliary(kind,text,{})
            self.assertEqual((value['base_url'],value['key']),('https://api.minimax.io','fixture-key'))
    def test_disabled_speech_fails_before_any_network(self):
        with patch.dict(os.environ,dict(TTS_PROVIDER='none')),patch.object(audio,'remote',side_effect=AssertionError('no network')):
            with self.assertRaises(ValueError):audio.speech_request(self.text(),'TTS',b'{}','application/json')

if __name__=='__main__':unittest.main()
