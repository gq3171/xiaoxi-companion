#include "pet_home.h"
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>

/* This fixed map describes the virtual room, never the user's physical room. */
const pet_home_spot_t pet_home_spots[PET_PLACE_COUNT] = {
    {PET_PLACE_FLOOR,"地板活动区",240,370,240,370, 110,292,240,130,430, 0,0,0,0},
    {PET_PLACE_BED,"床",155,292,122,240, 26,144,174,124,268, 36,240,156,28},
    {PET_PLACE_WASH,"洗漱台",338,358,376,348, 391,228,83,137,365, 396,286,77,73},
    {PET_PLACE_WORK,"电脑工作台",328,292,329,237, 248,115,168,124,239, 303,207,55,32},
    {PET_PLACE_WINDOW,"窗边",220,300,220,300, 15,40,182,114,200, 0,0,0,0},
};
static atomic_int s_request, s_computer;
static atomic_uint s_snapshot;
static atomic_int s_completed;
static atomic_uint s_request_serial;
unsigned pet_home_request_serial(void){return atomic_load(&s_request_serial);}
static const char *action_names[]={"","roam","rest","wake","wash","work","window","read"};
pet_home_action_t pet_home_action(const char *name)
{
    if(name)for(int i=1;i<=PET_HOME_READ;i++)if(!strcmp(name,action_names[i]))return (pet_home_action_t)i;
    return PET_HOME_NONE;
}
const char *pet_home_action_name(pet_home_action_t action)
{
    return action>PET_HOME_NONE&&action<=PET_HOME_READ?action_names[action]:"";
}

static int clamp(int n,int lo,int hi){return n<lo?lo:n>hi?hi:n;}
bool pet_home_request(pet_home_action_t action)
{
    if (action <= PET_HOME_NONE || action > PET_HOME_READ) return false;
    atomic_store(&s_request,action); atomic_fetch_add(&s_request_serial,1); return true;
}
bool pet_home_request_text(const char *action)
{
    return pet_home_request(pet_home_action(action));
}
pet_home_action_t pet_home_take_request(void){return (pet_home_action_t)atomic_exchange(&s_request,0);}
pet_computer_state_t pet_home_computer_state(void){return (pet_computer_state_t)atomic_load(&s_computer);}
void pet_home_computer_event(pet_computer_state_t state)
{
    if (state>=PET_COMPUTER_DISCONNECTED && state<=PET_COMPUTER_UNCHECKED) {
        int previous=atomic_exchange(&s_computer,state);
        if(state==PET_COMPUTER_RUNNING && previous!=PET_COMPUTER_RUNNING) pet_home_request(PET_HOME_WORK);
    }
}
void pet_home_report(pet_home_activity_t activity,pet_place_t place,pet_place_t destination,int x,int y)
{
    if (activity<PET_HOME_IDLE || activity>PET_HOME_READING || place<0 || place>=PET_PLACE_COUNT || destination<0 || destination>=PET_PLACE_COUNT) return;
    atomic_store(&s_snapshot,(unsigned)activity | (unsigned)place<<4 | (unsigned)clamp(x,0,479)<<7 | (unsigned)clamp(y,0,479)<<16 | (unsigned)destination<<25);
}
int pet_home_scale(int y){return clamp(144+(y-275)*124/150,144,268);}
void pet_home_floor_clamp(int *x,int *y)
{
    *y=clamp(*y,292,425);
    int widen=(*y-292)*55/133;
    *x=clamp(*x,145-widen,335+widen);
    int half=(208*pet_home_scale(*y)+511)/512;
    *x=clamp(*x,half+12,480-half-12);
    /* The basin occupies the upper-right floor. */
    if (*y<356 && *x>344) *x=344;
}
bool pet_home_floor_contains(int x,int y){int a=x,b=y;pet_home_floor_clamp(&a,&b);return a==x&&b==y;}
void pet_home_complete(pet_home_activity_t activity)
{
    if(activity==PET_HOME_SLEEPING || activity==PET_HOME_WAKING || activity==PET_HOME_WASHING || activity==PET_HOME_LOOKING || activity==PET_HOME_READING) {
        unsigned previous=(unsigned)atomic_load(&s_completed);
        atomic_store(&s_completed,(int)((((previous>>4)+1)&0x7fffff)<<4)|(int)activity);
    }
}
unsigned pet_home_completion(void){return (unsigned)atomic_load(&s_completed);}
pet_home_status_t pet_home_status(void)
{
    unsigned value=atomic_load(&s_snapshot);
    return (pet_home_status_t){.activity=value&15,.place=(value>>4)&7,.destination=(value>>25)&7};
}
void pet_home_description(char *out,size_t n)
{
    unsigned value=atomic_load(&s_snapshot);unsigned activity=value&15, place=(value>>4)&7, destination=(value>>25)&7;
    pet_computer_state_t computer=pet_home_computer_state();
    if(activity==PET_HOME_WORKING && computer!=PET_COMPUTER_RUNNING)activity=PET_HOME_WAIT_COMPUTER;
    const char *states[]={"在屋里休息","正在走路","正在上床","躺在床上睡觉","正在起床","正在洗漱","坐在工作台等电脑连接","正在电脑工作台工作","在窗边看看","正在走近工作台的椅子，尚未坐下","正从家具旁起身","捧着虚拟绘本读一页"};
    const char *pc[]={"尚未配置连接","已连接且空闲","真实任务执行中","最近连接检查或任务出错，需核对实际结果","已配置，连接尚未检查，不能判断断开"};
    char detail[160];const char *current=activity<=PET_HOME_READING?states[activity]:states[0];
    if(activity==PET_HOME_WALKING && destination<PET_PLACE_COUNT){snprintf(detail,sizeof(detail),"正在走向%s，还没有到达",pet_home_spots[destination].name);current=detail;}
    if(activity==PET_HOME_WAIT_COMPUTER && computer==PET_COMPUTER_READY)current="坐在工作台等下一项任务";
    if(activity==PET_HOME_WAIT_COMPUTER && computer==PET_COMPUTER_ERROR)current="坐在工作台等核对任务或连接状态";
    int completed=atomic_load(&s_completed)&15;
    const char *recent=completed==PET_HOME_SLEEPING?"一段床上休息":completed==PET_HOME_WAKING?"起床":completed==PET_HOME_WASHING?"洗漱":completed==PET_HOME_LOOKING?"在窗边看了一会儿":completed==PET_HOME_READING?"读完一页虚拟绘本":"尚无记录";
    snprintf(out,n,"屏幕内的虚拟家：左后方是床（休息、起床）；右侧是洗漱台（面盆、水壶、毛巾）；后方是电脑工作台（电脑、键盘、椅子）；中央地板可走动，窗边可看看，也可捧绘本安静读一页。当前在%s，%s。实体电脑%s。"
        "最近实际走完的虚拟生活动作：%s（仅本次开机记录，不代表现实动作或昨天的经历）。"
        "这些是虚拟生活动作，不是现实房间传感结果；电脑未连接时只能坐下等待，不能声称正在操作或已完成电脑任务。"
        "可在JSON附home_action=roam|rest|wake|wash|work|window|read请求走过去做动作；这是意图，状态更新后才代表已经到达。",
        place<PET_PLACE_COUNT?pet_home_spots[place].name:"地板活动区",current,pc[computer],recent);
}
