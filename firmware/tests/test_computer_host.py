"""Replay board job checkpoints and idempotent server reconciliation."""
import unittest
import test_runtime_core

class ComputerHostTests(unittest.TestCase):
    def run_computer(self, body):
        test_runtime_core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "pet_computer.c"
static bool configured=true,fail,cancel_request,preview;
static const char *server_state="queued",*server_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
static int calls;static char operation[24],submitted_id[33];
bool pet_cloud_computer_configured(void){return configured;}
char *pet_cloud_computer(const char *op,const cJSON *request){
 calls++;snprintf(operation,sizeof(operation),"%s",op);
 if(cancel_request){pet_turn_next();return NULL;}
 if(fail)return NULL;
 if(!strcmp(op,"health"))return pet_strdup("{\"ok\":true,\"ready\":true}");
 snprintf(submitted_id,sizeof(submitted_id),"%s",text(request,"job_id"));
 cJSON*r=cJSON_CreateObject();cJSON_AddBoolToObject(r,"ok",true);
 cJSON_AddStringToObject(r,"job_id",server_id);cJSON_AddStringToObject(r,"state",server_state);
 cJSON_AddStringToObject(r,"message","实际服务器进度");cJSON_AddBoolToObject(r,"auto_preview",preview);
 char*raw=cJSON_PrintUnformatted(r);cJSON_Delete(r);return raw;
}
'''+body,["pet_home","pet_util","pet_turn"])

    def test_lost_submit_reply_reboot_uses_same_id_and_never_claims_success(self):
        self.run_computer(r'''
