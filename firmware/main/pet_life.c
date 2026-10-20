#include "pet_life.h"
#include "pet_home.h"
#include "pet_util.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef PET_STORAGE_ROOT
#define PET_STORAGE_ROOT "/spiffs"
#endif
#define LIFE_BASE PET_STORAGE_ROOT "/life"
#define LIFE_BUDGET 8192
#define JOURNAL_LIMIT 6
static cJSON *s_life;
static uint32_t s_sequence,s_issued_serial,s_started,s_dwell,s_last_tick,s_retry_at;
static unsigned s_completed;
static bool s_writable,s_issued,s_arrived,s_wait_rest;

static const char *text(const cJSON *o,const char *key)
{
    cJSON *v=cJSON_GetObjectItemCaseSensitive(o,key);return cJSON_IsString(v)?v->valuestring:"";
}
static int integer(const cJSON *o,const char *key)
{
    cJSON *v=cJSON_GetObjectItemCaseSensitive(o,key);return cJSON_IsNumber(v)?v->valueint:0;
}
static void set(cJSON *o,const char *key,cJSON *v)
{
    if(cJSON_GetObjectItemCaseSensitive(o,key))cJSON_ReplaceItemInObjectCaseSensitive(o,key,v);
    else cJSON_AddItemToObject(o,key,v);
}
static bool valid_plan(const cJSON *p)
{
    if(!cJSON_IsObject(p)||!text(p,"goal")[0]||strlen(text(p,"goal"))>240||strlen(text(p,"reason"))>384)return false;
    cJSON *steps=cJSON_GetObjectItemCaseSensitive(p,"steps");int n=cJSON_GetArraySize(steps);
    if(!cJSON_IsArray(steps)||n<1||n>4)return false;
    for(int i=0;i<n;i++){
        cJSON *step=cJSON_GetArrayItem(steps,i);
        if(!cJSON_IsString(step)||!pet_home_action(step->valuestring))return false;
    }
    return true;
}
static int commit(cJSON *next)
{
    if(!next||!s_writable){cJSON_Delete(next);return -1;}
    char *json=cJSON_PrintUnformatted(next);
    int result=json?pet_snapshot_save(LIFE_BASE,json,LIFE_BUDGET,&s_sequence):-1;free(json);
    if(result==0){cJSON_Delete(s_life);s_life=next;}else cJSON_Delete(next);
    return result;
}
int pet_life_start(void)
{
    cJSON_Delete(s_life);s_life=NULL;s_sequence=0;s_issued=s_arrived=s_wait_rest=false;
    s_last_tick=s_retry_at=0;s_writable=true;
    char *json=pet_snapshot_load(LIFE_BASE,LIFE_BUDGET,&s_sequence);
    if(!json&&pet_snapshot_exists(LIFE_BASE))s_writable=false;
    s_life=json?cJSON_Parse(json):NULL;free(json);
    if(s_life){
        cJSON *plan=cJSON_GetObjectItemCaseSensitive(s_life,"plan");
        if(!cJSON_IsObject(s_life)||integer(s_life,"schema")!=1||
           !cJSON_IsArray(cJSON_GetObjectItemCaseSensitive(s_life,"journal"))||
           cJSON_GetArraySize(cJSON_GetObjectItemCaseSensitive(s_life,"journal"))>JOURNAL_LIMIT||
           (plan&&(!valid_plan(plan)||integer(plan,"index")<0||integer(plan,"index")>cJSON_GetArraySize(cJSON_GetObjectItemCaseSensitive(plan,"steps"))))){
            s_writable=false;cJSON_Delete(s_life);s_life=NULL;
        }
    }
    if(!s_life){s_life=cJSON_CreateObject();cJSON_AddNumberToObject(s_life,"schema",1);cJSON_AddArrayToObject(s_life,"journal");}
    return s_writable?0:-1;
}
bool pet_life_active(void)
{
    cJSON *p=cJSON_GetObjectItemCaseSensitive(s_life,"plan");
    return valid_plan(p)&&integer(p,"index")<cJSON_GetArraySize(cJSON_GetObjectItemCaseSensitive(p,"steps"));
}
int pet_life_plan(const cJSON *p,int64_t epoch,bool replace)
{
    if(!s_life||!s_writable||!valid_plan(p)||(!replace&&pet_life_active()))return -1;
    cJSON *next=cJSON_Duplicate(s_life,true),*plan=cJSON_CreateObject();
    if(!next||!plan){cJSON_Delete(next);cJSON_Delete(plan);return -1;}
    cJSON_AddStringToObject(plan,"goal",text(p,"goal"));cJSON_AddStringToObject(plan,"reason",text(p,"reason"));
    cJSON_AddItemToObject(plan,"steps",cJSON_Duplicate(cJSON_GetObjectItemCaseSensitive(p,"steps"),true));
    cJSON_AddNumberToObject(plan,"index",0);cJSON_AddNumberToObject(plan,"created",epoch);
    cJSON_AddBoolToObject(plan,"by_owner",replace);
    cJSON_AddBoolToObject(plan,"paused",false);set(next,"plan",plan);
    if(!valid_plan(plan)){cJSON_Delete(next);return -1;}
    int result=commit(next);if(!result){s_issued=s_arrived=s_wait_rest=false;s_retry_at=0;}return result;
}
static pet_home_action_t step_action(void);
int pet_life_control(const char *control)
{
    if(!control||!pet_life_active())return -1;
    bool handoff=!strcmp(control,"handoff");
    bool cancel=!strcmp(control,"cancel"),pause=!strcmp(control,"pause")||handoff,resume=!strcmp(control,"resume");
    if(handoff&&cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(cJSON_GetObjectItemCaseSensitive(s_life,"plan"),"paused")))return 0;
    if(!cancel&&!pause&&!resume)return -1;
    bool stop_read=!handoff&&(pause||cancel)&&s_issued&&step_action()==PET_HOME_READ;
    cJSON *next=cJSON_Duplicate(s_life,true);if(!next)return -1;
    if(cancel)cJSON_DeleteItemFromObjectCaseSensitive(next,"plan");
    else {
        cJSON *p=cJSON_GetObjectItemCaseSensitive(next,"plan");
        set(p,"paused",cJSON_CreateBool(pause));
        if(resume)set(p,"by_owner",cJSON_CreateBool(true));
    }
    int result=commit(next);
    /* A pause stops scheduling the next step; an already performed transition
     * may finish and must still be recorded, rather than repeated on resume. */
    if(!result&&stop_read)pet_home_request(PET_HOME_ROAM);
    if(!result&&(!pause||stop_read))s_issued=s_arrived=s_wait_rest=false;
    return result;
}
static bool paused(void)
{
    return cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(cJSON_GetObjectItemCaseSensitive(s_life,"plan"),"paused"));
}
static pet_home_action_t step_action(void)
{
    cJSON *p=cJSON_GetObjectItemCaseSensitive(s_life,"plan");
    cJSON *step=cJSON_GetArrayItem(cJSON_GetObjectItemCaseSensitive(p,"steps"),integer(p,"index"));
    return cJSON_IsString(step)?pet_home_action(step->valuestring):PET_HOME_NONE;
}
static int complete_step(int64_t epoch)
{
    cJSON *next=cJSON_Duplicate(s_life,true);if(!next)return -1;
    cJSON *p=cJSON_GetObjectItemCaseSensitive(next,"plan"),*journal=cJSON_GetObjectItemCaseSensitive(next,"journal");
    cJSON *event=cJSON_CreateObject();
    cJSON_AddStringToObject(event,"goal",text(p,"goal"));cJSON_AddStringToObject(event,"step",pet_home_action_name(step_action()));
    cJSON_AddNumberToObject(event,"epoch",epoch);cJSON_AddBoolToObject(event,"virtual",true);
    cJSON_AddItemToArray(journal,event);while(cJSON_GetArraySize(journal)>JOURNAL_LIMIT)cJSON_DeleteItemFromArray(journal,0);
    set(p,"index",cJSON_CreateNumber(integer(p,"index")+1));
    int result=commit(next);if(!result)s_issued=s_arrived=false;return result;
}
void pet_life_tick(uint32_t now,int64_t epoch,bool engaged,bool night,bool tired)
{
    uint32_t dt=s_last_tick?now-s_last_tick:0;s_last_tick=now;
    if(!s_writable||!pet_life_active())return;
    bool is_paused=paused();
    if(is_paused&&!s_issued)return;
    if(s_retry_at&&(int32_t)(now-s_retry_at)<0)return;
    if(engaged){if(s_issued)s_started+=dt;if(s_arrived)s_dwell+=dt;return;}
    pet_home_action_t action=step_action();
    bool requested=cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(cJSON_GetObjectItemCaseSensitive(s_life,"plan"),"by_owner"));
    if(!is_paused&&((night&&!requested)||tired)&&action!=PET_HOME_REST){
        /* Leave the saved goal pending while the local character rests. */
        if(!s_wait_rest){pet_home_request(PET_HOME_REST);s_wait_rest=true;s_issued=false;s_arrived=false;}
        return;
    }
    s_wait_rest=false;
    if(!s_issued){
        pet_home_request(action);s_issued_serial=pet_home_request_serial();s_completed=pet_home_completion();
        s_issued=true;s_arrived=false;s_started=now;s_dwell=0;return;
    }
    if(pet_home_request_serial()!=s_issued_serial){
        /* A touch/menu/direct command wins. Keep the old goal paused on flash. */
        if(pet_life_control("pause")!=0)s_retry_at=now+30000;
        else s_issued=s_arrived=false;
        return;
    }
    bool done=false;unsigned completion=pet_home_completion();
    if(completion!=s_completed){
        int event=completion&15;
        done=((action==PET_HOME_WASH||action==PET_HOME_WAKE)&&event==PET_HOME_WASHING)||
            (action==PET_HOME_WINDOW&&event==PET_HOME_LOOKING)||
            (action==PET_HOME_READ&&event==PET_HOME_READING);
    }
    pet_home_status_t home=pet_home_status();
    bool arrived=(action==PET_HOME_REST&&home.activity==PET_HOME_SLEEPING)||
        (action==PET_HOME_ROAM&&home.place==PET_PLACE_FLOOR&&home.activity==PET_HOME_IDLE)||
        (action==PET_HOME_WORK&&home.place==PET_PLACE_WORK&&home.activity==PET_HOME_WAIT_COMPUTER);
    if(arrived){if(!s_arrived){s_arrived=true;s_dwell=now;}else{
        unsigned dwell=action==PET_HOME_REST?60000:action==PET_HOME_WORK?10000:2000;
        done=now-s_dwell>=dwell;
    }}else s_arrived=false;
    if(done){if(complete_step(epoch)!=0)s_retry_at=now+30000;return;}
    if(!is_paused&&now-s_started>180000){
        /* No result is not success; pause instead of repeatedly issuing a goal. */
        if(pet_life_control("pause")!=0)s_retry_at=now+30000;
        else s_issued=s_arrived=false;
    }
}
void pet_life_context(char *out,size_t n)
{
    if(!n)return;
    out[0]=0;
    if(!s_life)return;
    cJSON *p=cJSON_GetObjectItemCaseSensitive(s_life,"plan");
    int count=snprintf(out,n,"连续生活（屏幕内的虚拟活动，不能作为主人事实或电脑执行结果）：");
    size_t used=count>0&&(size_t)count<n?(size_t)count:strlen(out);
    if(p){
        count=snprintf(out+used,n-used,"目标=%s；原因=%s；进度=%d/%d；状态=%s；当前步骤=%s。重启只恢复未完成步骤，不假装关机期间完成过。",
            text(p,"goal"),text(p,"reason"),integer(p,"index"),cJSON_GetArraySize(cJSON_GetObjectItemCaseSensitive(p,"steps")),
            !pet_life_active()?"已完成":paused()?"暂停，等待调整或继续":s_wait_rest?"先休息，之后继续":"待执行或执行中",pet_home_action_name(step_action()));
        used+=count>0&&(size_t)count<n-used?(size_t)count:strlen(out+used);
    }
    cJSON *journal=cJSON_GetObjectItemCaseSensitive(s_life,"journal"),*event;
    cJSON_ArrayForEach(event,journal){
        if(used+128>=n)break;
        count=snprintf(out+used,n-used,"\n已实际完成：%s/%s，时间戳=%.0f（0未知）。",text(event,"goal"),text(event,"step"),cJSON_GetNumberValue(cJSON_GetObjectItemCaseSensitive(event,"epoch")));
        used+=count>0&&(size_t)count<n-used?(size_t)count:strlen(out+used);
    }
    if(!s_writable&&used<n)snprintf(out+used,n-used,"生活存储不可写，旧记录保留，不能声称保存了新计划。");
}
const char *pet_life_rules(void)
{
    return "\n可以附life_plan={\"goal\":\"简洁的虚拟生活目标\",\"reason\":\"结合当前状态的原因\",\"steps\":[\"wash\",\"window\"]}，1至4步，仅roam/rest/wake/wash/work/window/read。"
        "只规划屏幕房间支持的动作；read是拿虚拟绘本在窗边读一页，不等于读过真实资料或获得现实知识。其他不存在的物品操作不能虚构。work只表示到工作台坐一会儿，不代表实体电脑任务。"
        "普通问答不必创建计划。已有未完成目标时优先接续，不每轮另起目标。主人明确要改做别的可替换；暂停/继续/取消可附life_control=pause/resume/cancel。"
        "主人说忙或想安静时可安静生活；夜间自主活动先休息，主人明确请求可安静完成，低电量先休息。不能在动作完成前说已完成，计划和已完成记录要区分。";
}
