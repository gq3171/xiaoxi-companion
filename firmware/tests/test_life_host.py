"""Actual persistent life goals, interruption and truthful completion."""
import unittest
import test_runtime_core

class LifeHostTests(unittest.TestCase):
    def run_life(self, body):
        test_runtime_core.RuntimeCoreTests.run_c(self, r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include "pet_life.c"
static int plan(const char *json,bool replace){cJSON *p=cJSON_Parse(json);int r=pet_life_plan(p,1700000000,replace);cJSON_Delete(p);return r;}
'''+body,["pet_home","pet_util"])

    def test_goal_steps_pause_reboot_completed_journal_and_no_invented_results(self):
        self.run_life(r'''
int main(void){
 assert(pet_life_start()==0);
 assert(plan("{\"goal\":\"醒来后看看窗外\",\"reason\":\"晨间活动\",\"steps\":[\"wash\",\"window\"]}",false)==0);
 assert(pet_life_active());pet_life_tick(100,1700000000,false,false,false);
 assert(pet_home_take_request()==PET_HOME_WASH);
 pet_home_report(PET_HOME_WASHING,PET_PLACE_WASH,PET_PLACE_WASH,376,348);
 pet_life_tick(7000,1700000007,false,false,false);
 assert(integer(cJSON_GetObjectItem(s_life,"plan"),"index")==0);
 pet_home_complete(PET_HOME_WASHING);pet_life_tick(7100,1700000008,false,false,false);
 assert(integer(cJSON_GetObjectItem(s_life,"plan"),"index")==1);
 assert(pet_life_start()==0); /* Resume only the unfinished window step. */
 pet_life_tick(100,1700000010,true,false,false);assert(pet_home_take_request()==PET_HOME_NONE);
 pet_life_tick(200,1700000011,false,false,false);assert(pet_home_take_request()==PET_HOME_WINDOW);
 assert(pet_life_control("pause")==0);assert(pet_life_start()==0);
 pet_life_tick(50000,1700000050,false,false,false);assert(pet_home_take_request()==PET_HOME_NONE);
 assert(pet_life_control("resume")==0);pet_life_tick(50100,1700000051,false,false,false);
 assert(pet_home_take_request()==PET_HOME_WINDOW);pet_home_complete(PET_HOME_LOOKING);
 pet_life_tick(58000,1700000058,false,false,false);assert(!pet_life_active());
 char out[3000];pet_life_context(out,sizeof(out));assert(strstr(out,"已完成")&&strstr(out,"wash")&&strstr(out,"window"));
 assert(strstr(out,"不能作为主人事实或电脑执行结果"));
 struct stat a,b;assert(!stat(@FLASH@ "/life.0",&a)&&!stat(@FLASH@ "/life.1",&b));
 assert(a.st_size<=8192+20&&b.st_size<=8192+20);return 0;
}
''')

    def test_pause_records_current_finished_step_but_does_not_schedule_next(self):
        self.run_life(r'''
int main(void){
 assert(!pet_life_start());assert(!plan("{\"goal\":\"晨间活动\",\"steps\":[\"wash\",\"window\"]}",false));
 pet_life_tick(100,0,false,false,false);assert(pet_home_take_request()==PET_HOME_WASH);
 assert(!pet_life_control("pause"));pet_home_complete(PET_HOME_WASHING);
 pet_life_tick(7000,0,false,false,false);assert(paused()&&integer(cJSON_GetObjectItem(s_life,"plan"),"index")==1);
 pet_life_tick(8000,0,false,false,false);assert(pet_home_take_request()==PET_HOME_NONE);
 assert(!pet_life_control("resume"));pet_life_tick(9000,0,false,false,false);
 assert(pet_home_take_request()==PET_HOME_WINDOW);return 0;
}
''')

    def test_invalid_plans_overrides_night_and_rest_exclude_conversation_time(self):
        self.run_life(r'''
int main(void){
 assert(pet_life_start()==0);
 assert(plan("{\"goal\":\"虚构动作\",\"steps\":[\"run_shell\"]}",false)<0);
 assert(plan("{\"goal\":\"休息\",\"steps\":[\"rest\"]}",false)==0);
 assert(plan("{\"goal\":\"替换\",\"steps\":[\"window\"]}",false)<0);
 pet_life_tick(100,0,false,false,false);assert(pet_home_take_request()==PET_HOME_REST);
 pet_home_report(PET_HOME_SLEEPING,PET_PLACE_BED,PET_PLACE_BED,122,240);
 pet_life_tick(200,0,false,false,false);
 pet_life_tick(50200,0,true,false,false); /* Do not count a 50-second conversation as rest. */
 pet_life_tick(110199,0,false,false,false);assert(pet_life_active());
 pet_life_tick(110200,0,false,false,false);assert(!pet_life_active());
 assert(plan("{\"goal\":\"看窗外\",\"steps\":[\"window\"]}",false)==0);
 pet_life_tick(110300,0,false,true,false);assert(pet_home_take_request()==PET_HOME_REST);
 pet_life_tick(110400,0,false,true,false);assert(pet_home_take_request()==PET_HOME_NONE);
 pet_life_tick(110500,0,false,false,false);assert(pet_home_take_request()==PET_HOME_WINDOW);
 pet_home_request(PET_HOME_WASH);pet_life_tick(110600,0,false,false,false);
 assert(paused()&&pet_life_active());assert(pet_life_control("cancel")==0&&!pet_life_active());return 0;
}
''')

    def test_explicit_request_can_act_quietly_at_night_but_low_battery_takes_priority(self):
        self.run_life(r'''
int main(void){
 assert(!pet_life_start());assert(!plan("{\"goal\":\"主人安排\",\"steps\":[\"wash\"]}",true));
 pet_life_tick(100,0,false,true,false);assert(pet_home_take_request()==PET_HOME_WASH);
 pet_life_tick(200,0,false,true,true);assert(pet_home_take_request()==PET_HOME_REST);
 return 0;
}
''')

    def test_corrupt_storage_is_preserved_and_failed_save_does_not_replace_goal(self):
        self.run_life(r'''
int main(void){
 assert(pet_life_start()==0);assert(plan("{\"goal\":\"旧目标\",\"steps\":[\"wash\"]}",false)==0);
 s_writable=false;assert(plan("{\"goal\":\"新目标\",\"steps\":[\"window\"]}",true)<0);
 assert(!strcmp(text(cJSON_GetObjectItem(s_life,"plan"),"goal"),"旧目标"));
 for(int i=0;i<2;i++){char path[256];snprintf(path,sizeof(path),"%s.%d",LIFE_BASE,i);FILE*f=fopen(path,"wb");assert(f);fputs("broken",f);fclose(f);}
 assert(pet_life_start()<0);assert(plan("{\"goal\":\"重置\",\"steps\":[\"wash\"]}",true)<0);
 FILE*f=fopen(@FLASH@ "/life.0","rb");assert(f);char b[8]={0};fread(b,1,6,f);fclose(f);assert(!strcmp(b,"broken"));return 0;
}
''')

class LifeSceneHostTests(unittest.TestCase):
    def test_real_scene_completes_a_saved_two_step_goal_while_invisible(self):
        test_runtime_core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include <string.h>
#include "pet_scene.h"
#include "pet_life.h"
#include "pet_screen.h"
int main(void){
 assert(!pet_life_start());pet_scene_t scene;pet_scene_init(&scene,100);
 cJSON *p=cJSON_Parse("{\"goal\":\"晨间活动\",\"steps\":[\"wash\",\"window\"]}");
 assert(!pet_life_plan(p,0,false));cJSON_Delete(p);pet_screen_t screen={0};
 pet_screen_brightness(&screen,100,false,false,false);
 for(unsigned t=100;t<140000;t+=100){
  pet_life_tick(t,0,false,false,false);
  pet_scene_step(&scene,(pet_scene_input_t){.now_ms=t,.random=1});
  pet_screen_brightness(&screen,t,false,false,false);
 }
 assert(!pet_life_active());char context[3000];pet_life_context(context,sizeof(context));
 assert(strstr(context,"wash")&&strstr(context,"window"));
 assert(pet_screen_brightness(&screen,140000,false,false,false)==0);return 0;
}
''',["pet_life","pet_scene","pet_home","pet_screen","pet_util"])

    def test_web_handoff_does_not_replace_new_activity_or_rewrite_flash_repeatedly(self):
        LifeHostTests.run_life(self,r'''
int main(void){
 assert(!pet_life_start());assert(!plan("{\"goal\":\"读一页\",\"steps\":[\"read\"]}",false));
 pet_life_tick(100,0,false,false,false);assert(pet_home_take_request()==PET_HOME_READ);
 pet_home_report(PET_HOME_READING,PET_PLACE_WINDOW,PET_PLACE_WINDOW,220,300);
 pet_home_request(PET_HOME_REST);unsigned serial=pet_home_request_serial();
 assert(!pet_life_control("handoff"));assert(paused());assert(pet_home_request_serial()==serial);
 assert(pet_home_take_request()==PET_HOME_REST);uint32_t sequence=s_sequence;
 for(int i=0;i<10;i++)assert(!pet_life_control("handoff"));
 assert(s_sequence==sequence&&pet_home_take_request()==PET_HOME_NONE);return 0;
}
''')
