"""Bounded one-segment-ahead TTS, relayed as a single existing SSE stream.

    Each producer is daemonized and owns its upstream response. Queues provide
    backpressure (four events per segment; <=33KiB per relayed event). Only two segments
    can be resident. Cancellation never sends a synthetic successful terminal.
"""
from contextlib import contextmanager
import json
import queue
import threading
import time
from runtime_support import failure_category


def segments(text, budget=150):
    result, part, size, boundary = [], '', 0, 0
    for char in text:
        length = len(char.encode())
        if size+length > budget and part:
            split = boundary if boundary and len(part[:boundary].encode()) > budget//3 else len(part)
            result.append(part[:split]);part=part[split:];size=len(part.encode());boundary=0
        part += char;size += length
        if char in '。！？!?.,，\n': boundary=len(part)
    if part:result.append(part)
    return result


class AudioSegment:
    def __init__(self, provider, speech, live, slots, trace=None):
        self.provider,self.speech,self.live=provider,speech,live
        self.queue=queue.Queue(maxsize=4)
        self.stop=threading.Event()
        self.trace=trace
        self.slots=slots
        self.thread=threading.Thread(target=self.produce,daemon=True,name='tts-prefetch')
        self.thread.start()

    def put(self, value):
        while not self.stop.is_set() and self.live():
            try:self.queue.put(value,timeout=.1);return True
            except queue.Full:pass
        return False

    def produce(self):
        acquired=False
        try:
            while not self.stop.is_set() and self.live():
                if self.slots.acquire(timeout=.1):acquired=True;break
            if not acquired:return
            body=json.dumps(self.speech,ensure_ascii=False,separators=(',',':')).encode()
            total, audio, done = 0, False, False
            if self.trace:self.trace.mark('tts_upstream_request')
            with self.provider.request('/v1/t2a_v2',body) as response:
                if self.trace:self.trace.mark('tts_upstream_headers')
                while not self.stop.is_set() and self.live():
                    line=response.readline(256*1024+1)
                    if not line:break
                    total+=len(line)
                    if len(line)>256*1024 or total>8*1024*1024:
                        raise ValueError('segment stream budget')
                    if not line.startswith(b'data:'):continue
                    payload=line[5:].strip()
                    if payload==b'[DONE]':continue
                    value=json.loads(payload)
                    if value.get('base_resp',{}).get('status_code',0)!=0:
                        raise ValueError('TTS provider error')
                    data=value.get('data',{})
                    status=data.get('status');hex_audio=data.get('audio','')
                    if not isinstance(hex_audio,str) or done:
                        raise ValueError('invalid TTS sequence')
                    if status==2:
                        if hex_audio or not audio:raise ValueError('invalid TTS terminal')
                        done=True
                        break
                    if status!=1 or len(hex_audio)%4 or any(c not in '0123456789abcdefABCDEF' for c in hex_audio):
                        raise ValueError('invalid PCM event')
                    if hex_audio:
                        audio=True
                        if self.trace:self.trace.mark('tts_first_audio')
                        # Fit the ESP SSE parser's 128KiB buffers even if the
                        # provider emits a much larger frame; PCM stays aligned.
                        for offset in range(0,len(hex_audio),32768):
                            event=json.dumps({'data':{'status':1,'audio':hex_audio[offset:offset+32768]}},separators=(',',':')).encode()
                            if not self.put(event):return
            if not done:raise ValueError('incomplete TTS segment')
            self.put(None)
        except Exception as error:
            if self.trace:self.trace.status=failure_category(error)
            # Never send exception bodies, provider credentials, or partial JSON.
            self.put(ValueError('TTS segment incomplete'))
        finally:
            if acquired:self.slots.release()

    def take(self):
        while not self.stop.is_set() and self.live():
            try:return self.queue.get(timeout=.1)
            except queue.Empty:pass
        raise ValueError('audio stream cancelled')

    def cancel(self):
        self.stop.set()


class SpeechPipeline:
    def __init__(self, provider):
        self.provider=provider
        self.capacity=threading.BoundedSemaphore(1)
        self.upstream_slots=threading.BoundedSemaphore(2)

    @contextmanager
    def events(self,speech,live,trace=None):
        if not self.capacity.acquire(blocking=False):
            raise ValueError('audio stream already active')
        active=[]
        started=time.monotonic()
        current=lambda:live() and time.monotonic()-started<120
        def start(text):
            request=dict(speech,text=text,stream=True)
            request['stream_options']={'exclude_aggregated_audio':True}
            return AudioSegment(self.provider,request,current,self.upstream_slots,trace)
        def iterate():
            parts=segments(speech['text'])
            if not parts:raise ValueError('empty speech')
            active.append(start(parts[0]))
            next_index=1
            samples=0
            # Start one lookahead after first audio, preserving first-segment
            # priority. Queues bound memory if the client consumes slowly.
            for index in range(len(parts)):
                segment=active[0]
                while True:
                    event=segment.take()
                    if isinstance(event,Exception):raise event
                    if event is None:break
                    if len(active)==1 and next_index<len(parts):
                        active.append(start(parts[next_index]));next_index+=1
                    samples+=len(json.loads(event)['data']['audio'])//4
                    if samples>16000*120:raise ValueError('total audio duration budget')
                    yield event
                active.pop(0);segment.cancel()
                if not active and next_index<len(parts):
                    active.append(start(parts[next_index]));next_index+=1
            if not current():raise ValueError('stale audio completion')
            yield b'{"data":{"status":2,"audio":""}}'
        try:
            yield iterate()
        finally:
            for segment in active:segment.cancel()
            # Producers are bounded and observe stop between reads/puts. Do not
            # block the HTTP worker waiting on an upstream stalled socket.
            self.capacity.release()
