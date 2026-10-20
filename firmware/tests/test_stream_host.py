"""Exercise fragmented SSE, actual PCM sink cancellation, and gesture filtering."""
import unittest
import test_runtime_core
import test_controls


class StreamHostTests(unittest.TestCase):
    def test_name_repeat_pinyin_tracks_name_and_rejects_unsupported_or_truncated_names(self):
        test_runtime_core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include <string.h>
#include "pet_wake_name.h"
int main(void){char phrase[32],pinyin[64];
 assert(pet_wake_name_build("小西",phrase,sizeof(phrase),pinyin,sizeof(pinyin)));
 assert(!strcmp(phrase,"小西小西")&&!strcmp(pinyin,"xiao xi xiao xi"));
 assert(pet_wake_name_build("小月",phrase,sizeof(phrase),pinyin,sizeof(pinyin)));
 assert(!strcmp(phrase,"小月小月")&&!strcmp(pinyin,"xiao yue xiao yue"));
 assert(pet_wake_name_build("西",phrase,sizeof(phrase),pinyin,sizeof(pinyin))&&!strcmp(pinyin,"xi xi"));
 assert(!pet_wake_name_build("",phrase,sizeof(phrase),pinyin,sizeof(pinyin)));
 assert(!pet_wake_name_build("小西呀呀呀",phrase,sizeof(phrase),pinyin,sizeof(pinyin)));
 assert(!pet_wake_name_build("小西!",phrase,sizeof(phrase),pinyin,sizeof(pinyin)));
 assert(!pet_wake_name_build("Alice",phrase,sizeof(phrase),pinyin,sizeof(pinyin)));
 assert(!pet_wake_name_build("小西",phrase,10,pinyin,sizeof(pinyin))&&!phrase[0]&&!pinyin[0]);
 assert(!pet_wake_name_build("小西",phrase,sizeof(phrase),pinyin,10));
 assert(!pet_wake_name_build("\xe5",phrase,sizeof(phrase),pinyin,sizeof(pinyin)));
 assert(!pet_wake_name_build("\xed\xa0\x80",phrase,sizeof(phrase),pinyin,sizeof(pinyin)));
 return 0;}
''',["pet_wake_name"])

    def test_wake_window_timeout_hold_onboarding_and_unsigned_rollover(self):
        test_runtime_core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include "pet_wake_gate.h"
int main(void){
 assert(pet_wake_active(0)); /* Enrollment bypass. */
 pet_wake_require(true);assert(!pet_wake_active(0));
 uint32_t now=0xfffff000u;pet_wake_open(now);
 assert(pet_wake_active(now+19999)&&!pet_wake_active(now+20000));
 pet_wake_open(now);pet_wake_hold(true,now+1000);assert(pet_wake_active(now+120000));
 pet_wake_hold(false,now+120000);assert(!pet_wake_active(now+120000));
 pet_wake_open(now);pet_wake_hold(true,now+1000);pet_wake_activity(now+120000);
 pet_wake_hold(false,now+120000);assert(pet_wake_active(now+139999)&&!pet_wake_active(now+140000));
 pet_wake_heard(now);assert(pet_wake_feedback(now+2499)&&!pet_wake_feedback(now+2500));
 pet_wake_open(100);pet_wake_sleep();pet_wake_hold(false,200);assert(!pet_wake_active(201));
 pet_wake_require(false);assert(pet_wake_active(1000000));pet_wake_require(true);assert(!pet_wake_active(1000000));
 return 0;
}
''',['pet_wake_gate'])

    def test_pcm_ring_concurrent_order_backpressure_and_counter_rollover(self):
        test_runtime_core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include <pthread.h>
