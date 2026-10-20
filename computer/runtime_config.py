"""Validated non-secret runtime options; credentials never enter this document."""
import copy
import json
import os
from pathlib import Path
import re
from deployment_paths import read_layout
from backend_config import base_url, PRESETS, API_TYPES

DEFAULTS=json.loads(Path(__file__).with_name('runtime.defaults.json').read_text())


def voice_valid(value):
    return isinstance(value,str) and bool(re.fullmatch(r'[\w .()（）-]{1,100}',value))


def validate(options):
    result=copy.deepcopy(DEFAULTS)
    def merge(target,source):
        if not isinstance(source,dict):raise ValueError('configuration section must be an object')
        for key,value in source.items():
            if key not in target:raise ValueError('unknown runtime configuration field')
            if isinstance(target[key],dict):merge(target[key],value)
            else:target[key]=value
    merge(result,options)
    for key in ('model',):
        if not isinstance(result['llm'][key],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}',result['llm'][key]):raise ValueError('invalid model name')
    base_url(result['llm']['api_host'])
    if result['llm']['provider'] not in PRESETS or result['llm']['api_type'] not in ('auto',)+API_TYPES:raise ValueError('invalid model provider/protocol')
    if result['llm']['send_temperature']!='auto' and type(result['llm']['send_temperature']) is not bool:raise ValueError('invalid temperature capability')
    if result['llm']['effort_mode'] not in ('auto','none','minimax','openai'):raise ValueError('invalid effort mode')
    if result['llm']['token_parameter'] not in ('auto','max_tokens','max_completion_tokens'):raise ValueError('invalid token parameter')
    for field in ('tts_model','asr_model','openai_tts_model','openai_asr_model'):
        if not isinstance(result['speech'][field],str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',result['speech'][field]):raise ValueError('invalid speech configuration')
    if not voice_valid(result['speech']['openai_voice']):raise ValueError('invalid compatible voice ID')
    if not voice_valid(result['speech']['default_voice']):raise ValueError('invalid default voice ID')
    bounds={'speech.openai_pcm_rate':(8000,48000),'llm.timeout_seconds':(5,120),'llm.dialogue_max_tokens':(256,65536),'llm.reflection_max_tokens':(256,65536),
            'desktop.cdp_port':(1024,65535),'desktop.probe_cdp_port':(1024,65535),'desktop.max_fps':(1,30),
            'desktop.headless_idle_seconds':(30,86400),'web.preview_port':(1024,65535),
            'http.connection_limit':(4,128),'http.handshake_limit':(1,32),'http.handshake_timeout':(1,30)}
    for key,(lo,hi) in bounds.items():
        section,field=key.split('.');value=result[section][field]
        if type(value) is not int or not lo<=value<=hi:raise ValueError('runtime setting outside supported range')
    for value in result['http']['lane_limits'].values():
        if type(value) is not int or not 1<=value<=128:raise ValueError('invalid HTTP lane budget')
    if result['desktop']['cdp_port']==result['desktop']['probe_cdp_port']:raise ValueError('browser and diagnostic ports must differ')
    if result['desktop']['renderer'] not in ('gles2','pixman'):raise ValueError('unsupported compositor renderer')
    if not re.fullmatch('/dev/dri/renderD[0-9]+',str(result['desktop']['drm_device'])):raise ValueError('invalid DRM render device')
    for key in ('dialogue_effort','reflection_effort'):
        if result['llm'][key] not in ('low','medium','high'):raise ValueError('unsupported model effort')
    if type(result['llm']['temperature']) not in (int,float) or not 0<result['llm']['temperature']<=1:raise ValueError('invalid model temperature')
    return result


def settings():
    return validate(read_layout().get('options',{}))


def cdp_port():
    value=os.environ.get('DESKPET_DESKTOP_CDP_PORT')
    if value is None:return settings()['desktop']['cdp_port']
    number=int(value)
    if not 1024<=number<=65535:raise ValueError('invalid private debugger port')
    return number


def allowed_cdp_ports():
    return {cdp_port(),settings()['desktop']['probe_cdp_port']}


def public_origin():
    layout=read_layout()
    return os.environ.get('DESKPET_PUBLIC_ORIGIN',layout.get('public_origin','https://xiaoxi.example:'+str(layout['port']))).rstrip('/')


def rewrite_asr_model(body,model=None):
    prefix=b'------deskpet\r\nContent-Disposition: form-data; name="model"\r\n\r\n'
    if not body.startswith(prefix):raise ValueError('missing ASR model form field')
    previous,separator,audio=body[len(prefix):].partition(b'\r\n------deskpet\r\n')
    if not separator or len(previous)>160:raise ValueError('invalid ASR model form field')
    return prefix+(model or settings()['speech']['asr_model']).encode()+separator+audio
