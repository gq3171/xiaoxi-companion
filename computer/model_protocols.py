"""Text protocol adapters with bounded SSE parsing and explicit completion fences."""
import json

class InferenceCancelled(ValueError):pass


def content_parts(content,protocol):
    if isinstance(content,str):return content
    if not isinstance(content,list):raise ValueError('invalid model message content')
    result=[]
    for part in content:
        if not isinstance(part,dict):raise ValueError('invalid model content block')
        if part.get('type')=='text':
            result.append(dict(type='input_text' if protocol=='openai-responses' else 'text',text=part['text']))
        elif part.get('type')=='image':
            source=part.get('source',{})
            if source.get('type')!='base64' or source.get('media_type') not in ('image/png','image/jpeg','image/webp') or not isinstance(source.get('data'),str):raise ValueError('unsupported image source')
            url='data:'+source['media_type']+';base64,'+source['data']
            result.append(dict(type='input_image',image_url=url) if protocol=='openai-responses' else dict(type='image_url',image_url=dict(url=url)))
        else:raise ValueError('unsupported model content block')
    return result


def payload(config,system,messages,options,reflection=False):
    protocol=config.api_type
    limit=options['reflection_max_tokens'] if reflection else options['dialogue_max_tokens']
    body=dict(model=config.model,stream=True)
    if protocol in ('minimax-messages','anthropic'):
        path='/anthropic/v1/messages' if protocol=='minimax-messages' else '/messages'
        body.update(system=system,messages=messages,max_tokens=limit)
    else:
        converted=[dict(role=m['role'],content=content_parts(m['content'],protocol)) for m in messages]
        if protocol=='openai-responses':
            path='/responses';body.update(instructions=system,input=converted,max_output_tokens=limit,store=False)
        else:
            path='/chat/completions';body.update(messages=[dict(role='system',content=system)]+converted)
            body[config.token_parameter]=limit
    if config.temperature:body['temperature']=options['temperature']
    effort=options['reflection_effort'] if reflection else options['dialogue_effort']
    if config.effort=='minimax':body['output_config']=dict(effort=effort)
    elif config.effort=='openai':
        if protocol=='openai-responses':body['reasoning']=dict(effort=effort)
        elif protocol=='openai-chat':body['reasoning_effort']=effort
        else:raise ValueError('OpenAI effort requires an OpenAI-compatible protocol')
    return path,body


def events(response,live):
    total=0;data=[]
    while True:
        if live and not live():raise InferenceCancelled('inference cancelled')
        line=response.readline(131073)
        total+=len(line)
        if total>1024*1024 or len(line)>131072:raise ValueError('provider stream budget exceeded')
        if not line or line in (b'\n',b'\r\n'):
            if data:yield b'\n'.join(data);data=[]
            if not line:break
        elif line.startswith(b'data:'):
            data.append(line[5:].lstrip(b' ').rstrip(b'\r\n'))


def read_text(response,protocol,live=None,on_text=lambda:None):
    text=[];done=False;limited=False;stop=False;used=0
    for raw in events(response,live):
        if raw==b'[DONE]':
            done=True;break
        value=json.loads(raw)
        if not isinstance(value,dict) or value.get('error') or value.get('type') in ('error','response.failed','response.incomplete'):
            raise ValueError('provider stream failed')
        fragment=''
        if protocol in ('minimax-messages','anthropic'):
            delta=value.get('delta',{})
            if value.get('type')=='content_block_delta' and delta.get('type')=='text_delta':fragment=delta.get('text','')
            reason=delta.get('stop_reason')
            if reason is not None and reason not in ('end_turn','stop_sequence'):limited=True
            if value.get('type')=='message_stop':done=True;stop=True
        elif protocol=='openai-responses':
            if value.get('type')=='response.output_text.delta':fragment=value.get('delta','')
            if value.get('type')=='response.completed':
                result=value.get('response',{})
                done=result.get('status')=='completed' and not result.get('incomplete_details')
                stop=done
                if not done:limited=True
        else:
            for choice in value.get('choices',[]):
                if choice.get('index',0)!=0:continue
                delta=choice.get('delta',{});fragment=delta.get('content') or ''
                if not isinstance(fragment,str):raise ValueError('unsupported chat delta')
                reason=choice.get('finish_reason')
                if reason=='stop':stop=True
                elif reason is not None:limited=True
        if fragment:
            if not isinstance(fragment,str):raise ValueError('invalid text delta')
            if not text:on_text()
            text.append(fragment)
            used+=len(fragment.encode())
            if used>=65536:raise ValueError('provider reply budget exceeded')
    if live and not live():raise InferenceCancelled('inference cancelled')
    result=''.join(text)
    if not done or not stop or limited or not result:raise ValueError('provider reply incomplete')
    return result