#include <sched.h>
#include "pet_pcm_ring.h"
static pet_pcm_ring_t r;static int16_t storage[1024];
static void *producer(void*u){
 for(unsigned i=0;i<100000;i++){int16_t v=(int16_t)i;while(!pet_pcm_ring_push(&r,&v,1))sched_yield();}return 0;
}
int main(void){
 pet_pcm_ring_init(&r,storage,1024);atomic_store(&r.read,0xfffffff0u);atomic_store(&r.write,0xfffffff0u);
 pthread_t p;assert(!pthread_create(&p,0,producer,0));
 for(unsigned i=0;i<100000;i++){int16_t v;while(!pet_pcm_ring_pop(&r,&v,1))sched_yield();assert(v==(int16_t)i);}
 pthread_join(p,0);assert(!pet_pcm_ring_used(&r));
 int16_t data[1030]={0};assert(pet_pcm_ring_push(&r,data,1030)==1024);assert(!pet_pcm_ring_push(&r,data,1));
 assert(pet_pcm_ring_pop(&r,data,1030)==1024);return 0;
}
''',['pet_pcm_ring'])

    def test_sse_all_fragment_boundaries_multiline_overflow_and_truncation(self):
        test_runtime_core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include <string.h>
#include "pet_stream.h"
static int calls;
static bool reject;
static bool event(const char *s,size_t n,void *u){calls++;assert(!strcmp(s,"{\"text\":\n\"你好\"}"));return !reject;}
int main(void){
 const char *wire=": keepalive\r\nevent: test\r\ndata: {\"text\":\r\ndata: \"你好\"}\r\n\r\n";
 char line[256],data[256];pet_sse_t s;
 for(size_t cut=0;cut<=strlen(wire);cut++){
  calls=0;pet_sse_init(&s,line,data,sizeof(line),event,0);
  assert(pet_sse_feed(&s,wire,cut));assert(pet_sse_feed(&s,wire+cut,strlen(wire)-cut));
  assert(pet_sse_complete(&s)&&calls==1);
 }
 calls=0;pet_sse_init(&s,line,data,sizeof(line),event,0);
 for(size_t i=0;i<strlen(wire);i++)assert(pet_sse_feed(&s,wire+i,1));
 assert(calls==1&&pet_sse_complete(&s));
 pet_sse_init(&s,line,data,sizeof(line),event,0);
 assert(pet_sse_feed(&s,"data: {}\n",9));assert(!pet_sse_complete(&s));
 pet_sse_init(&s,line,data,8,event,0);assert(!pet_sse_feed(&s,"data: 123456789\n\n",17));
 assert(!pet_sse_complete(&s));
 reject=true;pet_sse_init(&s,line,data,sizeof(line),event,0);assert(!pet_sse_feed(&s,wire,strlen(wire)));
 return 0;
}
''',['pet_stream'])

    def test_motion_requires_warmup_repetition_and_settling_and_recovers_stale_sensor(self):
        test_runtime_core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include <math.h>
#include "pet_motion.h"
int main(void){
 pet_motion_t s={0};uint32_t now=0xfffff000u;
 float a[]={0,0,1},g[]={0,0,0};
 for(int i=0;i<25;i++){now+=50;assert(!pet_motion_step(&s,a,g,now));}
 assert(s.ready&&!s.moving);
 /* Desk vibration and sensor noise do not create pickup/shake events. */
 for(int i=0;i<100;i++){a[0]=(i%2?1:-1)*.02f;g[0]=.3f;now+=50;assert(!pet_motion_step(&s,a,g,now));}
 a[0]=1.2f;now+=50;assert(!(pet_motion_step(&s,a,g,now)&PET_MOTION_SHAKEN));
 a[0]=0;now+=50;assert(!(pet_motion_step(&s,a,g,now)&PET_MOTION_SHAKEN));
 for(int i=0;i<30;i++){now+=50;pet_motion_step(&s,a,g,now);}
 unsigned events=0;g[1]=80;
 for(int i=0;i<5;i++){now+=50;events|=pet_motion_step(&s,a,g,now);}
 assert(events&PET_MOTION_MOVED);assert(s.moving&&s.rotation_dps>=80);
 g[1]=0;events=0;
 for(int i=0;i<24;i++){now+=50;events|=pet_motion_step(&s,a,g,now);}
 assert((events&PET_MOTION_SETTLED)&&!s.moving);
 for(int i=0;i<20;i++){now+=50;pet_motion_step(&s,a,g,now);}
 events=0;for(int i=0;i<10;i++){a[0]=i%2?.7f:-.7f;now+=50;events|=pet_motion_step(&s,a,g,now);}
 assert(events&PET_MOTION_SHAKEN);
 events=0;for(int i=0;i<10;i++){a[0]=i%2?.7f:-.7f;now+=50;events|=pet_motion_step(&s,a,g,now);}
 assert(!(events&PET_MOTION_SHAKEN)); /* Cooldown. */
 a[0]=0;now+=2000;assert(!pet_motion_step(&s,a,g,now));assert(!s.ready);
 for(int i=0;i<25;i++){now+=50;pet_motion_step(&s,a,g,now);}assert(s.ready);
 a[0]=NAN;assert(!pet_motion_step(&s,a,g,now+50));
 return 0;
}
''',['pet_motion'])

    def test_actual_audio_stream_keeps_aec_reference_and_rejects_stale_audio(self):
        prefix=test_controls.AUDIO.split('int main(void)',1)[0]
        prefix=prefix.replace('int esp_codec_dev_write(void *h, void *p, int n) { return 0; }',r'''
