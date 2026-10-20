"""Exercise actual input admission and source-dependent memory repair."""
import unittest
import test_runtime_core

class InputHostTests(unittest.TestCase):
    def test_recent_speech_tail_is_echo_but_short_answers_and_explicit_questions_are_not(self):
        test_runtime_core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include "pet_input.h"
int main(void){
 const char *reply="日本与美国将举行大规模联合军演，巴基斯坦暂时关闭与伊朗的边境贸易通道。此外，还有供暖季代缴费用骗局和电动车拧把即走需关闭电源等提醒。";
 assert(pet_input_echo_candidate("大规模联合军演，巴基斯坦暂时关闭与伊朗的边境贸易通道。此外，还有供暖器代缴话费骗局。",reply));
 assert(!pet_input_echo_candidate("好的",reply));
 assert(!pet_input_echo_candidate("你说的巴基斯坦暂时关闭与伊朗的边境贸易通道是什么意思？",reply));
 assert(!pet_input_echo_candidate("不是供暖器代缴话费骗局，是供暖费代缴骗局",reply));
 assert(!pet_input_echo_candidate("今天我想给你的小屋重新整理一下",reply));
 return 0;}
''',['pet_input'])

    def test_unconfirmed_audio_never_becomes_owner_evidence(self):
        test_runtime_core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "pet_input.h"
#include "pet_memory.h"
int main(void){
 assert(pet_memory_start()==0);
 const char *cases[]={"{}","{\"action\":\"speak\"}",
 "{\"input\":\"background\",\"action\":\"speak\",\"remember\":true}",
 "{\"input\":\"uncertain\",\"action\":\"ignore\"}",
 "{\"input\":\"direct\",\"action\":\"ignore\",\"remember\":true}"};
 for(int i=0;i<5;i++){cJSON*a=cJSON_Parse(cases[i]);assert(!pet_input_direct(a,true));assert(!pet_input_remember(a,true,true));cJSON_Delete(a);}
 cJSON*a=cJSON_Parse("{\"input\":\"direct\",\"action\":\"speak\",\"remember\":false}");
 assert(pet_input_direct(a,true)&&!pet_input_remember(a,true,true));
 pet_memory_add("user","嗯",pet_input_remember(a,true,true));
 char *pending=pet_memory_reflection_request();assert(pending);cJSON*q=cJSON_Parse(pending);assert(cJSON_GetArraySize(cJSON_GetObjectItem(q,"owner_messages"))==0);cJSON_Delete(q);free(pending);
 cJSON_ReplaceItemInObject(a,"remember",cJSON_CreateBool(true));
 assert(pet_input_remember(a,true,true)&&!pet_input_remember(a,true,false));
 assert(pet_input_direct(a,false));cJSON_Delete(a);
 const char *actions[]={"computer_task","computer_cancel"};
 for(int i=0;i<2;i++){
  a=cJSON_CreateObject();cJSON_AddStringToObject(a,"action",actions[i]);
  assert(!pet_input_direct(a,true));cJSON_AddStringToObject(a,"input","direct");assert(pet_input_direct(a,true));
  cJSON_ReplaceItemInObject(a,"input",cJSON_CreateString("background"));assert(!pet_input_direct(a,true));cJSON_Delete(a);
 }
 assert(!pet_input_direct(NULL,true));return 0;
}
''',['pet_input','pet_memory','pet_util'])

    def test_confirmed_background_repair_preserves_other_memories_and_reboots(self):
        test_runtime_core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include "pet_memory.h"
#include "pet_util.h"
int main(void){
 assert(!pet_memory_start());
 int good=pet_memory_add("user","我喜欢喝茶",true);
 int bad=pet_memory_add("user","这是电视台词",true);
 int derived=pet_memory_add("assistant","我在想电视里的故事",false);
 char ops[1500];snprintf(ops,sizeof(ops),"{\"ops\":[{\"op\":\"upsert\",\"kind\":\"preference\",\"slot\":\"饮料\",\"text\":\"主人喜欢茶\",\"source_id\":%d},{\"op\":\"upsert\",\"kind\":\"episode\",\"slot\":\"故事\",\"text\":\"错误电视情节\",\"source_id\":%d}],\"summary\":\"含有电视的旧摘要\"}",good,bad);
 assert(pet_memory_apply_reflection(ops)==2);
 pet_memory_rejection_t wrong={bad,1};assert(!pet_memory_reject_sources(&wrong,1));
 pet_memory_rejection_t rejected[]={{bad,pet_crc32("这是电视台词",strlen("这是电视台词"))},{derived,pet_crc32("我在想电视里的故事",strlen("我在想电视里的故事"))}};
 assert(pet_memory_reject_sources(rejected,2)==2);assert(!pet_memory_reject_sources(rejected,2));
 assert(!pet_memory_start());char context[10000];pet_memory_context("故事",context,sizeof(context));
 assert(strstr(context,"主人喜欢茶")&&!strstr(context,"电视"));
 cJSON*h=pet_memory_history();char*s=cJSON_PrintUnformatted(h);assert(strstr(s,"喝茶")&&!strstr(s,"电视"));free(s);cJSON_Delete(h);
 return 0;
}
''',['pet_memory','pet_util'])
