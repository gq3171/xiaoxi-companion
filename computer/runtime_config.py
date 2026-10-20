"""Validated non-secret runtime options; credentials never enter this document."""
import copy
import json
import os
from pathlib import Path
import re
from deployment_paths import read_layout

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
    if result['llm']['api_host'] not in ('https://api.minimaxi.com','https://api.minimax.io','https://api.minimax.cn'):
        raise ValueError('unsupported provider origin')
    for field in ('tts_model','asr_model'):
        if not isinstance(result['speech'][field],str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',result['speech'][field]):raise ValueError('invalid speech configuration')
    if not voice_valid(result['speech']['default_voice']):raise ValueError('invalid default voice ID')
    bounds={'llm.timeout_seconds':(5,120),'llm.dialogue_max_tokens':(256,65536),'llm.reflection_max_tokens':(256,65536),
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


def rewrite_asr_model(body):
    prefix=b'------deskpet\r\nContent-Disposition: form-data; name="model"\r\n\r\n'
    if not body.startswith(prefix):raise ValueError('missing ASR model form field')
    previous,separator,audio=body[len(prefix):].partition(b'\r\n------deskpet\r\n')
    if not separator or len(previous)>160:raise ValueError('invalid ASR model form field')
    return prefix+settings()['speech']['asr_model'].encode()+separator+audio
