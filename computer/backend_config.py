"""Provider selection is operator configuration, never a model/tool argument.

Generic credentials never fall back to another vendor's key. Legacy MiniMax env
names remain readable, but only for the MiniMax profile.
"""
from dataclasses import dataclass, field
import ipaddress
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

PRESETS=json.loads(Path(__file__).with_name('providers.defaults.json').read_text())
API_TYPES=('minimax-messages','anthropic','openai-chat','openai-responses')
MINIMAX_ORIGINS=('https://api.minimaxi.com','https://api.minimax.io','https://api.minimax.cn')


def base_url(value):
    if not isinstance(value,str) or not value or any(c.isspace() or ord(c)<32 for c in value):
        raise ValueError('invalid API base URL')
    try:
        url=urlsplit(value);port=url.port
        if not url.hostname or url.username or url.password or url.query or url.fragment or (port is not None and not 1<=port<=65535):
            raise ValueError()
        local=url.hostname=='localhost'
        try:
            addr=ipaddress.ip_address(url.hostname)
            local=addr.is_loopback or any(addr in ipaddress.ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16') if addr.version==4) or (addr.version==6 and addr in ipaddress.ip_network('fc00::/7'))
        except ValueError:pass
        if url.scheme!='https' and not (url.scheme=='http' and local):raise ValueError()
        if '\\' in value or any(part in ('.','..') for part in url.path.split('/')):raise ValueError()
        value.encode('ascii')
    except (ValueError,UnicodeError):
        raise ValueError('Use an HTTPS API base URL; HTTP is limited to explicit local/private hosts') from None
    return value.rstrip('/')


def key_valid(value):
    return isinstance(value,str) and (not value or bool(re.fullmatch(r'[A-Za-z0-9_./:@+?%=-]{1,4096}',value)))


def model_valid(value):
    return isinstance(value,str) and bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}',value))


@dataclass(repr=False)
class TextConfig:
    provider:str
    api_type:str
    base_url:str
    model:str
    key:str=field(repr=False)
    temperature:bool=True
    effort:str='none'
    token_parameter:str='max_tokens'

    @property
    def ready(self):return bool(self.model and (self.key or self.base_url.startswith('http://')))


def text_config(values=None,options=None,*,key=None,host=None,model=None):
    if options is None:
        from runtime_config import settings
        options=settings()['llm']
    env=os.environ if values is None else values
    provider=env.get('LLM_PROVIDER',options.get('provider','minimax'))
    if provider not in PRESETS:raise ValueError('Unknown LLM provider; use custom for a compatible endpoint')
    preset=PRESETS[provider]
    protocol=env.get('LLM_API_TYPE') or options.get('api_type','auto')
    if protocol=='auto':protocol=preset['api_type']
    if protocol not in API_TYPES:raise ValueError('unsupported model API type')
    legacy=provider=='minimax'
    url=base_url(host or env.get('LLM_BASE_URL') or (env.get('MINIMAX_API_HOST') or options['api_host'] if legacy else preset['base_url']))
    name=model or env.get('LLM_MODEL') or (env.get('MINIMAX_MODEL') or options['model'] if legacy else '')
    if not model_valid(name):raise ValueError('Provide the actual backend model name')
    secret=key if key is not None else env.get('LLM_API_KEY',env.get('MINIMAX_API_KEY','') if legacy else '')
    if not key_valid(secret):raise ValueError('invalid API key syntax')
    if protocol=='minimax-messages' and url not in MINIMAX_ORIGINS:
        raise ValueError('MiniMax native protocol requires an official MiniMax origin; use a compatible protocol for gateways')
    temperature=options.get('send_temperature','auto')
    if temperature=='auto':temperature=preset['temperature']
    effort=options.get('effort_mode','auto')
    if effort=='auto':effort=preset['effort']
    token=options.get('token_parameter','auto')
    if token=='auto':token=preset['token_parameter']
    return TextConfig(provider,protocol,url,name,secret,temperature,effort,token)


def auxiliary(kind,text,values=None):
    """ASR/TTS/search have separate origins, keys and explicit enablement."""
    env=os.environ if values is None else values
    default='minimax' if text.provider=='minimax' else 'none'
    provider=env.get(kind+'_PROVIDER',default)
    allowed=('minimax','none') if kind=='SEARCH' else ('minimax','openai-compatible','none')
    if provider not in allowed:raise ValueError('unsupported auxiliary service provider')
    if provider=='none':return dict(provider=provider,base_url='',key='')
    default_url=(text.base_url if text.provider=='minimax' and text.base_url in MINIMAX_ORIGINS else 'https://api.minimaxi.com') if provider=='minimax' else 'https://api.openai.com/v1'
    url=base_url(env.get(kind+'_BASE_URL',default_url))
    if provider=='minimax' and url not in MINIMAX_ORIGINS:raise ValueError('MiniMax service requires an official origin')
    # Reuse only the exact same configured MiniMax service, never a foreign key.
    fallback=text.key if text.provider=='minimax' and text.base_url==url and provider=='minimax' else ''
    secret=env.get(kind+'_API_KEY',fallback)
    if not key_valid(secret):raise ValueError('invalid auxiliary credential syntax')
    return dict(provider=provider,base_url=url,key=secret)
