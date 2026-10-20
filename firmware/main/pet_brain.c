#include "pet_brain.h"
#include "sdkconfig.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "pet_cloud.h"
#include "pet_memory.h"
#include "pet_store.h"
#include "pet_util.h"
#include "pet_turn.h"
#include "pet_home.h"
#ifdef CONFIG_DESKPET_REMOTE_BRAIN
#include "esp_mac.h"
#include "esp_random.h"
#include "esp_log.h"
#include "nvs.h"
#ifndef PET_STORAGE_ROOT
#define PET_STORAGE_ROOT "/spiffs"
#endif
#define OUTBOX PET_STORAGE_ROOT "/brain-outbox"
static cJSON *s_outbox,*s_state;
static char s_device[13],s_session[33];
static uint32_t s_boot,s_sequence,s_revision,s_poll,s_mirror_crc;
static bool s_started,s_ready,s_writable;
static void random_id(char *out){snprintf(out,33,"%08x%08x%08x%08x",(unsigned)esp_random(),(unsigned)esp_random(),(unsigned)esp_random(),(unsigned)esp_random());}
static int save(void){cJSON_SetNumberValue(cJSON_GetObjectItem(s_state,"revision"),s_revision);cJSON_SetNumberValue(cJSON_GetObjectItem(s_state,"mirror_crc"),s_mirror_crc);char *raw=cJSON_PrintUnformatted(s_state);int r=raw?pet_snapshot_save(OUTBOX,raw,16384,&s_sequence):-1;free(raw);return r;}
static bool accept(cJSON *reply)
{
    cJSON *revision=cJSON_GetObjectItem(reply,"revision"),*memory=cJSON_GetObjectItem(reply,"memory");
    if(!cJSON_IsTrue(cJSON_GetObjectItem(reply,"ok"))||!cJSON_IsNumber(revision)||revision->valuedouble<1||revision->valuedouble>UINT32_MAX||!cJSON_IsObject(memory))return false;
    uint32_t next=(uint32_t)revision->valuedouble;
    if(next<s_revision)return false;
    if(next==s_revision)return true;
    if(next>s_revision&&pet_memory_install_remote(memory)!=0)return false;
    s_revision=next;char *mirror=pet_memory_export();if(!mirror)return false;s_mirror_crc=pet_crc32(mirror,strlen(mirror));free(mirror);
    return save()==0;
}
bool pet_brain_enabled(void){return CONFIG_DESKPET_BRAIN_TOKEN[0]&&pet_cloud_computer_configured();}
int pet_brain_start(void)
{
    if(s_started)return s_writable?0:-1;
    s_started=true;uint8_t mac[6];
    if(esp_efuse_mac_get_default(mac)!=ESP_OK)return -1;
    snprintf(s_device,sizeof(s_device),"%02x%02x%02x%02x%02x%02x",mac[0],mac[1],mac[2],mac[3],mac[4],mac[5]);random_id(s_session);
    nvs_handle_t nvs;if(nvs_open("pet_brain",NVS_READWRITE,&nvs)!=ESP_OK)return -1;
    nvs_get_u32(nvs,"boot",&s_boot);
    esp_err_t err=s_boot==UINT32_MAX?ESP_FAIL:nvs_set_u32(nvs,"boot",++s_boot);
    if(err==ESP_OK)err=nvs_commit(nvs);
    nvs_close(nvs);
    if(err!=ESP_OK)return -1;
    char *raw=pet_snapshot_load(OUTBOX,16384,&s_sequence);
    if(!raw&&pet_snapshot_exists(OUTBOX))return -1;
    s_state=raw?cJSON_Parse(raw):cJSON_CreateObject();free(raw);
    if(!s_state)return -1;
    if(!cJSON_GetObjectItem(s_state,"operations"))cJSON_AddArrayToObject(s_state,"operations");
    if(!cJSON_GetObjectItem(s_state,"revision"))cJSON_AddNumberToObject(s_state,"revision",0);
    if(!cJSON_GetObjectItem(s_state,"mirror_crc"))cJSON_AddNumberToObject(s_state,"mirror_crc",0);
    cJSON *revision=cJSON_GetObjectItem(s_state,"revision"),*crc=cJSON_GetObjectItem(s_state,"mirror_crc");
    if(!cJSON_IsNumber(revision)||revision->valuedouble<0||revision->valuedouble>UINT32_MAX||!cJSON_IsNumber(crc)||crc->valuedouble<0||crc->valuedouble>UINT32_MAX)return -1;
    s_outbox=cJSON_GetObjectItem(s_state,"operations");s_revision=(uint32_t)revision->valuedouble;s_mirror_crc=(uint32_t)crc->valuedouble;
    s_writable=cJSON_IsObject(s_state)&&cJSON_IsArray(s_outbox)&&cJSON_GetArraySize(s_outbox)<=12;
    return s_writable?0:-1;
}
cJSON *pet_brain_envelope(void)
{
    if(pet_brain_start()!=0)return NULL;
    cJSON *r=cJSON_CreateObject();cJSON_AddStringToObject(r,"device",s_device);cJSON_AddStringToObject(r,"session",s_session);
    cJSON_AddNumberToObject(r,"boot",s_boot);cJSON_AddNumberToObject(r,"generation",pet_turn_current());return r;
}
bool pet_brain_ensure(void)
{
    if(!pet_brain_enabled()||pet_brain_start()!=0)return false;
    if(s_ready)return true;
    cJSON *r=pet_brain_envelope();char *memory=pet_memory_export();cJSON *identity=pet_store_identity_export();
    char *birth=identity?cJSON_PrintUnformatted(identity):pet_strdup("{}");cJSON_Delete(identity);
    if(!r||!memory||!birth){cJSON_Delete(r);free(memory);free(birth);return false;}
    cJSON_AddStringToObject(r,"memory_raw",memory);cJSON_AddNumberToObject(r,"memory_crc",pet_crc32(memory,strlen(memory)));
    cJSON_AddNumberToObject(r,"mirror_revision",s_revision);cJSON_AddNumberToObject(r,"mirror_crc",s_mirror_crc);
    cJSON_AddStringToObject(r,"identity_raw",birth);free(memory);free(birth);
    char *raw=pet_cloud_brain("open",r);cJSON_Delete(r);
    cJSON *reply=raw?cJSON_Parse(raw):NULL;free(raw);
    s_ready=accept(reply);cJSON_Delete(reply);
    ESP_LOGI("pet_brain","server memory ready=%d revision=%u queued=%d",s_ready,(unsigned)s_revision,cJSON_GetArraySize(s_outbox));return s_ready;
}
static int flush(void)
{
    int result=-1;
    while(cJSON_GetArraySize(s_outbox)>0&&s_ready){
        cJSON *request=pet_brain_envelope();cJSON_AddItemToObject(request,"operation",cJSON_Duplicate(cJSON_GetArrayItem(s_outbox,0),true));
        char *raw=pet_cloud_brain("memory",request);cJSON_Delete(request);
        cJSON *reply=raw?cJSON_Parse(raw):NULL;free(raw);
        if(!accept(reply)){cJSON_Delete(reply);s_ready=false;break;}
        cJSON *value=cJSON_GetObjectItem(reply,"result");result=cJSON_IsNumber(value)?value->valueint:-1;cJSON_Delete(reply);
        cJSON *done=cJSON_DetachItemFromArray(s_outbox,0);
        if(save()!=0){cJSON_InsertItemInArray(s_outbox,0,done);s_ready=false;return -1;}
        cJSON_Delete(done);
    }
    return result;
}
bool pet_brain_reconcile(void){if(!pet_brain_ensure())return false;if(cJSON_GetArraySize(s_outbox)>0)flush();return s_ready;}
static int queue_operation(const cJSON *operation)
{
    if(pet_brain_start()!=0||!s_writable||cJSON_GetArraySize(s_outbox)>=12)return -1;
    cJSON *copy=cJSON_Duplicate(operation,true);if(!copy)return -1;
    char id[33];random_id(id);cJSON_AddStringToObject(copy,"op_id",id);cJSON_AddItemToArray(s_outbox,copy);
    if(save()!=0){cJSON_DeleteItemFromArray(s_outbox,cJSON_GetArraySize(s_outbox)-1);return -1;}
    return 0;
}
int pet_brain_receipt(const char *trace,const char *stage,int source_id)
{
    if(!trace||strlen(trace)!=32||!stage)return -1;
    for(int i=0;i<32;i++)if(!((trace[i]>='0'&&trace[i]<='9')||(trace[i]>='a'&&trace[i]<='f')))return -1;
    if(!strcmp(stage,"accepted")&&source_id<=0)return -1;
    cJSON *op=cJSON_CreateObject();if(!op)return -1;
    cJSON_AddStringToObject(op,"kind","feedback");cJSON_AddStringToObject(op,"trace",trace);
    cJSON_AddStringToObject(op,"stage",stage);cJSON_AddNumberToObject(op,"source_id",source_id);
    int result=queue_operation(op);cJSON_Delete(op);return result;
}
int pet_brain_memory(const cJSON *operation)
{
    if(queue_operation(operation)!=0)return -1;
    if(!pet_brain_ensure())return -1;
    return flush();
}
void pet_brain_tick(uint32_t now)
{
    if(s_poll&&(int32_t)(now-s_poll)<0)return;
    s_poll=now+30000;
    if(!pet_brain_ensure())return;
    if(cJSON_GetArraySize(s_outbox)>0){flush();if(!s_ready)return;}
    cJSON *request=pet_brain_envelope(),*parts=cJSON_AddObjectToObject(request,"parts");
    cJSON *feedback=cJSON_AddObjectToObject(parts,"feedback");
    cJSON_AddNumberToObject(feedback,"uptime_ms",now);cJSON_AddNumberToObject(feedback,"activity",pet_home_status().activity);
    cJSON_AddNumberToObject(feedback,"computer_protocol",2);cJSON_AddNumberToObject(feedback,"home_protocol",2);cJSON_AddNumberToObject(feedback,"tts_protocol",2);
    const char *keys[]={"agency","life","computer"};
    for(int i=0;i<3;i++){
        char path[96];snprintf(path,sizeof(path),PET_STORAGE_ROOT "/%s",keys[i]);uint32_t sequence;
        char *raw=pet_snapshot_load(path,8192,&sequence);cJSON *value=raw?cJSON_Parse(raw):NULL;free(raw);
        if(value)cJSON_AddItemToObject(parts,keys[i],value);
    }
    cJSON *identity=pet_store_identity_export();if(identity)cJSON_AddItemToObject(parts,"identity",identity);
    char *raw=pet_cloud_brain("state",request);cJSON_Delete(request);cJSON *reply=raw?cJSON_Parse(raw):NULL;free(raw);
    if(!accept(reply))s_ready=false;
    cJSON_Delete(reply);
}
#else
bool pet_brain_enabled(void){return false;}
int pet_brain_start(void){return 0;}
bool pet_brain_ensure(void){return false;}
bool pet_brain_reconcile(void){return false;}
cJSON *pet_brain_envelope(void){return NULL;}
int pet_brain_memory(const cJSON *o){(void)o;return -1;}
int pet_brain_receipt(const char *t,const char *s,int id){(void)t;(void)s;(void)id;return -1;}
void pet_brain_tick(uint32_t now){(void)now;}
#endif