static atomic_int writes,refs,restarts,first_audio;static bool fail_write;
int esp_codec_dev_write(void *h,void *p,int n){assert(n>0&&n<=2048);assert(pet_audio_playing());writes++;return fail_write?-1:0;}
''')
        body=r'''
#include <pthread.h>
#include <time.h>
#include "pet_latency.h"
static void *worker_entry(void *arg){stream_player(0);return 0;}
int xTaskCreate(void (*f)(void *),const char*n,unsigned z,void*a,unsigned p,void*h){pthread_t thread;return pthread_create(&thread,0,worker_entry,0)==0?pdPASS:0;}
void vTaskDelay(TickType_t t){struct timespec ts={.tv_nsec=1000000};nanosleep(&ts,0);}

void pet_latency_mark(uint32_t g,pet_time_point_t p){assert(p==PET_TIME_SPEAKER);first_audio++;}
void pet_capture_reference(const int16_t *p,size_t n,bool restart){refs++;if(restart)restarts++;}
bool pet_capture_started(void){return false;}
bool pet_capture_take(pet_utterance_t*u,TickType_t t){return false;}
int main(void){
 pet_audio_start();int16_t pcm[1400]={0};uint32_t g=pet_turn_current();
 assert(pet_audio_stream_begin(g));assert(!pet_audio_playing());
 assert(pet_audio_stream_write(pcm,1400,g));
 assert(pet_audio_stream_write(pcm,37,g));pet_audio_stream_end(true);assert(writes==3&&refs==3&&restarts==1&&first_audio==1);
 pet_audio_stream_begin(g);pet_audio_stop();assert(!pet_audio_stream_write(pcm,10,g));assert(writes==3);
 pet_audio_stream_end(false);assert(!pet_audio_playing());
 pet_audio_stream_begin(g);pet_turn_next();assert(!pet_audio_stream_write(pcm,10,g));assert(writes==3);
 pet_audio_stream_end(false);g=pet_turn_current();pet_audio_stream_begin(g);pet_audio_allow_output(false);
 assert(!pet_audio_stream_write(pcm,10,g));assert(writes==3);
 pet_audio_stream_end(false);pet_audio_allow_output(true);pet_audio_stream_begin(g);fail_write=true;
 assert(pet_audio_stream_write(pcm,10,g));pet_audio_stream_end(true);assert(!pet_audio_stream_ok()&&!pet_audio_playing());
 fail_write=false;int before=writes,reference_before=refs;
 assert(pet_audio_wake_ack(g));
 for(int i=0;i<2000&&writes==before;i++)vTaskDelay(1);
 for(int i=0;i<2000&&!atomic_load(&s_stream_worker_done);i++)vTaskDelay(1);
 assert(writes==before+1&&refs==reference_before+1&&!pet_audio_playing());
 pet_audio_allow_output(false);assert(!pet_audio_wake_ack(g));pet_audio_allow_output(true);
 pet_turn_next();assert(!pet_audio_wake_ack(g));
 return 0;
}
'''
        headers={'sdk_test.h':test_controls.SDK,'sdkconfig.h':''}
        for name in ['bsp/esp-bsp.h','esp_codec_dev.h','esp_log.h','freertos/FreeRTOS.h','freertos/semphr.h','nvs.h']:
            headers[name]='#include "sdk_test.h"\n'
        test_runtime_core.RuntimeCoreTests.run_c(self,prefix+body,['pet_turn','pet_util','pet_pcm_ring'],headers)


if __name__=='__main__':unittest.main()
