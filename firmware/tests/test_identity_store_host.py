"""Real CRC snapshots: legacy text is retained until a normalized review commits."""
import unittest
import test_runtime_core

SDK=r'''
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define ESP_OK 0
#define ESP_LOGE(...) ((void)0)
#define NVS_READONLY 0
#define NVS_READWRITE 1
#define CONFIG_DESKPET_WIFI_SSID ""
#define CONFIG_DESKPET_WIFI_PASSWORD ""
typedef int nvs_handle_t;
typedef int esp_err_t;
typedef struct {const char *base_path,*partition_label;int max_files;bool format_if_mount_failed;} esp_vfs_spiffs_conf_t;
static inline int esp_vfs_spiffs_register(const esp_vfs_spiffs_conf_t *c){return 0;}
static inline int nvs_open(const char *s,int m,nvs_handle_t *h){return -1;}
static inline void nvs_close(nvs_handle_t h){}
static inline int nvs_get_u8(nvs_handle_t h,const char *k,uint8_t *v){return -1;}
static inline int nvs_set_u8(nvs_handle_t h,const char *k,uint8_t v){return 0;}
static inline int nvs_get_u32(nvs_handle_t h,const char *k,uint32_t *v){return -1;}
static inline int nvs_set_u32(nvs_handle_t h,const char *k,uint32_t v){return 0;}
static inline int nvs_get_str(nvs_handle_t h,const char *k,char *v,size_t *n){return -1;}
static inline int nvs_set_str(nvs_handle_t h,const char *k,const char *v){return 0;}
static inline int nvs_commit(nvs_handle_t h){return 0;}
'''

class IdentityStoreHostTests(unittest.TestCase):
    def test_legacy_migration_never_writes_raw_model_failure_or_unconfirmed_output(self):
        headers={'identity_test_sdk.h':SDK}
        headers.update({name:'#include \"identity_test_sdk.h\"\n' for name in ['esp_log.h','esp_spiffs.h','nvs.h','sdkconfig.h']})
        code=r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "pet_store.h"
#include "pet_util.h"
#include "pet_birth.h"
int main(void){
 uint32_t seq=0;assert(pet_snapshot_save(@FLASH@ "/birth","{\"name\":\"以后你就叫小西\",\"soul\":\"你自己定吧\"}",8192,&seq)==0);
 assert(pet_store_start()==0 && pet_store_identity_needs_review());
 cJSON *legacy=pet_store_identity_legacy();assert(legacy);cJSON_Delete(legacy);
 cJSON *bad=cJSON_Parse("{\"name\":\"小西\"}");assert(pet_store_write_identity(bad)==-1);cJSON_Delete(bad);
 assert(pet_store_identity_needs_review());
 pet_birth_t b;pet_birth_init(&b);char q[384];
 assert(pet_birth_apply(&b,"{\"updates\":[{\"field\":\"name\",\"mode\":\"explicit\",\"value\":\"小西\"},{\"field\":\"creature\",\"mode\":\"develop\",\"value\":\"\"},{\"field\":\"vibe\",\"mode\":\"develop\",\"value\":\"\"},{\"field\":\"soul\",\"mode\":\"develop\",\"value\":\"\"},{\"field\":\"user_name\",\"mode\":\"explicit\",\"value\":\"主人\"}],\"question\":\"\"}",q,sizeof(q))==1);
 cJSON *identity=pet_birth_identity(&b);assert(pet_store_write_identity(identity)==0);
 cJSON_Delete(identity);pet_birth_free(&b);
 assert(pet_store_start()==0 && !pet_store_identity_needs_review());
 char context[4000];assert(pet_store_system(context,sizeof(context))==0);
 assert(strstr(context,"你的名字：小西") && !strstr(context,"以后你就叫"));
 /* The preceding legacy generation remains recoverable in the other slot. */
 char *snapshot=pet_snapshot_load(@FLASH@ "/birth",8192,&seq);assert(snapshot && seq==2);free(snapshot);
 return 0;
}
'''
        test_runtime_core.RuntimeCoreTests.run_c(self,code,['pet_store','pet_birth','pet_memory','pet_util'],headers)
