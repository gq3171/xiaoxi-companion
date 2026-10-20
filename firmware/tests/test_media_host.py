"""Actual media C state machine; platform decoder/network mocked separately.

Real JPEG decode is checked at boot on ESP32, and real conversion/HTTP on RK.
"""
from pathlib import Path
import unittest
import test_runtime_core

HEADERS={
'esp_timer.h':'#include <stdint.h>\nint64_t esp_timer_get_time(void);',
'esp_log.h':'#define ESP_LOGI(...) ((void)0)\n',
'freertos/FreeRTOS.h':'#define pdMS_TO_TICKS(x) (x)\n',
'freertos/task.h':'void vTaskDelay(unsigned);',
'mbedtls/base64.h':'#include <stddef.h>\nint mbedtls_base64_decode(unsigned char*,size_t,size_t*,const unsigned char*,size_t);',
'esp_jpeg_dec.h':'''#include <stdint.h>
#include <stdlib.h>
#define DEFAULT_JPEG_DEC_CONFIG() {0}
#define JPEG_PIXEL_FORMAT_RGB565_LE 1
#define JPEG_ERR_OK 0
typedef struct{int output_type;}jpeg_dec_config_t;
typedef void* jpeg_dec_handle_t;
typedef struct{int width,height;}jpeg_dec_header_info_t;
typedef struct{unsigned char*inbuf;int inbuf_len;unsigned char*outbuf;}jpeg_dec_io_t;
static inline void*jpeg_calloc_align(size_t n,int a){return calloc(1,n);}
int jpeg_dec_open(jpeg_dec_config_t*,jpeg_dec_handle_t*);
int jpeg_dec_parse_header(jpeg_dec_handle_t,jpeg_dec_io_t*,jpeg_dec_header_info_t*);
int jpeg_dec_process(jpeg_dec_handle_t,jpeg_dec_io_t*);
int jpeg_dec_close(jpeg_dec_handle_t);
'''}