int main(void){
 assert(!pet_computer_start());
 assert(!pet_computer_submit("检查服务器磁盘",server_id));fail=true;pet_computer_tick(100,false);
 assert(!strcmp(operation,"submit")&&busy());char context[3000];pet_computer_context(context,sizeof(context));
 assert(strstr(context,"pending")&&pet_home_computer_state()==PET_COMPUTER_ERROR);
 assert(!pet_computer_start());fail=false;pet_computer_tick(200,false);
 assert(!strcmp(operation,"submit")&&!strcmp(submitted_id,server_id));
 assert(!strcmp(text(s_job,"state"),"queued"));
 assert(pet_computer_submit("不该重建", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")<0);
 server_state="running";pet_computer_tick(6000,false);assert(!strcmp(operation,"status"));
 assert(pet_home_computer_state()==PET_COMPUTER_RUNNING);assert(pet_home_take_request()==PET_HOME_WORK);
 int before=calls;pet_computer_tick(12000,true);assert(calls==before);
 server_state="succeeded";pet_computer_tick(12100,false);assert(!busy());
 assert(!pet_computer_start());assert(!strcmp(text(s_job,"state"),"succeeded"));return 0;
}
''')

    def test_read_only_connection_check_distinguishes_unknown_and_never_dispatches_pending_work(self):
        self.run_computer(r'''
int main(void){
 assert(!pet_computer_start());char context[3000];
 pet_computer_context(context,sizeof(context));
 assert(strstr(context,"尚未检查")&&!strstr(context,"暂时断开"));
 assert(pet_home_computer_state()==PET_COMPUTER_UNCHECKED);
 pet_home_description(context,sizeof(context));assert(strstr(context,"连接尚未检查")&&!strstr(context,"实体电脑未连接"));
 assert(!pet_computer_submit("等待明确提交的任务",server_id));
 pet_computer_check_connection(100);
 assert(calls==1&&!strcmp(operation,"health")&&!strcmp(text(s_job,"state"),"pending"));
 pet_computer_context(context,sizeof(context));assert(strstr(context,"最近一次检查可达"));
 fail=true;pet_computer_check_connection(200);
 pet_computer_context(context,sizeof(context));assert(strstr(context,"最近一次请求失败"));
 assert(!strcmp(text(s_job,"state"),"pending"));
 fail=false;pet_computer_check_connection(300);
 pet_computer_context(context,sizeof(context));assert(strstr(context,"最近一次检查可达"));
 assert(calls==3&&!strcmp(operation,"health"));
 return 0;}
''')

    def test_cancel_requires_server_confirmation_and_wrong_job_is_rejected(self):
        self.run_computer(r'''
int main(void){
 assert(!pet_computer_start());configured=false;assert(pet_computer_submit("test",server_id)<0);
 configured=true;assert(!pet_computer_submit("测试任务",server_id));assert(!pet_computer_cancel());
 fail=true;pet_computer_tick(100,false);assert(!strcmp(operation,"cancel")&&!strcmp(text(s_job,"state"),"pending"));
 assert(!pet_computer_start());fail=false;server_id="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";pet_computer_tick(200,false);
 assert(!strcmp(text(s_job,"state"),"pending"));
 server_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";server_state="cancelled";pet_computer_tick(31000,false);
 assert(!strcmp(operation,"cancel")&&!busy());
 assert(pet_computer_submit("new", "-invalid-id")<0);return 0;
}
''')

    def test_new_utterance_cancels_only_status_request_and_preserves_background_job(self):
        self.run_computer(r'''
int main(void){
 assert(!pet_computer_start());cancel_request=true;pet_computer_check_connection(100);
 assert(!s_checked&&pet_home_computer_state()==PET_COMPUTER_UNCHECKED);
 cancel_request=false;assert(!pet_computer_submit("边工作边聊天",server_id));
 server_state="running";pet_computer_tick(1200,false);
 assert(busy()&&s_reachable&&pet_home_computer_state()==PET_COMPUTER_RUNNING);
 uint32_t before=pet_turn_current();cancel_request=true;pet_computer_tick(6300,false);
 assert(pet_turn_current()!=before&&busy()&&s_reachable);
 assert(!strcmp(text(s_job,"state"),"running")&&!cJSON_IsTrue(cJSON_GetObjectItem(s_job,"cancel_requested")));
 assert(pet_home_computer_state()==PET_COMPUTER_RUNNING);
 cancel_request=false;server_state="succeeded";pet_computer_tick(7400,false);
 assert(!busy()&&!strcmp(text(s_job,"state"),"succeeded"));
 return 0;}
''')

    def test_terminal_results_survive_reboot_and_new_tasks_and_ack_only_after_delivery(self):
        self.run_computer(r'''
int main(void){
 assert(!pet_computer_start());assert(!pet_computer_submit("首个任务",server_id));
 server_state="failed";pet_computer_tick(100,false);
 char message[448],receipt[80];assert(pet_computer_result_pending(message,sizeof(message),receipt,sizeof(receipt)));
 assert(strstr(message,"还没做成"));assert(!pet_computer_start());
 assert(pet_computer_result_pending(message,sizeof(message),receipt,sizeof(receipt)));
 assert(pet_computer_result_delivered("wrong")<0);
 const char *second="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
 assert(!pet_computer_submit("第二个任务",second));
 assert(pet_computer_result_pending(message,sizeof(message),receipt,sizeof(receipt))&&strstr(receipt,"aaaaaaaa"));
 assert(!pet_computer_result_delivered(receipt));assert(!pet_computer_result_pending(message,sizeof(message),receipt,sizeof(receipt)));
 server_id=second;server_state="succeeded";pet_computer_tick(200,false);
 assert(pet_computer_result_pending(message,sizeof(message),receipt,sizeof(receipt))&&!strcmp(message,"实际服务器进度"));
 assert(!pet_computer_result_delivered(receipt));assert(!pet_computer_start());
 assert(!pet_computer_result_pending(message,sizeof(message),receipt,sizeof(receipt)));
 return 0;}
''')

    def test_preview_metadata_survives_reboot_and_viewing_newer_result_preserves_older_notice(self):
        self.run_computer(r'''
int main(void){
 const char *first="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",*second="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
 assert(!pet_computer_start());assert(!pet_computer_submit("画小鸡",first));
 preview=true;server_state="succeeded";pet_computer_tick(100,false);assert(!pet_computer_start());
 char id[33];assert(pet_computer_result_media(id,sizeof(id))&&!strcmp(id,first));
 assert(!pet_computer_submit("画小猫",second));server_id=second;pet_computer_tick(200,false);
 assert(!pet_computer_start());assert(pet_computer_result_media(id,sizeof(id))&&!strcmp(id,first));
 assert(!pet_computer_media_presented("cccccccccccccccccccccccccccccccc"));
 assert(pet_computer_media_presented(second));assert(pet_computer_result_media(id,sizeof(id))&&!strcmp(id,first));
 assert(pet_computer_media_presented(first));assert(!pet_computer_start());
 char out[448],receipt[80];assert(!pet_computer_result_pending(out,sizeof(out),receipt,sizeof(receipt)));
 return 0;
}
''')

    def test_explicit_resume_reuses_nonce_after_lost_ack_and_reboot(self):
        self.run_computer(r'''
int main(void){
 assert(!pet_computer_start());assert(!pet_computer_submit("原任务",server_id));
 server_state="interrupted";pet_computer_tick(100,false);assert(!busy());
 const char *parent="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",*child="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
 assert(!pet_computer_resume_id(parent,child));fail=true;pet_computer_tick(200,false);
 assert(!strcmp(operation,"resume"));assert(!pet_computer_start());
 fail=false;server_id=child;server_state="queued";pet_computer_tick(300,false);
 assert(!strcmp(operation,"resume")&&!strcmp(submitted_id,parent));
 assert(!strcmp(text(s_job,"job_id"),child)&&!strcmp(text(s_job,"resume_of"),parent));
 assert(pet_computer_resume_id(parent,"cccccccccccccccccccccccccccccccc")<0);
 return 0;}
''')

    def test_blocked_task_can_be_cancelled_without_claiming_success(self):
        self.run_computer(r'''
int main(void){
 assert(!pet_computer_start());assert(!pet_computer_submit("需要人工处理",server_id));
 server_state="blocked";pet_computer_tick(100,false);assert(!busy());
 assert(!pet_computer_cancel());server_state="cancelled";pet_computer_tick(200,false);
 assert(!strcmp(operation,"cancel")&&!strcmp(text(s_job,"state"),"cancelled"));
 return 0;}
''')

    def test_first_frame_before_terminal_poll_is_durable_and_never_claims_task_success(self):
        self.run_computer(r'''
int main(void){
 assert(!pet_computer_start());assert(!pet_computer_submit("画图",server_id));
 server_state="running";pet_computer_tick(100,false);
 assert(!pet_computer_media_presented(server_id));assert(!strcmp(text(s_job,"state"),"running"));
 assert(cJSON_IsTrue(cJSON_GetObjectItem(s_job,"media_presented")));
 assert(!pet_computer_start());assert(cJSON_IsTrue(cJSON_GetObjectItem(s_job,"media_presented")));
 server_state="succeeded";preview=true;pet_computer_tick(6000,false);
 char msg[448],receipt[80];assert(!pet_computer_result_pending(msg,sizeof(msg),receipt,sizeof(receipt)));
 assert(!strcmp(text(s_job,"reported_state"),"succeeded"));
 const char *new_id="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
 assert(!pet_computer_submit("新任务",new_id));assert(!cJSON_IsTrue(cJSON_GetObjectItem(s_job,"media_presented")));
 return 0;}
''')

    def test_first_frame_never_hides_a_failed_task_and_announced_preview_retries_are_silent(self):
        self.run_computer(r'''
int main(void){
 assert(!pet_computer_start());assert(!pet_computer_submit("画图",server_id));
 assert(!pet_computer_media_presented(server_id));server_state="failed";preview=true;pet_computer_tick(100,false);
 char msg[448],receipt[80];assert(pet_computer_result_pending(msg,sizeof(msg),receipt,sizeof(receipt))&&strstr(msg,"还没做成"));
 assert(!pet_computer_result_delivered(receipt));
 server_id="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";assert(!pet_computer_submit("动画",server_id));
 server_state="succeeded";pet_computer_tick(6000,false);
 assert(pet_computer_result_pending(msg,sizeof(msg),receipt,sizeof(receipt))&&msg[0]);
 assert(pet_computer_result_announced("wrong")<0);assert(!pet_computer_result_announced(receipt));
 assert(!pet_computer_start());assert(pet_computer_result_pending(msg,sizeof(msg),receipt,sizeof(receipt))&&!msg[0]);
 char id[33];assert(pet_computer_result_media(id,sizeof(id))&&!strcmp(id,server_id));
 assert(pet_computer_media_presented(id));assert(!pet_computer_result_pending(msg,sizeof(msg),receipt,sizeof(receipt)));
 return 0;}
''')

