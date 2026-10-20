#include "pet_wake.h"
#include "pet_wake_name.h"
#include "pet_wake_level.h"
#include "sdkconfig.h"
#include "esp_log.h"
#include "pet_util.h"
#include <string.h>
#include <stdatomic.h>
#include <stdlib.h>
#ifdef CONFIG_DESKPET_WAKE
#include "esp_mn_iface.h"
#include "esp_mn_speech_commands.h"
#include "model_path.h"
#include "esp_partition.h"
#include "mbedtls/sha256.h"
#include "freertos/FreeRTOS.h"
#include "pet_name_wake_model.h"
/* Do not use the factory handle: it links every language/model implementation. */
extern const esp_mn_iface_t esp_sr_multinet5_quantized8;
static const esp_mn_iface_t *s_net=&esp_sr_multinet5_quantized8;
static model_iface_data_t *s_model;
static int16_t *s_frame;
static size_t s_used,s_chunk;
static pet_wake_level_t s_level;
static atomic_bool s_ready;
static portMUX_TYPE s_lock=portMUX_INITIALIZER_UNLOCKED;
static char s_pending[64],s_phrase[32];
static unsigned s_version,s_applied;
static const void *s_weights;
static esp_partition_mmap_handle_t s_mapping;
static srmodel_data_t *s_model_files;
#ifndef PET_WAKE_BOOT_SELFTEST
#define PET_WAKE_BOOT_SELFTEST 0
#endif
#if PET_WAKE_BOOT_SELFTEST
static bool boot_selftest(void);
static bool s_test_raw;
#endif
static bool load_weights(void)
{
    if(s_weights)return true;
    const esp_partition_t *part=NULL;const void *mapped=NULL;
    /* Only register an in-memory description; no partition-table writes.
     * Registration fails on overlap with any real partition. This range must
     * be backed up and explicitly provisioned using models/provision_name_wake.py. */
    if(esp_partition_register_external(NULL,0xa00000,0x300000,"petwake",ESP_PARTITION_TYPE_DATA,0x40,&part)!=ESP_OK)return false;
    if(esp_partition_mmap(part,0,PET_NAME_WAKE_MODEL_BYTES,ESP_PARTITION_MMAP_DATA,&mapped,&s_mapping)!=ESP_OK)return false;
    unsigned char hash[32];char hex[65];static const char digits[]="0123456789abcdef";
    if(mbedtls_sha256(mapped,PET_NAME_WAKE_MODEL_BYTES,hash,0)!=0){esp_partition_munmap(s_mapping);return false;}
    for(int i=0;i<32;i++){hex[i*2]=digits[hash[i]>>4];hex[i*2+1]=digits[hash[i]&15];}hex[64]=0;
    if(strcmp(hex,PET_NAME_WAKE_MODEL_SHA256)){ESP_LOGE("pet_wake","name wake model integrity failed; touch remains available");esp_partition_munmap(s_mapping);return false;}
    srmodel_list_t *models=srmodel_load(mapped);
    s_weights=mapped;
    s_model_files=models&&models->num==1?models->model_data[0]:NULL;
    return models&&models->num==1&&!strcmp(models->model_name[0],"mn5q8_cn");
}
bool pet_wake_init(void)
{
    if(s_model)return true;
    if(!load_weights())return false;
    s_model=s_net->create("mn5q8_cn",4000);
    if(!s_model)return false;
    s_chunk=s_net->get_samp_chunksize(s_model);
    if(s_chunk<1||s_chunk>2048||s_net->get_samp_rate(s_model)!=16000){s_net->destroy(s_model);s_model=NULL;return false;}
    s_frame=pet_alloc(s_chunk*sizeof(int16_t));
    if(!s_frame){s_net->destroy(s_model);s_model=NULL;return false;}
    esp_mn_commands_alloc(s_net,s_model);s_net->set_det_threshold(s_model,0.90f);
    ESP_LOGI("pet_wake","experimental offline name recognizer ready, chunk=%u",(unsigned)s_chunk);
#if PET_WAKE_BOOT_SELFTEST
    if(!boot_selftest()){ESP_LOGE("pet_wake","name selftest failed; capture remains touch-only");esp_mn_commands_free();s_net->destroy(s_model);s_model=NULL;free(s_frame);s_frame=NULL;atomic_store(&s_ready,false);return false;}
#endif
    return true;
}
bool pet_wake_ready(void){return atomic_load(&s_ready);}
void pet_wake_set_name(const char *name)
{
    char phrase[32],pinyin[64];bool valid=pet_wake_name_build(name,phrase,sizeof(phrase),pinyin,sizeof(pinyin));
    if(!valid)phrase[0]=pinyin[0]=0;
    portENTER_CRITICAL(&s_lock);
    if(strcmp(s_pending,pinyin)||strcmp(s_phrase,phrase)){
        memcpy(s_pending,pinyin,strlen(pinyin)+1);memcpy(s_phrase,phrase,strlen(phrase)+1);s_version++;
        atomic_store(&s_ready,false);
    }
    portEXIT_CRITICAL(&s_lock);
}
void pet_wake_phrase(char *out,size_t size)
{
    portENTER_CRITICAL(&s_lock);pet_utf8_copy(out,size,s_phrase);portEXIT_CRITICAL(&s_lock);
}
static bool apply_name(void)
{
    char command[64];unsigned version;
    portENTER_CRITICAL(&s_lock);version=s_version;memcpy(command,s_pending,sizeof(command));portEXIT_CRITICAL(&s_lock);
    if(version==s_applied)return atomic_load(&s_ready);
    s_applied=version;s_used=0;s_level=(pet_wake_level_t){0};s_net->clean(s_model);esp_mn_commands_clear();
    bool ok=command[0]&&esp_mn_commands_add(1,command)==ESP_OK;
    if(ok)ok=esp_mn_commands_update()==NULL;
    portENTER_CRITICAL(&s_lock);if(version==s_version)atomic_store(&s_ready,ok);portEXIT_CRITICAL(&s_lock);
    ESP_LOGI("pet_wake","name binding %s; phonemes=%s",ok?"ready":"unavailable",command);
    return ok;
}
bool pet_wake_feed(const int16_t *pcm,size_t samples)
{
    if(!s_model||!apply_name())return false;
    for(size_t at=0;at<samples;){
        size_t n=s_chunk-s_used;if(n>samples-at)n=samples-at;
        memcpy(s_frame+s_used,pcm+at,n*sizeof(int16_t));s_used+=n;at+=n;
        if(s_used==s_chunk){
#if PET_WAKE_BOOT_SELFTEST
            if(!s_test_raw)
#endif
                pet_wake_level(&s_level,s_frame,s_chunk);
            esp_mn_state_t state=s_net->detect(s_model,s_frame);s_used=0;
            if(state==ESP_MN_STATE_DETECTED){
                esp_mn_results_t *r=s_net->get_results(s_model);
                /* MultiNet's returned ranking probability is not its detection threshold.
                 * Trust DETECTED, and invalidate a concurrent old-name result. */
                portENTER_CRITICAL(&s_lock);
                bool hit=r&&r->num>0&&r->command_id[0]==1&&atomic_load(&s_ready)&&s_applied==s_version;
                portEXIT_CRITICAL(&s_lock);
                ESP_LOGI("pet_wake","candidate id=%d score=%.3f accepted=%d",r&&r->num?r->command_id[0]:0,r&&r->num?r->prob[0]:0.f,hit);
                s_net->clean(s_model);if(hit)return true;
            }else if(state==ESP_MN_STATE_TIMEOUT)s_net->clean(s_model);
        }
    }
    return false;
}
void pet_wake_reset(void){s_used=0;s_level=(pet_wake_level_t){0};if(s_model)s_net->clean(s_model);}
const void *pet_wake_test_audio(const char *fixture,size_t *bytes)
{
    *bytes=0;if(!s_model_files||!fixture||strncmp(fixture,"_TEST_",6))return NULL;
    for(int i=0;i<s_model_files->num;i++)if(!strcmp(s_model_files->files[i],fixture)){
        *bytes=s_model_files->sizes[i];return s_model_files->data[i];
    }
    return NULL;
}
#if PET_WAKE_BOOT_SELFTEST
static bool selftest_case(const char *name,const char *file,bool expected,int divisor,bool normalize)
{
    const unsigned char *data=NULL;size_t bytes=0;
    for(int i=0;i<s_model_files->num;i++)if(!strcmp(s_model_files->files[i],file)){data=(const unsigned char*)s_model_files->data[i];bytes=s_model_files->sizes[i];break;}
    if(!data||bytes%2)return false;
    s_test_raw=!normalize;
    pet_wake_set_name(name);pet_wake_reset();bool hit=false;int16_t frame[512];
    memset(frame,0,sizeof(frame));
    for(int warm=0;warm<20;warm++){if(pet_wake_feed(frame,512))hit=true;vTaskDelay(pdMS_TO_TICKS(1));}
    for(size_t at=0;at<bytes/2+16000;at+=512){
        memset(frame,0,sizeof(frame));size_t n=at<bytes/2?bytes/2-at:0;if(n>512)n=512;
        if(n)memcpy(frame,data+at*2,n*2);
        for(size_t i=0;i<n;i++)frame[i]/=divisor;
        if(pet_wake_feed(frame,512))hit=true;
        vTaskDelay(pdMS_TO_TICKS(1));
    }
    ESP_LOGI("pet_wake","SELFTEST name=%s file=%s divisor=%d normalized=%d hit=%d expected=%d",name,file,divisor,normalize,hit,expected);
    return hit==expected;
}
static bool boot_selftest(void)
{
    bool ok=true;
    ok=selftest_case("小西","_TEST_xiaoxi",true,1,true)&&ok;
    ok=selftest_case("小西","_TEST_xiaoyue",false,1,true)&&ok;
    ok=selftest_case("小月","_TEST_xiaoyue",true,1,true)&&ok;
    ok=selftest_case("小月","_TEST_xiaoxi",false,1,true)&&ok;
    ok=selftest_case("小西","_TEST_ordinary",false,1,true)&&ok;
    ok=selftest_case("小西","_TEST_near",false,1,true)&&ok;
    /* Matched quiet recordings before/after, using the very same decoder.
     * Raw baseline is observational, never an assumed failure criterion. */
    selftest_case("小西","_TEST_xiaoxi",true,8,false);
    ok=selftest_case("小西","_TEST_xiaoxi",true,8,true)&&ok;
    ok=selftest_case("小月","_TEST_xiaoyue",true,8,true)&&ok;
    ok=selftest_case("小西","_TEST_ordinary",false,8,true)&&ok;
    ok=selftest_case("小西","_TEST_near",false,8,true)&&ok;
    s_test_raw=false;
    pet_wake_set_name("");pet_wake_reset();
    return ok;
}
#endif

#else
bool pet_wake_init(void){return false;}
bool pet_wake_ready(void){return false;}
bool pet_wake_feed(const int16_t *pcm,size_t samples){return false;}
void pet_wake_reset(void){}
void pet_wake_set_name(const char *name){}
void pet_wake_phrase(char *out,size_t size){if(size)out[0]=0;}
const void *pet_wake_test_audio(const char *fixture,size_t *bytes){*bytes=0;return NULL;}
#endif
