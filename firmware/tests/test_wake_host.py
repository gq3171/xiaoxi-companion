"""Run real name-wake binding against a deterministic SDK detector, not acoustics."""
import unittest
import test_runtime_core

class WakeHostTests(unittest.TestCase):
    def test_media_return_resumes_after_long_view_without_keeping_mic_open_or_overriding_rest(self):
        test_runtime_core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include "pet_wake_gate.h"
int main(void){
 pet_wake_require(true);pet_wake_open(1000);pet_wake_media_begin();
 assert(pet_wake_active(2000));assert(!pet_wake_active(121000));
 assert(pet_wake_media_return(121000)&&pet_wake_active(121001));
 assert(!pet_wake_active(141001));assert(!pet_wake_media_return(142000));
 pet_wake_open(200000);pet_wake_media_begin();pet_wake_rest();
 assert(!pet_wake_media_return(250000)&&pet_wake_resting()&&!pet_wake_active(250000));
 pet_wake_open(300000);pet_wake_media_begin();pet_wake_end_conversation();
 assert(!pet_wake_media_return(350000)&&!pet_wake_active(350000));
 pet_wake_open(400000);pet_wake_media_begin();pet_wake_sleep();
 assert(pet_wake_media_return(450000));return 0;
}
''',['pet_wake_gate'])

    def test_local_wake_level_boosts_quiet_frames_without_clipping_or_changing_source(self):
        test_runtime_core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "pet_wake_level.h"
int main(void){
 pet_wake_level_t s={0};int16_t frame[512];
 for(int i=0;i<512;i++)frame[i]=i%2?8:-8;
 for(int n=0;n<80;n++)pet_wake_level(&s,frame,512);
 assert(frame[0]==-8&&frame[1]==8&&s.gain==1);
 for(int n=0;n<30;n++){
  for(int i=0;i<512;i++)frame[i]=i%2?200:-200;
  pet_wake_level(&s,frame,512);
 }
 assert(frame[1]>=1390&&frame[1]<=1400&&s.gain<=8);
 for(int i=0;i<512;i++)frame[i]=i%2?30000:-30000;
 pet_wake_level(&s,frame,512);assert(frame[0]==-30000&&frame[1]==30000&&s.gain==1);
 for(int n=0;n<30;n++){
  for(int i=0;i<512;i++)frame[i]=i%2?50:-50;
  pet_wake_level(&s,frame,512);
 }
 assert(frame[1]<=400&&s.gain<=8);
 frame[0]=-32768;frame[1]=32767;pet_wake_level(&s,frame,512);
 assert(frame[0]==-32768&&frame[1]==32767);
 for(int n=0;n<80;n++){
  memset(frame,0,sizeof(frame));pet_wake_level(&s,frame,512);
 }
 assert(s.gain<1.03);return 0;
}
''',['pet_wake_level'])
    def test_rebinding_invalidates_inflight_old_name_without_second_probability_gate(self):
        sdk=r'''
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#define ESP_OK 0
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGE(...) ((void)0)
#define CONFIG_DESKPET_WAKE 1
#define portENTER_CRITICAL(x) ((void)0)
#define portEXIT_CRITICAL(x) ((void)0)
#define portMUX_INITIALIZER_UNLOCKED 0
typedef int portMUX_TYPE;
typedef struct {} model_iface_data_t;
typedef enum {ESP_MN_STATE_DETECTING,ESP_MN_STATE_DETECTED,ESP_MN_STATE_TIMEOUT} esp_mn_state_t;
typedef struct {int num;int command_id[5];float prob[5];} esp_mn_results_t;
typedef struct {
 model_iface_data_t *(*create)(const char*,int);
 int (*get_samp_chunksize)(model_iface_data_t*);
 int (*get_samp_rate)(model_iface_data_t*);
 void (*destroy)(model_iface_data_t*);
 int (*set_det_threshold)(model_iface_data_t*,float);
 esp_mn_state_t (*detect)(model_iface_data_t*,int16_t*);
 esp_mn_results_t *(*get_results)(model_iface_data_t*);
 void (*clean)(model_iface_data_t*);
} esp_mn_iface_t;
typedef struct {int num;char **files,**data;int *sizes;} srmodel_data_t;
typedef struct {int num;char **model_name;srmodel_data_t **model_data;} srmodel_list_t;
typedef struct {int dummy;} esp_partition_t;
typedef uintptr_t esp_partition_mmap_handle_t;
#define ESP_PARTITION_TYPE_DATA 1
#define ESP_PARTITION_MMAP_DATA 0
int esp_partition_register_external(void*,size_t,size_t,const char*,int,int,const esp_partition_t**);
int esp_partition_mmap(const esp_partition_t*,size_t,size_t,int,const void**,esp_partition_mmap_handle_t*);
void esp_partition_munmap(esp_partition_mmap_handle_t);
int mbedtls_sha256(const unsigned char*,size_t,unsigned char*,int);
srmodel_list_t *srmodel_load(const void*);
int esp_mn_commands_alloc(const esp_mn_iface_t*,model_iface_data_t*);
int esp_mn_commands_clear(void);
int esp_mn_commands_add(int,const char*);
void *esp_mn_commands_update(void);
'''
        headers={name:'#include "wake_test_sdk.h"\n' for name in ['sdkconfig.h','esp_log.h','esp_mn_iface.h','esp_mn_speech_commands.h','model_path.h','esp_partition.h','mbedtls/sha256.h','freertos/FreeRTOS.h']}
        headers["wake_test_sdk.h"]=sdk
        body=r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "sdkconfig.h"