class MediaHostTests(unittest.TestCase):
    def test_real_client_mute_show_pause_resume_wrong_packet_and_voice_cancel(self):
        code=r'''
#include <assert.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include "pet_media.c"
static unsigned gen=1;static int vol=5,kind=0,requests=0,frames=0,writes=0,streams=0,closed=0,controls=0,stop_at=0,corrupt=0,cancel_at=0;
static char status[256];static int64_t clock_us;static const char *job="aa";static int presented,choices;static bool reject_catalog;
bool pet_computer_media_presented(const char *id){if(!strcmp(id,job)){presented++;return true;}return false;}
void pet_face_result_pending(bool pending){}
void*pet_alloc(size_t n){return malloc(n);}
uint32_t pet_turn_current(void){return gen;}bool pet_turn_valid(uint32_t n){return n==gen;}
int64_t esp_timer_get_time(void){clock_us+=50000;return clock_us;}void vTaskDelay(unsigned n){clock_us+=n*1000;}
bool pet_setup_connected(void){return false;}
pet_network_state_t pet_setup_network_state(void){return(pet_network_state_t){.connected=true,.rssi=-55};}
void pet_cloud_begin_turn(uint32_t n){}
char*pet_cloud_computer(const char*op,const cJSON*q){
 if(!strcmp(op,"media_list")){
 if(s_catalog_job[0])assert(!strcmp(text(q,"job_id"),s_catalog_job));
 char b[512];snprintf(b,sizeof(b),"{\"ok\":true,\"media\":[{\"job_id\":\"%s\",\"id\":\"bb\",\"title\":\"fixture\",\"kind\":\"%s\",\"frames\":%d,\"fps\":%d,\"has_audio\":%s}]}",reject_catalog?"different":job,kind==0?"image":kind==1?"audio":"video",kind==0?1:3,kind==0?0:kind==1?4:8,kind==0?"false":"true");return strdup(b);}
 unsigned i=(unsigned)cJSON_GetObjectItem(q,"index")->valueint;requests++;
 if(cancel_at&&requests==cancel_at)gen++;
 char b[512];snprintf(b,sizeof(b),"{\"ok\":true,\"job_id\":\"%s\",\"id\":\"%s\",\"index\":%u,\"eof\":%s,\"frame\":\"%s\",\"audio\":\"%s\"}",job,corrupt?"wrong":"bb",i,i+1==(kind==0?1:3)?"true":"false",kind==1?"":"pic",kind==0?"":"pcm");return strdup(b);}
int mbedtls_base64_decode(unsigned char*b,size_t cap,size_t*n,const unsigned char*in,size_t len){*n=4;memset(b,0,4);return 0;}
int jpeg_dec_open(jpeg_dec_config_t*c,jpeg_dec_handle_t*d){*d=(void*)1;return 0;}
int jpeg_dec_parse_header(jpeg_dec_handle_t d,jpeg_dec_io_t*i,jpeg_dec_header_info_t*h){h->width=320;h->height=240;return 0;}
int jpeg_dec_process(jpeg_dec_handle_t d,jpeg_dec_io_t*i){return 0;}int jpeg_dec_close(jpeg_dec_handle_t d){return 0;}
bool pet_audio_output_allowed(void){return true;}int pet_audio_get_volume(void){return vol;}
bool pet_audio_stream_ok(void){return true;}
bool pet_audio_stream_begin_media(uint32_t n){streams++;return true;}
bool pet_audio_stream_write(const int16_t*p,size_t n,uint32_t g){writes++;return pet_turn_valid(g);}
void pet_audio_stream_end(bool complete){}void pet_audio_stop(void){}
void pet_face_set(const char*p,const char*t){}void pet_face_media_open(const char*t,bool p){}
bool pet_face_media_frame(const uint16_t*p,int w,int h){assert(w==320&&h==240);frames++;return true;}
void pet_face_media_status(const char*s,bool playing){snprintf(status,sizeof(status),"%s",s);}
void pet_face_media_close(void){closed++;}
int pet_face_media_control(void){if(stop_at&&requests>=stop_at){stop_at=0;return 2;}int c=controls;controls=0;return c;}
int pet_face_choose(const char*t,const char*o,char*a,int n){choices++;snprintf(a,n,"1. fixture");return 0;}
static void reset(int type){kind=type;gen++;s_playing=false;s_request=0;s_selected=-1;s_index=0;requests=frames=writes=streams=closed=controls=stop_at=corrupt=cancel_at=0;vol=5;status[0]=0;s_catalog_job[0]=0;job="aa";presented=choices=0;reject_catalog=false;}
static void start(const char*a){pet_media_command(a,1,gen);pet_media_tick(gen);assert(!pet_media_active());}
int main(void){
 reset(0);start("show");assert(requests==1&&frames==1&&!writes&&strstr(status,"图片"));
 char ctx[2048];pet_media_context(ctx,sizeof(ctx));assert(strstr(ctx,"320x240")&&strstr(ctx,"图片已展示"));
 reset(1);vol=0;start("play");assert(!requests&&!streams&&strstr(status,"静音"));
 vol=5;controls=1;pet_media_tick(gen);assert(requests==3&&writes==3&&strstr(status,"完毕"));
 reset(2);start("show");assert(requests==1&&frames==1&&!writes&&!streams&&strstr(status,"点播放"));
 requests=0;controls=1;stop_at=1;pet_media_tick(gen);assert(requests==1&&s_index==1&&strstr(status,"暂停"));
 controls=1;pet_media_tick(gen);assert(requests==3&&s_index==3&&strstr(status,"完毕"));
 reset(2);corrupt=1;start("play");assert(!frames&&!writes&&s_index==0&&strstr(status,"中断"));
 reset(2);cancel_at=1;start("play");assert(!frames&&!writes&&closed==1&&s_index==0);
 reset(0);job="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";assert(pet_media_present_result(job,gen));pet_media_tick(gen);
 assert(requests==1&&frames==1&&presented==1&&!writes);
 controls=4;pet_media_tick(gen);assert(!s_catalog_job[0]&&choices==1); /* back means all results */
 reset(2);job="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";assert(pet_media_present_result(job,gen));pet_media_tick(gen);
 assert(frames==1&&presented==1&&!writes&&!streams&&strstr(status,"点播放"));
 reset(0);job="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";reject_catalog=true;assert(pet_media_present_result(job,gen));pet_media_tick(gen);
 assert(!requests&&!frames&&!presented); /* never show another recent job */
 reset(0);job="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";assert(pet_media_present_result(job,gen));gen++;pet_media_tick(gen);
 assert(!requests&&!frames&&!presented); /* a newer conversation wins */
 reset(0);job="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";corrupt=1;assert(pet_media_present_result(job,gen));pet_media_tick(gen);
 assert(!frames&&!presented); /* failed packets cannot acknowledge delivery */
 return 0;}
'''
        test_runtime_core.RuntimeCoreTests.run_c(self,code,["pet_wake_gate"],HEADERS)
