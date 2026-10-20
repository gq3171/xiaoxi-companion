"""Actual ESP transport outbox against a deterministic server/flash fixture."""
import unittest
import test_runtime_core as runtime_core

HEADERS = {
    'sdkconfig.h': '#define CONFIG_DESKPET_REMOTE_BRAIN 1\n#define CONFIG_DESKPET_BRAIN_TOKEN "test-only-pair"\n',
    'esp_mac.h': '#include <stdint.h>\n#define ESP_OK 0\n#define ESP_FAIL -1\ntypedef int esp_err_t;\nstatic inline int esp_efuse_mac_get_default(uint8_t *p){for(int i=0;i<6;i++)p[i]=i;return 0;}\n',
    'esp_random.h': '#include <stdint.h>\nstatic inline uint32_t esp_random(void){static uint32_t i=0;return ++i;}\n',
    'esp_log.h': '#define ESP_LOGI(...) ((void)0)\n',
    'nvs.h': '#include <stdint.h>\ntypedef int nvs_handle_t;\n#define NVS_READWRITE 1\nstatic inline int nvs_open(const char*a,int b,nvs_handle_t*c){*c=1;return 0;}\nstatic inline int nvs_get_u32(int a,const char*b,uint32_t*c){*c=0;return 0;}\nstatic inline int nvs_set_u32(int a,const char*b,uint32_t c){return 0;}\nstatic inline int nvs_commit(int a){return 0;}\nstatic inline void nvs_close(int a){}\n',
}
FIXTURE = r'''
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include "pet_brain.h"
#include "pet_util.h"
#include "pet_home.h"
pet_home_status_t pet_home_status(void){return (pet_home_status_t){.activity=PET_HOME_IDLE};}
static int revision=1, applied=0, calls=0, lose_ack=1, installs=0;
static char operation_id[33];
static cJSON *mirror;
bool pet_cloud_computer_configured(void){return true;}
cJSON *pet_store_identity_export(void){return cJSON_Parse("{\"name\":\"test\"}");}
char *pet_memory_export(void){return cJSON_PrintUnformatted(mirror);}
int pet_memory_install_remote(const cJSON *value){cJSON_Delete(mirror);mirror=cJSON_Duplicate(value,true);installs++;return 0;}
char *pet_cloud_brain(const char *route,const cJSON *request){
    calls++;
    if(!strcmp(route,"memory")){
        cJSON *op=cJSON_GetObjectItem(request,"operation");
        const char *id=cJSON_GetObjectItem(op,"op_id")->valuestring;
        if(!operation_id[0]){snprintf(operation_id,sizeof(operation_id),"%s",id);applied++;revision++;}
        else assert(!strcmp(operation_id,id));
        if(lose_ack){lose_ack=0;return NULL;}
    }
    cJSON *reply=cJSON_CreateObject();
    cJSON_AddBoolToObject(reply,"ok",true);cJSON_AddNumberToObject(reply,"revision",revision);
    cJSON *value=cJSON_Parse("{\"history\":[],\"next_id\":1,\"cards\":[],\"pending\":[]}");
    if(applied)cJSON_AddItemToArray(cJSON_GetObjectItem(value,"history"),cJSON_CreateString("once"));
    cJSON_AddItemToObject(reply,"memory",value);cJSON_AddNumberToObject(reply,"result",1);
    char *raw=cJSON_PrintUnformatted(reply);cJSON_Delete(reply);return raw;
}
static cJSON *operation(void){return cJSON_Parse("{\"kind\":\"add\",\"role\":\"user\",\"owner\":true,\"text\":\"test\"}");}
static void init(void){mirror=cJSON_Parse("{\"history\":[],\"next_id\":1,\"cards\":[],\"pending\":[]}");assert(!pet_brain_start());}
'''

class BrainHostTests(unittest.TestCase):
    run_c = runtime_core.RuntimeCoreTests.run_c

    def test_receipts_are_durable_without_blocking_network_on_speech_path(self):
        self.run_c(FIXTURE + r'''
int main(void){init();const char *trace="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
 assert(pet_brain_receipt(trace,"accepted",0)==-1&&calls==0);
 assert(!pet_brain_receipt(trace,"accepted",1));assert(!pet_brain_receipt(trace,"displayed",0));assert(calls==0);
 uint32_t seq;char *raw=pet_snapshot_load(@FLASH@ "/brain-outbox",16384,&seq);assert(raw);
 cJSON *root=cJSON_Parse(raw),*ops=cJSON_GetObjectItem(root,"operations");assert(cJSON_GetArraySize(ops)==2);
 assert(!strcmp(cJSON_GetObjectItem(cJSON_GetArrayItem(ops,0),"stage")->valuestring,"accepted"));
 assert(!strcmp(cJSON_GetObjectItem(cJSON_GetArrayItem(ops,1),"stage")->valuestring,"displayed"));
 cJSON_Delete(root);free(raw);cJSON_Delete(mirror);return 0;}
''', ['pet_brain','pet_util','pet_turn'], HEADERS)

    def test_lost_ack_replays_same_id_once_and_idle_sync_does_not_write_flash(self):
        self.run_c(FIXTURE + r'''
int main(void){init();cJSON *op=operation();assert(pet_brain_memory(op)==-1);assert(applied==1);
 uint32_t seq=0;char *raw=pet_snapshot_load(@FLASH@ "/brain-outbox",16384,&seq);assert(raw);
 cJSON *saved=cJSON_Parse(raw);free(raw);assert(cJSON_GetArraySize(cJSON_GetObjectItem(saved,"operations"))==1);cJSON_Delete(saved);
 assert(pet_brain_reconcile());assert(applied==1);assert(cJSON_GetArraySize(cJSON_GetObjectItem(mirror,"history"))==1);
 raw=pet_snapshot_load(@FLASH@ "/brain-outbox",16384,&seq);saved=cJSON_Parse(raw);free(raw);
 assert(cJSON_GetArraySize(cJSON_GetObjectItem(saved,"operations"))==0);cJSON_Delete(saved);
 uint32_t previous=seq;int previous_installs=installs;pet_brain_tick(1);pet_brain_tick(31001);
 raw=pet_snapshot_load(@FLASH@ "/brain-outbox",16384,&seq);free(raw);assert(seq==previous);assert(installs==previous_installs);
 cJSON_Delete(op);cJSON_Delete(mirror);return 0;}
''', ['pet_brain','pet_util','pet_turn'], HEADERS)

    def test_outbox_write_failure_never_sends_unpersisted_operation(self):
        self.run_c(FIXTURE + r'''
int main(void){init();assert(mkdir(@FLASH@ "/brain-outbox.1",0700)==0);
 cJSON *op=operation();assert(pet_brain_memory(op)==-1);assert(calls==0);assert(applied==0);
 cJSON_Delete(op);cJSON_Delete(mirror);return 0;}
''', ['pet_brain','pet_util','pet_turn'], HEADERS)

if __name__ == '__main__': unittest.main()