#include "pet_wake.h"
#include "pet_name_wake_model.h"
static char command[64];static int candidates,detects;static bool rename_inside;
static model_iface_data_t object;
static model_iface_data_t *create(const char*n,int d){assert(!strcmp(n,"mn5q8_cn")&&d==4000);return &object;}
static int chunk(model_iface_data_t*m){return 4;}
static int rate(model_iface_data_t*m){return 16000;}
static void destroy(model_iface_data_t*m){}
static int threshold(model_iface_data_t*m,float t){assert(t==0.90f);return 0;}
static void clean(model_iface_data_t*m){}
static esp_mn_state_t detect(model_iface_data_t*m,int16_t*f){detects++;if(rename_inside){rename_inside=false;pet_wake_set_name("小月");}return candidates?ESP_MN_STATE_DETECTED:ESP_MN_STATE_DETECTING;}
static esp_mn_results_t *results(model_iface_data_t*m){static esp_mn_results_t r={.num=1,.command_id={1},.prob={0.05f}};return &r;}
const esp_mn_iface_t esp_sr_multinet5_quantized8={create,chunk,rate,destroy,threshold,detect,results,clean};
int esp_partition_register_external(void*c,size_t o,size_t n,const char*l,int t,int s,const esp_partition_t**p){static esp_partition_t part;assert(o==0xa00000&&n==0x300000);*p=&part;return 0;}
int esp_partition_mmap(const esp_partition_t*p,size_t o,size_t n,int m,const void**v,esp_partition_mmap_handle_t*h){static unsigned char dummy;assert(n==PET_NAME_WAKE_MODEL_BYTES);*v=&dummy;return 0;}
void esp_partition_munmap(esp_partition_mmap_handle_t h){}
int mbedtls_sha256(const unsigned char*p,size_t n,unsigned char*out,int k){const char*hex=PET_NAME_WAKE_MODEL_SHA256;for(int i=0;i<32;i++){char s[]={hex[i*2],hex[i*2+1],0};out[i]=strtoul(s,0,16);}return 0;}
srmodel_list_t *srmodel_load(const void*p){static char *name[]={"mn5q8_cn"};static srmodel_data_t data;static srmodel_data_t *entries[]={&data};static srmodel_list_t models={1,name,entries};return &models;}
int esp_mn_commands_alloc(const esp_mn_iface_t*n,model_iface_data_t*m){return 0;}
int esp_mn_commands_clear(void){command[0]=0;return 0;}
int esp_mn_commands_add(int id,const char*s){assert(id==1);strcpy(command,s);return 0;}
void *esp_mn_commands_update(void){return NULL;}
int main(void){int16_t frame[4]={0};char phrase[32];
 assert(pet_wake_init()&&!pet_wake_ready());
 pet_wake_set_name("小西");assert(!pet_wake_feed(frame,4));
 assert(pet_wake_ready()&&!strcmp(command,"xiao xi xiao xi"));
 candidates=1;assert(pet_wake_feed(frame,4));
 rename_inside=true;assert(!pet_wake_feed(frame,4)); /* old result cannot open new name */
 assert(!pet_wake_ready());assert(pet_wake_feed(frame,4));
 assert(!strcmp(command,"xiao yue xiao yue"));pet_wake_phrase(phrase,sizeof(phrase));assert(!strcmp(phrase,"小月小月"));
 pet_wake_set_name("Alice");int old=detects;assert(!pet_wake_feed(frame,4)&&!pet_wake_ready()&&detects==old);
 pet_wake_phrase(phrase,sizeof(phrase));assert(!phrase[0]);
 return 0;}
'''
        test_runtime_core.RuntimeCoreTests.run_c(self,body,['pet_wake','pet_wake_level','pet_wake_name','pet_util'],headers,compiler_flags=['-DPET_WAKE_BOOT_SELFTEST=0'])
