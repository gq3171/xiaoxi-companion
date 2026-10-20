#include "pet_panel.h"
#ifdef CONFIG_DESKPET_PANEL_CACHE
#include "panel/pet_panel_manifest.h"
#include "pet_panel_cache.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef ESP_PLATFORM
#include "esp_partition.h"
#include "esp_flash.h"
#include "esp_log.h"
#include "mbedtls/base64.h"
#include "pet_cloud.h"
#include "pet_face.h"
#include "pet_util.h"
#include "pet_turn.h"
typedef struct {const esp_partition_t *partition;const uint8_t *map;esp_partition_mmap_handle_t handle;} slot_t;
static slot_t s_slots[2][2];
#else
/* Host renderer uses the exact public payloads, never the device's secrets. */
static uint8_t *s_host[2];
#endif
static const uint8_t *s_data[2];
static pet_panel_spec_t s_specs[2];
static const char *s_sha[2]={PET_PANEL_FONT_SHA,PET_PANEL_ART_SHA};
static void specifications(void){
 for(int j=0;j<2;j++){s_specs[j].kind=j+1;s_specs[j].bytes=j?PET_PANEL_ART_SIZE:PET_PANEL_FONT_SIZE;
  for(int i=0;i<32;i++){unsigned value;sscanf(s_sha[j]+2*i,"%2x",&value);s_specs[j].sha[i]=(uint8_t)value;}}
}
int pet_panel_start(void){
 specifications();
#ifdef ESP_PLATFORM
 uint32_t flash_bytes=0;
 const esp_partition_t *app=esp_partition_find_first(ESP_PARTITION_TYPE_APP,ESP_PARTITION_SUBTYPE_APP_FACTORY,NULL);
 const esp_partition_t *storage=esp_partition_find_first(ESP_PARTITION_TYPE_DATA,ESP_PARTITION_SUBTYPE_DATA_SPIFFS,"storage");
 if(esp_flash_get_size(NULL,&flash_bytes)!=ESP_OK||flash_bytes!=0x1000000||!app||app->address!=0x10000||app->size!=0x800000||!storage||storage->address!=0x810000||storage->size!=0x100000){
  ESP_LOGW("pet_panel","cache layout unavailable; local fallback retained");return 0;
 }
 const uint32_t offsets[2][2]={{0xd00000,0xe20000},{0xf40000,0x910000}};
 const uint32_t sizes[2][2]={{0x120000,0x120000},{0xc0000,0xf0000}};
 int ready=0;
 for(int j=0;j<2;j++)for(int i=0;i<2;i++){
  char label[16];snprintf(label,sizeof(label),"petres%d%d",j,i);slot_t*s=&s_slots[j][i];
  if(esp_partition_register_external(NULL,offsets[j][i],sizes[j][i],label,ESP_PARTITION_TYPE_DATA,0x41,&s->partition)!=ESP_OK)continue;
  const void *map=NULL;if(esp_partition_mmap(s->partition,0,sizes[j][i],ESP_PARTITION_MMAP_DATA,&map,&s->handle)!=ESP_OK)continue;s->map=map;
  if(!s_data[j]&&pet_panel_cache_valid(s->map,sizes[j][i],&s_specs[j])){s_data[j]=s->map+PET_PANEL_HEADER;ready++;}
 }
 ESP_LOGI("pet_panel","verified cache font=%d art=%d",s_data[0]!=NULL,s_data[1]!=NULL);return ready;
#else
 const char *root=getenv("PET_PANEL_TEST_ROOT");if(!root)return 0;
 for(int j=0;j<2;j++){char path[1024];snprintf(path,sizeof(path),"%s/%s.bin",root,s_sha[j]);FILE*f=fopen(path,"rb");if(!f)continue;
  if(s_data[j]){fclose(f);continue;}
  s_host[j]=malloc(s_specs[j].bytes);if(!s_host[j]){fclose(f);continue;}size_t n=fread(s_host[j],1,s_specs[j].bytes,f);int extra=fgetc(f);fclose(f);uint8_t hash[32];pet_panel_sha256(s_host[j],n,hash);
  if(n==s_specs[j].bytes&&extra==EOF&&!memcmp(hash,s_specs[j].sha,32))s_data[j]=s_host[j];else{free(s_host[j]);s_host[j]=NULL;}}
 return !!s_data[0]+!!s_data[1];
#endif
}
void pet_panel_bind(void){
 if(s_data[0])pet_panel_font_bind(s_data[0],s_specs[0].bytes);
 if(s_data[1])pet_panel_art_bind(s_data[1],s_specs[1].bytes);
}
#ifdef ESP_PLATFORM
static uint32_t s_retry,s_sequence,s_erased,s_received;
static int s_group=-1,s_slot;
static void retry(uint32_t now){s_group=-1;s_retry=now+60000;s_erased=s_received=0;}
void pet_panel_tick(uint32_t now,bool idle){
 if(!idle||((s_retry)&&(int32_t)(now-s_retry)<0))return;
 if(s_data[0]&&s_data[1])return;
 if(s_group<0){
  s_group=s_data[0]?1:0;slot_t*a=&s_slots[s_group][0],*b=&s_slots[s_group][1];
  s_slot=pet_panel_cache_target(a->map,a->partition?a->partition->size:0,b->map,b->partition?b->partition->size:0,&s_sequence);
  if(s_slot<0||!s_slots[s_group][s_slot].partition||!s_slots[s_group][s_slot].map){retry(now);return;}
  s_erased=s_received=0;
 }
 slot_t*slot=&s_slots[s_group][s_slot];const pet_panel_spec_t *spec=&s_specs[s_group];
 if(s_erased<slot->partition->size){
  unsigned amount=slot->partition->size-s_erased;if(amount>0x10000)amount=0x10000;
  if(esp_partition_erase_range(slot->partition,s_erased,amount)!=ESP_OK){retry(now);return;}
  s_erased+=amount;return;
 }
 uint32_t generation=pet_turn_current();cJSON*r=cJSON_CreateObject();cJSON_AddStringToObject(r,"sha256",s_sha[s_group]);cJSON_AddNumberToObject(r,"offset",s_received);cJSON_AddNumberToObject(r,"bytes",16384);
 char *raw=pet_cloud_computer("resource",r);cJSON_Delete(r);cJSON*reply=raw?cJSON_Parse(raw):NULL;free(raw);
 cJSON*data=cJSON_GetObjectItem(reply,"data"),*sha=cJSON_GetObjectItem(reply,"sha256"),*offset=cJSON_GetObjectItem(reply,"offset"),*total=cJSON_GetObjectItem(reply,"total"),*crc=cJSON_GetObjectItem(reply,"crc32");
 bool ok=pet_turn_valid(generation)&&cJSON_IsTrue(cJSON_GetObjectItem(reply,"ok"))&&cJSON_IsString(sha)&&!strcmp(sha->valuestring,s_sha[s_group])&&cJSON_IsNumber(offset)&&offset->valuedouble==s_received&&cJSON_IsNumber(total)&&total->valuedouble==spec->bytes&&cJSON_IsString(data)&&strlen(data->valuestring)<=21848&&cJSON_IsNumber(crc);
 uint8_t *chunk=ok?pet_alloc(16384):NULL;size_t n=0;
 ok=ok&&chunk&&mbedtls_base64_decode(chunk,16384,&n,(const unsigned char*)data->valuestring,strlen(data->valuestring))==0&&n>0&&n==(spec->bytes-s_received>16384?16384:spec->bytes-s_received)&&crc->valuedouble==pet_crc32((const char*)chunk,n);
 if(ok)ok=esp_partition_write(slot->partition,PET_PANEL_HEADER+s_received,chunk,n)==ESP_OK;
 free(chunk);cJSON_Delete(reply);
 if(!ok){
  if(!pet_turn_valid(generation)){s_retry=now+1000;return;} /* Keep verified download progress while chatting. */
  retry(now);return;
 }
 s_received+=n;
 if(s_received==spec->bytes){
  uint8_t digest[32],header[64];pet_panel_sha256(slot->map+PET_PANEL_HEADER,spec->bytes,digest);
  if(memcmp(digest,spec->sha,32)){retry(now);return;}
  pet_panel_cache_commit(header,spec,s_sequence);
  if(esp_partition_write(slot->partition,0,header,sizeof(header))!=ESP_OK||!pet_panel_cache_valid(slot->map,slot->partition->size,spec)){retry(now);return;}
  s_data[s_group]=slot->map+PET_PANEL_HEADER;ESP_LOGI("pet_panel","resource cached kind=%d bytes=%u",s_group+1,(unsigned)spec->bytes);
  s_group=-1;pet_face_panel_refresh();
 }
}
#else
void pet_panel_tick(uint32_t now,bool idle){(void)now;(void)idle;}
#endif
#endif
