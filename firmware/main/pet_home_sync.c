#include "pet_home_sync.h"
#ifdef CONFIG_DESKPET_HOME_SYNC
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "cJSON.h"
#include "pet_util.h"
#include "pet_setup.h"
#include "pet_hardware.h"
#include "pet_wake_gate.h"
#include "pet_store.h"
#include "pet_brain.h"
#include "pet_runtime.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_random.h"
#include "esp_heap_caps.h"
#include "esp_http_client.h"
#include "esp_crt_bundle.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <math.h>
static portMUX_TYPE mux=portMUX_INITIALIZER_UNLOCKED;
#define LOCK() portENTER_CRITICAL(&mux)
#define UNLOCK() portEXIT_CRITICAL(&mux)
typedef struct {char action[8],id[33];int x,y;uint32_t at;} event_t;
static struct {
 int32_t wire[PET_SCENE_WIRE_WORDS],seed[PET_SCENE_WIRE_WORDS];
 uint32_t received,remote,frame,seed_ms,rtt,completion;double revision;
 char epoch[33],phase[97],caption[1801];unsigned flags;
 bool have,initialized;event_t events[8];unsigned count,nonce;
 unsigned pair_request,pair_done;char pair_code[9];
 pet_home_world_t world;unsigned world_request,world_done;bool world_ok;char world_action[8],world_id[33];
 int reminder_id,reminder_state;char reminder_lease[33],reminder_text[241];uint32_t reminder_retry,reminder_checked;
} shared;
static StaticTask_t task_buffer;
static uint32_t now_ms(void){return (uint32_t)(esp_timer_get_time()/1000);}
static bool active(uint32_t now){return shared.have&&(uint32_t)(now-shared.received)<3000;}
#define REMINDER_ACK_BASE "/spiffs/remote-reminder-ack"
static uint32_t reminder_ack_sequence;
bool pet_home_sync_take_reminder(char*out,size_t capacity)
{
    bool ready=false;LOCK();
    if(shared.reminder_state==1&&(uint32_t)(now_ms()-shared.reminder_checked)<2000&&(int32_t)(now_ms()-shared.reminder_retry)>=0){pet_utf8_copy(out,capacity,shared.reminder_text);shared.reminder_state=2;ready=true;}
    UNLOCK();return ready;
}
void pet_home_sync_finish_reminder(bool played)
{
    char saved[128]={0};LOCK();
    if(shared.reminder_state==2){
        if(played){shared.reminder_state=3;snprintf(saved,sizeof(saved),"{\"id\":%d,\"lease\":\"%s\"}",shared.reminder_id,shared.reminder_lease);}
        else {shared.reminder_state=1;shared.reminder_retry=now_ms()+30000;}
    }
    UNLOCK();
    if(saved[0])pet_snapshot_save(REMINDER_ACK_BASE,saved,sizeof(saved),&reminder_ack_sequence);
}
void pet_home_sync_world(pet_home_world_t*out){if(!out)return;LOCK();*out=shared.world;uint32_t now=now_ms();out->online=active(now);pet_home_cat_motion(out,now-shared.received);UNLOCK();}
int pet_home_sync_world_request(const char*action){
 if(!action||(strcmp(action,"yard")&&strcmp(action,"home")&&strcmp(action,"catpet")&&strcmp(action,"catfeed")))return -1;
 LOCK();if(!active(now_ms())||shared.world_request!=shared.world_done){UNLOCK();return -1;}
 unsigned ticket=++shared.world_request;snprintf(shared.world_action,sizeof(shared.world_action),"%s",action);snprintf(shared.world_id,sizeof(shared.world_id),"%08x%08x%08x%08x",(unsigned)esp_random(),(unsigned)esp_random(),(unsigned)now_ms(),ticket);UNLOCK();
 uint32_t start=now_ms();while(now_ms()-start<5000){LOCK();bool done=shared.world_done==ticket,ok=shared.world_ok;UNLOCK();if(done)return ok?0:-1;vTaskDelay(pdMS_TO_TICKS(50));}return -1;
}
void pet_home_sync_event(const char*action,int x,int y,uint32_t now){
 if(!action||strlen(action)>7)return;
 LOCK();
 if(active(now)&&shared.count<8){event_t*e=&shared.events[shared.count++];snprintf(e->action,sizeof(e->action),"%s",action);e->x=x;e->y=y;e->at=now;
  unsigned n=++shared.nonce;snprintf(e->id,sizeof(e->id),"%08x%08x%08x%08x",(unsigned)shared.seed_ms,(unsigned)esp_random(),(unsigned)esp_random(),n);}
 UNLOCK();
}
bool pet_home_sync_step(pet_scene_t*s,pet_scene_input_t in,const char*phase,const char*caption){
 int32_t wire[PET_SCENE_WIRE_WORDS];uint32_t received=0,remote=0,frame=0,rtt=0,completion=0;bool online;
 LOCK();
 online=active(in.now_ms);pet_scene_export(s,shared.seed);shared.seed_ms=in.now_ms;shared.initialized=true;
 shared.flags=(in.listening?1:0)|(in.speaking?2:0)|(in.thinking?4:0)|(in.night?16:0)|(in.tired?32:0);
 pet_utf8_copy(shared.phase,sizeof(shared.phase),phase?phase:"");pet_utf8_copy(shared.caption,sizeof(shared.caption),caption?caption:"");
 if(online&&shared.count==0&&!s->pressed){memcpy(wire,shared.wire,sizeof(wire));received=shared.received;remote=shared.remote;frame=shared.frame;rtt=shared.rtt;completion=shared.completion;}
 UNLOCK();
 if(!online)return false;
 static int32_t phase_offset;static uint32_t applied_received,last_completion;static bool completion_seen; /* Network epoch/frame can restart; receive time is local. */
 if(received&&received!=applied_received){
  if(pet_scene_import(s,wire,PET_SCENE_WIRE_WORDS,received-rtt/2,remote)){applied_received=received;phase_offset=(int32_t)(remote-(received-rtt/2));
   if(completion_seen&&completion!=last_completion)pet_home_complete((pet_home_activity_t)(completion&15));
   last_completion=completion;completion_seen=true;
  }
 }
 (void)frame;
 s->replica=true;
 pet_home_action_t action=pet_home_take_request();
 if(action!=PET_HOME_NONE){pet_home_sync_event(pet_home_action_name(action),0,0,in.now_ms);pet_scene_command(s,action,in.now_ms);s->last_step=in.now_ms;}
 in.replica=true;in.phase_valid=true;in.phase_ms=in.now_ms+phase_offset;pet_scene_predict(s,in);return true;
}
typedef struct {char *data;size_t used;} response_t;
static esp_err_t receive(esp_http_client_event_t*e){
 response_t*r=e->user_data;
 if(e->event_id==HTTP_EVENT_ON_DATA){if(e->data_len<0||r->used+(size_t)e->data_len>=8192)return ESP_FAIL;memcpy(r->data+r->used,e->data,e->data_len);r->used+=e->data_len;r->data[r->used]=0;}
 return ESP_OK;
}
#ifdef PET_COMPUTER_CUSTOM_CA
extern const char pet_computer_ca[] asm("_binary_pet_computer_ca_start");
#endif
static cJSON *request(esp_http_client_handle_t *client,const char*operation,cJSON*body){
 char url[384],authorization[224];snprintf(url,sizeof(url),"%s/v1/home/%s",CONFIG_DESKPET_COMPUTER_URL,operation);
 if(!*client){
  esp_http_client_config_t config={.url=url,.timeout_ms=1200,.buffer_size=1024,.buffer_size_tx=1024,.event_handler=receive,.crt_bundle_attach=esp_crt_bundle_attach,.keep_alive_enable=true};
#ifdef PET_COMPUTER_CUSTOM_CA
  config.crt_bundle_attach=NULL;config.cert_pem=pet_computer_ca;
#endif
  *client=esp_http_client_init(&config);if(!*client)return NULL;
 }
 response_t response={.data=pet_alloc(8192)};char*raw=cJSON_PrintUnformatted(body);cJSON*reply=NULL;
 if(!response.data||!raw)goto done;
 response.data[0]=0;esp_http_client_set_url(*client,url);esp_http_client_set_method(*client,HTTP_METHOD_POST);esp_http_client_set_user_data(*client,&response);
 snprintf(authorization,sizeof(authorization),"Bearer %s",CONFIG_DESKPET_COMPUTER_TOKEN);
 esp_http_client_set_header(*client,"Authorization",authorization);esp_http_client_set_header(*client,"Content-Type","application/json");
 esp_http_client_set_post_field(*client,raw,strlen(raw));
 if(esp_http_client_perform(*client)==ESP_OK&&esp_http_client_get_status_code(*client)==200&&esp_http_client_is_complete_data_received(*client))reply=cJSON_Parse(response.data);
 if(!reply){esp_http_client_cleanup(*client);*client=NULL;}
 done:free(response.data);free(raw);return reply;
}
static bool number(const cJSON*j,double lo,double hi){return cJSON_IsNumber(j)&&isfinite(j->valuedouble)&&j->valuedouble>=lo&&j->valuedouble<=hi&&floor(j->valuedouble)==j->valuedouble;}
static bool accept_snapshot(cJSON*r,uint32_t started,const event_t *sent){
 cJSON *wire=cJSON_GetObjectItem(r,"wire"),*epoch=cJSON_GetObjectItem(r,"epoch"),*remote=cJSON_GetObjectItem(r,"server_ms"),*revision=cJSON_GetObjectItem(r,"revision"),*frame=cJSON_GetObjectItem(r,"frame");
 if(!cJSON_IsTrue(cJSON_GetObjectItem(r,"ok"))||!cJSON_IsString(epoch)||strlen(epoch->valuestring)!=32||cJSON_GetArraySize(wire)!=PET_SCENE_WIRE_WORDS||!number(remote,0,UINT32_MAX)||!number(revision,0,9007199254740991.)||!number(frame,0,UINT32_MAX))return false;
 int32_t words[PET_SCENE_WIRE_WORDS];for(int i=0;i<PET_SCENE_WIRE_WORDS;i++){cJSON*n=cJSON_GetArrayItem(wire,i);if(!number(n,INT32_MIN,INT32_MAX))return false;words[i]=(int32_t)n->valuedouble;}
 pet_scene_t test;if(!pet_scene_import(&test,words,PET_SCENE_WIRE_WORDS,now_ms(),(uint32_t)remote->valuedouble))return false;
 cJSON*ack=cJSON_GetObjectItem(r,"ack"),*id=cJSON_GetObjectItem(ack,"id");
 static double web_seen;static bool web_known;
 cJSON*web=cJSON_GetObjectItem(r,"web_revision");double web_revision=number(web,0,9007199254740991.)?web->valuedouble:0;
 LOCK();bool changed=shared.have&&strcmp(shared.epoch,epoch->valuestring);
 bool web_changed=web_known&&!changed&&web_revision>web_seen;web_seen=web_revision;web_known=true;
 if(changed||web_changed)shared.count=0;
 if(sent&&cJSON_IsString(id)&&!strcmp(id->valuestring,sent->id)&&shared.count&&!strcmp(shared.events[0].id,sent->id)){
  memmove(shared.events,shared.events+1,(--shared.count)*sizeof(event_t));
 }
 memcpy(shared.wire,words,sizeof(words));snprintf(shared.epoch,sizeof(shared.epoch),"%s",epoch->valuestring);shared.revision=revision->valuedouble;shared.frame=(uint32_t)frame->valuedouble;shared.remote=(uint32_t)remote->valuedouble;
 cJSON*complete=cJSON_GetObjectItem(r,"completion");shared.completion=number(complete,0,UINT32_MAX)?(uint32_t)complete->valuedouble:0;
 if(cJSON_IsTrue(cJSON_GetObjectItem(r,"reminder_ack_processed"))&&shared.reminder_state==3)shared.reminder_state=0;
 cJSON*valid=cJSON_GetObjectItem(r,"reminder_current_valid");
 if(shared.reminder_state==1&&cJSON_IsBool(valid)){if(cJSON_IsTrue(valid))shared.reminder_checked=now_ms();else shared.reminder_state=0;}
 cJSON*notice=cJSON_GetObjectItem(r,"reminder"),*notice_id=cJSON_GetObjectItem(notice,"id"),*notice_lease=cJSON_GetObjectItem(notice,"lease"),*notice_text=cJSON_GetObjectItem(notice,"text");
 if(number(notice_id,1,INT32_MAX)&&cJSON_IsString(notice_lease)&&strlen(notice_lease->valuestring)==32&&cJSON_IsString(notice_text)&&strlen(notice_text->valuestring)<=240&&shared.reminder_state==0){
  shared.reminder_id=(int)notice_id->valuedouble;snprintf(shared.reminder_lease,sizeof(shared.reminder_lease),"%s",notice_lease->valuestring);snprintf(shared.reminder_text,sizeof(shared.reminder_text),"%s",notice_text->valuestring);shared.reminder_state=1;shared.reminder_retry=now_ms();shared.reminder_checked=now_ms();
 }
 cJSON*world=cJSON_GetObjectItem(r,"world"),*loc=cJSON_GetObjectItem(world,"location"),*cat=cJSON_GetObjectItem(world,"cat");
 cJSON*cx=cJSON_GetObjectItem(cat,"x"),*cy=cJSON_GetObjectItem(cat,"y"),*cf=cJSON_GetObjectItem(cat,"art_frame"),*face=cJSON_GetObjectItem(cat,"face"),*mode=cJSON_GetObjectItem(cat,"mode"),*hunger=cJSON_GetObjectItem(cat,"hunger"),*aff=cJSON_GetObjectItem(cat,"affection"),*cat_phase=cJSON_GetObjectItem(cat,"phase_ms"),*walk_rate=cJSON_GetObjectItem(cat,"walk_rate");
 if(cJSON_IsString(loc)&&(!strcmp(loc->valuestring,"home")||!strcmp(loc->valuestring,"yard"))&&number(cx,0,479)&&number(cy,0,479)&&number(cf,PET_ART_CAT_IDLE,PET_ART_CAT_TURN)&&number(face,-1,1)&&face->valueint!=0&&number(mode,0,11)&&number(hunger,0,100)&&number(aff,0,100)){
  shared.world=(pet_home_world_t){.valid=true,.online=true,.location=!strcmp(loc->valuestring,"yard"),.cat_x=cx->valueint,.cat_y=cy->valueint,.cat_frame=cf->valueint,.cat_face=face->valueint,.cat_mode=mode->valueint,.cat_hunger=hunger->valueint,.cat_affection=aff->valueint,.cat_phase_ms=number(cat_phase,0,59999)?cat_phase->valueint:0,.cat_walk_rate=number(walk_rate,0,1000)?walk_rate->valueint:-1};
 }
 shared.received=now_ms();shared.rtt=shared.received-started;if(shared.rtt>1500)shared.rtt=1500;bool was=shared.have;shared.have=true;UNLOCK();
 if(web_changed)pet_runtime_notify("网页调整了房间活动");
 if(!was||changed)ESP_LOGI("pet_home_sync","shared room connected revision=%.0f",revision->valuedouble);
 return true;
}
static void worker(void*arg){
 esp_http_client_handle_t client=NULL;uint32_t seq=0;
 while(true){
  vTaskDelay(pdMS_TO_TICKS(100));if(!pet_setup_connected())continue;
  cJSON*envelope=pet_brain_envelope();cJSON*boot=cJSON_GetObjectItem(envelope,"boot");double boot_number=cJSON_IsNumber(boot)?boot->valuedouble:0;cJSON_Delete(envelope);if(boot_number<1)continue;
  int32_t seed[PET_SCENE_WIRE_WORDS];char phase[97],caption[1801],epoch[33];unsigned flags,pair;uint32_t seed_ms;double revision;event_t event={0};
  LOCK();bool initialized=shared.initialized;memcpy(seed,shared.seed,sizeof(seed));seed_ms=shared.seed_ms;flags=shared.flags;memcpy(phase,shared.phase,sizeof(phase));memcpy(caption,shared.caption,sizeof(caption));memcpy(epoch,shared.epoch,sizeof(epoch));revision=shared.revision;pair=shared.pair_request!=shared.pair_done?shared.pair_request:0;
  while(shared.count&&now_ms()-shared.events[0].at>2500){memmove(shared.events,shared.events+1,(--shared.count)*sizeof(event_t));}
  if(shared.count)event=shared.events[0];
  UNLOCK();if(!initialized)continue;
  cJSON*r=cJSON_CreateObject();
  if(pair){
   cJSON*reply=request(&client,"pair",r);cJSON*code=cJSON_GetObjectItem(reply,"code");
   LOCK();shared.pair_code[0]=0;if(cJSON_IsString(code)&&strlen(code->valuestring)==8)snprintf(shared.pair_code,sizeof(shared.pair_code),"%s",code->valuestring);shared.pair_done=pair;UNLOCK();cJSON_Delete(reply);cJSON_Delete(r);continue;
  }
  unsigned world_ticket;char world_action[8],world_id[33];LOCK();world_ticket=shared.world_request!=shared.world_done?shared.world_request:0;memcpy(world_action,shared.world_action,sizeof(world_action));memcpy(world_id,shared.world_id,sizeof(world_id));UNLOCK();
  if(world_ticket){
   cJSON_AddStringToObject(r,"action",world_action);cJSON_AddStringToObject(r,"id",world_id);cJSON*answer=request(&client,"world",r);bool ok=cJSON_IsTrue(cJSON_GetObjectItem(answer,"ok"))&&cJSON_IsTrue(cJSON_GetObjectItem(answer,"accepted"));
   LOCK();shared.world_ok=ok;shared.world_done=world_ticket;UNLOCK();cJSON_Delete(answer);cJSON_Delete(r);continue;
  }
  cJSON_AddNumberToObject(r,"boot",boot_number);cJSON_AddNumberToObject(r,"seq",++seq);cJSON_AddNumberToObject(r,"seed_ms",seed_ms);
  cJSON*array=cJSON_AddArrayToObject(r,"seed");for(int i=0;i<PET_SCENE_WIRE_WORDS;i++)cJSON_AddItemToArray(array,cJSON_CreateNumber(seed[i]));
  cJSON*b=cJSON_AddObjectToObject(r,"body");const char*keys[]={"listening","speaking","thinking","blocked","resting","tired"};for(int i=0;i<6;i++)cJSON_AddBoolToObject(b,keys[i],flags&(1<<i));cJSON_AddNumberToObject(b,"computer",pet_home_computer_state());
  bool ready=pet_runtime_reminder_ready();int reminder_id=0,reminder_current=0;char reminder_lease[33]={0};
  LOCK();if(shared.reminder_state==1){reminder_current=shared.reminder_id;memcpy(reminder_lease,shared.reminder_lease,sizeof(reminder_lease));}if(shared.reminder_state==3){reminder_id=shared.reminder_id;memcpy(reminder_lease,shared.reminder_lease,sizeof(reminder_lease));}if(shared.reminder_state==2||(shared.reminder_state==1&&(int32_t)(now_ms()-shared.reminder_retry)<0))ready=false;UNLOCK();
  cJSON_AddBoolToObject(b,"reminder_ready",ready);
  if(reminder_current){cJSON*a=cJSON_AddObjectToObject(r,"reminder_current");cJSON_AddNumberToObject(a,"id",reminder_current);cJSON_AddStringToObject(a,"lease",reminder_lease);}
  if(reminder_id){cJSON*a=cJSON_AddObjectToObject(r,"reminder_ack");cJSON_AddNumberToObject(a,"id",reminder_id);cJSON_AddStringToObject(a,"lease",reminder_lease);cJSON_AddStringToObject(a,"delivery","played");}
  char name[96];pet_store_name(name,sizeof(name));cJSON_AddStringToObject(r,"name",name);cJSON_AddStringToObject(r,"phase",phase);cJSON_AddStringToObject(r,"caption",caption);
  if(event.id[0]){cJSON*e=cJSON_AddObjectToObject(r,"event");cJSON_AddStringToObject(e,"id",event.id);cJSON_AddStringToObject(e,"epoch",epoch);cJSON_AddNumberToObject(e,"revision",revision);cJSON_AddStringToObject(e,"action",event.action);cJSON_AddNumberToObject(e,"x",event.x);cJSON_AddNumberToObject(e,"y",event.y);}
  uint32_t started=now_ms();cJSON*reply=request(&client,"poll",r);bool ok=reply&&accept_snapshot(reply,started,event.id[0]?&event:NULL);cJSON_Delete(reply);cJSON_Delete(r);
  if(!ok){vTaskDelay(pdMS_TO_TICKS(1000));continue;}
  if(!pet_hardware_state().usb_power)vTaskDelay(pdMS_TO_TICKS(500));
 }
}
void pet_home_sync_start(void){
 char*saved=pet_snapshot_load(REMINDER_ACK_BASE,128,&reminder_ack_sequence);cJSON*previous=saved?cJSON_Parse(saved):NULL;free(saved);
 cJSON*identifier=cJSON_GetObjectItem(previous,"id"),*lease=cJSON_GetObjectItem(previous,"lease");
 if(number(identifier,1,INT32_MAX)&&cJSON_IsString(lease)&&strlen(lease->valuestring)==32){shared.reminder_id=(int)identifier->valuedouble;snprintf(shared.reminder_lease,sizeof(shared.reminder_lease),"%s",lease->valuestring);shared.reminder_state=3;}
 cJSON_Delete(previous);

 if(!CONFIG_DESKPET_COMPUTER_URL[0])return;
 StackType_t*stack=heap_caps_malloc(12288,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 if(!stack)return;
 TaskHandle_t task=xTaskCreateStatic(worker,"home_sync",12288,NULL,2,stack,&task_buffer);
 if(!task){free(stack);return;}ESP_LOGI("pet_home_sync","shared room worker started");
}
int pet_home_sync_pair_code(char*out,size_t capacity){
 if(!out||capacity<9)return -1;
 out[0]=0;
 unsigned ticket;LOCK();ticket=++shared.pair_request;UNLOCK();uint32_t started=now_ms();
 while(now_ms()-started<4000){LOCK();bool done=shared.pair_done==ticket;char code[9];memcpy(code,shared.pair_code,sizeof(code));UNLOCK();
  if(done){if(strlen(code)!=8)return -1;for(int i=0;i<8;i++)if(code[i]<'0'||code[i]>'9')return -1;snprintf(out,capacity,"%s",code);return 0;}
  vTaskDelay(pdMS_TO_TICKS(50));
 }
 return -1;
}
int pet_home_sync_pair(char*out,size_t capacity){
 char code[9];if(pet_home_sync_pair_code(code,sizeof(code)))return -1;
 snprintf(out,capacity,"在电脑浏览器打开：\n%s/home/\n\n配对码：%s\n\n3 分钟内有效，仅能使用一次。\n输入后，网页和小板子会同步同一个家。",CONFIG_DESKPET_COMPUTER_URL,code);return 0;
}
#endif
