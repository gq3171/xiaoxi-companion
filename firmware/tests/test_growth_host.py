"""Evidence-grounded growth and lessons in the real bounded memory store."""
import unittest
import test_runtime_core

class GrowthHostTests(unittest.TestCase):
    def test_repeated_interests_correction_outcomes_and_no_fabricated_sources(self):
        code=r'''
#include "pet_memory.c"
#include <assert.h>
#include <sys/stat.h>
static const char *slot_name="topic";
static int update(const char *kind,const char *basis,const char *text,int id){
 cJSON *r=cJSON_CreateObject();cJSON_AddArrayToObject(r,"ops");
 cJSON *g=cJSON_AddArrayToObject(r,"growth_ops"),*o=cJSON_CreateObject();cJSON_AddItemToArray(g,o);
 cJSON_AddStringToObject(o,"op","upsert");cJSON_AddStringToObject(o,"kind",kind);
 cJSON_AddStringToObject(o,"slot",slot_name);cJSON_AddStringToObject(o,"basis",basis);
 cJSON_AddStringToObject(o,"text",text);cJSON_AddStringToObject(o,"trigger","相关话题时");
 cJSON_AddStringToObject(o,"check","看主人是否愿意继续");
 cJSON *ids=cJSON_AddArrayToObject(o,"source_ids");cJSON_AddItemToArray(ids,cJSON_CreateNumber(id));
 char *t=cJSON_PrintUnformatted(r);cJSON_Delete(r);int result=pet_memory_apply_reflection(t);free(t);return result;
}
int main(void){
 assert(pet_memory_start()==0);
 int id=pet_memory_add("user","我们再聊聊星星吧",true);
 assert(update("interest","recurring","我对星空有些好奇",99999)==0);
 assert(cJSON_GetArraySize(array("growth"))==0);
 id=pet_memory_add("user","我们再聊聊星星吧",true);
 assert(update("interest","recurring","我对星空有些好奇",id)==1);
 assert(number(cJSON_GetArrayItem(array("growth"),0),"active",0)==0);
 id=pet_memory_add("user","今天还想聊星星",true);
 assert(update("interest","recurring","我对星空有些好奇",id)==1);
 assert(number(cJSON_GetArrayItem(array("growth"),0),"active",0)==1);
 id=pet_memory_add("user","今天聊下音乐",true);
 assert(update("interest","recurring","我喜欢音乐",id)==1);
 assert(number(cJSON_GetArrayItem(array("growth"),0),"active",0)==0); /* changed meaning needs new support */
 id=pet_memory_add("assistant","主人一定喜欢咖啡",false);
 assert(update("style","correction","不随意猜测",id)==0);
 id=pet_memory_add("user","不要每句话都追问",true);
 assert(update("style","correction","回答后适时留白",id)==1);
 id=pet_memory_observe("failure","提醒写入失败，不能声称保存成功");assert(id>0 && pet_memory_needs_reflection());
 assert(update("interest","recurring","我喜欢故障",id)==0);
 id=pet_memory_observe("failure","提醒写入失败，不能声称保存成功");
 assert(update("lesson","outcome","确认写入成功后再告诉主人已完成",id)==1);
 assert(pet_memory_start()==0);char context[5000];pet_memory_context("提醒",context,sizeof(context));
 assert(strstr(context,"我的成长") && strstr(context,"确认写入成功"));
 char *req=pet_memory_reflection_request();assert(strstr(req,"recent_dialogue") && strstr(req,"outcomes"));free(req);
 for(int i=0;i<24;i++){
  char slot[32];snprintf(slot,sizeof(slot),"habit-%d",i);slot_name=slot;
  id=pet_memory_add("user","请少一些机械追问",true);
  assert(update("style","correction","回答后留白",id)==1);
 }
 assert(cJSON_GetArraySize(array("growth"))==16);
 assert(pet_memory_start()==0 && cJSON_GetArraySize(array("growth"))==16);
 id=pet_memory_add("user","请忘记刚才那条习惯",true);
 char forget[400];snprintf(forget,sizeof(forget),"{\"ops\":[],\"growth_ops\":[{\"op\":\"forget\",\"kind\":\"style\",\"slot\":\"habit-23\",\"source_ids\":[%d]}]}",id);
 assert(pet_memory_apply_reflection(forget)==1 && cJSON_GetArraySize(array("growth"))==15);
 assert(cJSON_GetArraySize(array("changes"))==0);
 struct stat a,b;assert(stat(@FLASH@ "/memory.0",&a)==0 && stat(@FLASH@ "/memory.1",&b)==0);
 assert(a.st_size<=65536+20 && b.st_size<=65536+20);
 return 0;
}
'''
        test_runtime_core.RuntimeCoreTests.run_c(self,code,['pet_util'])

    def test_relevant_lesson_is_retrieved_ahead_of_unrelated_active_experience(self):
        test_runtime_core.RuntimeCoreTests.run_c(self,r'''
#include "pet_memory.c"
#include <assert.h>
static void lesson(const char *slot,const char *trigger,const char *meaning){
 int id=pet_memory_add("user","请按这个经验改进做法",true);
 cJSON*r=cJSON_CreateObject();cJSON_AddArrayToObject(r,"ops");cJSON*g=cJSON_AddArrayToObject(r,"growth_ops"),*o=cJSON_CreateObject();cJSON_AddItemToArray(g,o);
 cJSON_AddStringToObject(o,"op","upsert");cJSON_AddStringToObject(o,"kind","lesson");cJSON_AddStringToObject(o,"basis","correction");
 cJSON_AddStringToObject(o,"slot",slot);cJSON_AddStringToObject(o,"trigger",trigger);cJSON_AddStringToObject(o,"text",meaning);cJSON_AddStringToObject(o,"check","核对实际结果");
 cJSON*ids=cJSON_AddArrayToObject(o,"source_ids");cJSON_AddItemToArray(ids,cJSON_CreateNumber(id));char*raw=cJSON_PrintUnformatted(r);assert(pet_memory_apply_reflection(raw)==1);free(raw);cJSON_Delete(r);
}
int main(void){
 assert(!pet_memory_start());
 for(int i=0;i<9;i++){char slot[24];snprintf(slot,sizeof(slot),"unrelated-%d",i);lesson(slot,"画画","画画时确认颜色");}
 lesson("提醒保存","取消提醒或设定提醒时","提醒保存失败不能说已完成");
 char context[6000];pet_memory_context("提醒设好了吗",context,sizeof(context));assert(strstr(context,"提醒保存失败不能说已完成"));
 return 0;
}
''',["pet_util"])
