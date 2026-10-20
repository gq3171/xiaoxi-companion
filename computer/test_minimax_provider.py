"""Messages streaming contract across the formal-model migration; no network."""
import io,json,unittest
import brain

class MiniMaxProviderTests(unittest.TestCase):
 def provider(self,stop='end_turn',done=True):
  p=brain.Provider('test-key','https://api.minimaxi.com');seen=[]
  events=[{'type':'content_block_delta','delta':{'type':'thinking_delta','thinking':'PRIVATE_THINKING'}},
          {'type':'content_block_delta','delta':{'type':'text_delta','text':'{"say":"我在呀"}'}},
          {'type':'message_delta','delta':{'stop_reason':stop}}]
  if done:events.append({'type':'message_stop'})
  raw=b''.join(b'data: '+json.dumps(e,ensure_ascii=False).encode()+b'\n\n' for e in events)
  def request(path,body):seen.append((path,json.loads(body)));return io.BytesIO(raw)
  p.request=request;return p,seen
 def test_formal_model_preserves_effort_routing_and_only_returns_final_text(self):
  p,seen=self.provider()
  for reflection,effort,limit in [(False,'low',4096),(True,'high',8192)]:
   raw=p.complete('system',[{'role':'user','content':'test'}],reflection=reflection)
   self.assertEqual(brain.parse_answer(raw),{'say':'我在呀'});self.assertNotIn('PRIVATE_THINKING',raw)
   path,body=seen[-1];self.assertEqual(path,'/anthropic/v1/messages');self.assertEqual(body['model'],'MiniMax-M3.1-Flash');self.assertEqual(body['output_config'],{'effort':effort});self.assertEqual(body['max_tokens'],limit);self.assertTrue(body['stream']);self.assertNotIn('thinking',body)
 def test_token_truncation_is_not_treated_as_complete_answer(self):
  p,_=self.provider(stop='max_tokens')
  with self.assertRaisesRegex(ValueError,'incomplete'):p.complete('s',[])
 def test_missing_stream_termination_is_not_treated_as_complete_answer(self):
  p,_=self.provider(done=False)
  with self.assertRaisesRegex(ValueError,'incomplete'):p.complete('s',[])

class ConfiguredModelTests(unittest.TestCase):
 def test_configured_model_is_used_in_dialogue_and_reflection_requests(self):
  from unittest.mock import patch
  with patch.dict('os.environ',{'MINIMAX_MODEL':'configured-model-fixture'}):
   p=brain.Provider('test-key');seen=[]
  def request(path,body):
   seen.append(json.loads(body));return io.BytesIO(b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"ok"}}\n\ndata: {"type":"message_stop"}\n\n')
  p.request=request
  p.complete('system',[]);p.complete('system',[],reflection=True)
  self.assertEqual([x['model'] for x in seen],['configured-model-fixture']*2)
 def test_explicit_model_beats_environment_and_invalid_names_fail_before_network(self):
  from unittest.mock import patch
  with patch.dict('os.environ',{'MINIMAX_MODEL':'environment-fixture'}):
   self.assertEqual(brain.Provider('test-key',model='explicit-fixture').model,'explicit-fixture')
   with self.assertRaises(ValueError):brain.Provider('test-key',model='bad\nmodel')
