"""Credential-separated HTTP and speech adapters; no cloud retries/fallbacks.

The internal 16kHz mono protocol stays stable for existing ESP32 firmware. The
OpenAI-compatible TTS bridge buffers and resamples PCM; it is not realtime voice.
"""
import io,json,os,subprocess
from urllib.request import Request,build_opener,HTTPRedirectHandler
from backend_config import auxiliary,model_valid

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def remote(base,path,key,body,content_type='application/json',protocol='',language=False,timeout=30):
    if not path.startswith('/') or path.startswith('//') or any(x in path for x in ('..','?','#')):raise ValueError('invalid fixed API operation')
    headers={'Content-Type':content_type}
    if key:
        if protocol=='anthropic':headers['x-api-key']=key
        else:headers['Authorization']='Bearer '+key
    if protocol in ('minimax-messages','anthropic'):
        headers['anthropic-version']='2023-06-01'
        if protocol=='minimax-messages':headers['x-api-key']=key
    if language:headers['language']='zh'
    return build_opener(NoRedirect()).open(Request(base+path,body,headers),timeout=timeout)


def speech_model(kind,config,values=None):
    from runtime_config import settings
    defaults=settings()['speech'];compatible=config['provider']=='openai-compatible'
    default=defaults[('openai_' if compatible else '')+kind.lower()+'_model']
    name=(os.environ if values is None else values).get(kind+'_MODEL',default)
    if not model_valid(name):raise ValueError('invalid configured speech model')
    return name


def resample_pcm(pcm,rate):
    if not pcm or len(pcm)%2 or len(pcm)>4*1024*1024:raise ValueError('invalid PCM audio budget')
    if rate==16000:return pcm
    result=subprocess.run(['ffmpeg','-nostdin','-v','error','-f','s16le','-ar',str(rate),'-ac','1','-i','pipe:0','-threads','1','-ar','16000','-f','s16le','pipe:1'],input=pcm,capture_output=True,timeout=20,check=True)
    if not result.stdout or len(result.stdout)>2*1024*1024:raise ValueError('converted audio budget')
    return result.stdout


def speech_request(text,kind,body,content_type,opener=None,values=None):
    from runtime_config import settings,rewrite_asr_model,voice_valid
    opener=opener or remote
    config=auxiliary(kind,text,values)
    if config['provider']=='none' or (not config['key'] and not config['base_url'].startswith('http://')):
        raise ValueError('speech service is not configured')
    timeout=settings()['llm']['timeout_seconds']
    if kind=='ASR':
        body=rewrite_asr_model(body,speech_model('ASR',config,values))
        path='/v1/speech_to_text' if config['provider']=='minimax' else '/audio/transcriptions'
        return opener(config['base_url'],path,config['key'],body,content_type,language=config['provider']=='minimax',timeout=timeout)
    speech=json.loads(body)
    if config['provider']=='minimax':
        speech['model']=speech_model('TTS',config,values)
        return opener(config['base_url'],'/v1/t2a_v2',config['key'],json.dumps(speech,ensure_ascii=False).encode(),timeout=timeout)
    voice=(os.environ if values is None else values).get('TTS_VOICE',settings()['speech']['openai_voice'])
    if not voice_valid(voice):raise ValueError('invalid configured TTS voice')
    payload=dict(model=speech_model('TTS',config,values),input=speech['text'],voice=voice,response_format='pcm',speed=speech.get('voice_setting',{}).get('speed',1))
    with opener(config['base_url'],'/audio/speech',config['key'],json.dumps(payload,ensure_ascii=False).encode(),timeout=timeout) as upstream:
        raw=upstream.read(4*1024*1024+1)
        if getattr(upstream,'headers',{}).get('Content-Type','').startswith('application/json'):raise ValueError('invalid speech response format')
    pcm=resample_pcm(raw,settings()['speech']['openai_pcm_rate'])
    if speech.get('stream'):
        def frame(data):return b'data: '+json.dumps(dict(data=data,base_resp=dict(status_code=0))).encode()+b'\n\n'
        return io.BytesIO(b''.join(frame(dict(audio=pcm[n:n+4096].hex(),status=1)) for n in range(0,len(pcm),4096))+frame(dict(audio='',status=2)))
    return io.BytesIO(json.dumps(dict(data=dict(audio=pcm.hex()),base_resp=dict(status_code=0))).encode())
