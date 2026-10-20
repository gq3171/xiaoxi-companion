"""Real remote-mode runtime reports delivery; fake speaker never emits audio."""
import unittest
import test_autonomy_host as runtime
import test_runtime_core as core

class CompanionRuntimeTests(unittest.TestCase):
    def test_only_admitted_input_gets_receipts_and_display_is_distinct_from_audio(self):
        headers={'runtime_test_sdk.h':runtime.SDK}
        for name in ['esp_log.h','esp_timer.h','esp_wifi.h','nvs.h','freertos/FreeRTOS.h','freertos/queue.h','freertos/task.h']:
            headers[name]='#include "runtime_test_sdk.h"\n'
        fixture='static int speech_failure;\n'+runtime.FIXTURE.replace('spoken++; return 0;', 'spoken++; return speech_failure?-1:0;')
        code=fixture+r'''
static int accepted_receipts,played_receipts,displayed_receipts,incomplete_receipts;
bool pet_speech_audible(void){return allowed;}
bool pet_cloud_ready(void){return true;}
void pet_cloud_input_source(bool microphone){}
bool pet_brain_enabled(void){return true;}
int pet_brain_start(void){return 0;}
void pet_brain_tick(uint32_t now){}
int pet_brain_receipt(const char *trace,const char *stage,int source){
 if(!trace[0])return -1;assert(!strcmp(trace,"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"));
 if(!strcmp(stage,"accepted")){assert(source>0);accepted_receipts++;}
 if(!strcmp(stage,"played"))played_receipts++;
 if(!strcmp(stage,"displayed"))displayed_receipts++;
 if(!strcmp(stage,"incomplete"))incomplete_receipts++;
 return 0;
}
int main(void){init();
 dialogue_plan="{\"input\":\"background\",\"action\":\"ignore\",\"_trace\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"}";
 dialogue("背景台词",true,true,pet_turn_current());assert(!accepted_receipts&&!played_receipts);
 dialogue_plan="{\"input\":\"direct\",\"action\":\"speak\",\"say\":\"测试\",\"_trace\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"}";
 allowed=false;dialogue("测试",true,true,pet_turn_current());assert(accepted_receipts==1&&displayed_receipts==1&&!played_receipts);
 allowed=true;dialogue("测试",true,true,pet_turn_current());assert(accepted_receipts==2&&played_receipts==1);
 speech_failure=1;dialogue("测试",true,true,pet_turn_current());assert(accepted_receipts==3&&incomplete_receipts==1);
 dialogue_cancelled=true;dialogue("测试",true,true,pet_turn_current());assert(accepted_receipts==3);
 return 0;}
'''
        core.RuntimeCoreTests.run_c(self,code,['pet_tts','pet_search','pet_util','pet_policy','pet_turn','pet_owner_session','pet_life','pet_computer','pet_home','pet_latency','pet_wake_gate','pet_input'],headers,['-DCONFIG_DESKPET_REMOTE_BRAIN=1'])

class RemoteReadinessTests(unittest.TestCase):
    def test_empty_local_key_does_not_block_remote_microphone_or_voice_selection(self):
        headers={'runtime_test_sdk.h':runtime.SDK}
        for name in ['esp_log.h','esp_timer.h','esp_wifi.h','nvs.h','freertos/FreeRTOS.h','freertos/queue.h','freertos/task.h']:
            headers[name]='#include "runtime_test_sdk.h"\n'
        code=runtime.FIXTURE+r'''
static bool paired_ready=true;
bool pet_speech_audible(void){return allowed;}
bool pet_cloud_ready(void){return paired_ready;}
void pet_cloud_input_source(bool microphone){}
bool pet_brain_enabled(void){return paired_ready;}
int pet_brain_start(void){return 0;}
void pet_brain_tick(uint32_t now){}
int pet_brain_receipt(const char *trace,const char *stage,int source){return 0;}
int main(void){init();has_keys=false;has_soul=true;has_voice=true;
 assert(!pet_secrets_minimax()[0]&&runtime_cloud_ready());
 int16_t samples[16000]={0};
 pet_utterance_t u={.pcm=samples,.samples=16000,.generation=pet_turn_current()};
 transcribe_success=true;dialogue_plan="{\"input\":\"direct\",\"action\":\"speak\",\"say\":\"我听到了\"}";
 voice_turn(&u);assert(transcriptions==1&&spoken==1);
 voice_actions[0]=PET_VOICE_PREVIEW;voice_indices[0]=18;voice_actions[1]=PET_VOICE_CLOSE;
 choose_voice();assert(voice_syntheses==1&&voice_preview_plays==1);
 paired_ready=false;u.generation=pet_turn_current();int previous=transcriptions;
 voice_turn(&u);assert(transcriptions==previous);
 return 0;
}
'''
        core.RuntimeCoreTests.run_c(self,code,['pet_tts','pet_search','pet_util','pet_policy','pet_turn','pet_owner_session','pet_life','pet_computer','pet_home','pet_latency','pet_wake_gate','pet_input'],headers,['-DCONFIG_DESKPET_REMOTE_BRAIN=1'])

class AuditRuntimeTests(unittest.TestCase):
    def run_fixture(self,fixture,body):
        headers={'runtime_test_sdk.h':runtime.SDK}
        for name in ['esp_log.h','esp_timer.h','esp_wifi.h','nvs.h','freertos/FreeRTOS.h','freertos/queue.h','freertos/task.h']:
            headers[name]='#include "runtime_test_sdk.h"\n'
        core.RuntimeCoreTests.run_c(self,fixture+body,['pet_tts','pet_search','pet_util','pet_policy','pet_turn','pet_owner_session','pet_life','pet_computer','pet_home','pet_latency','pet_wake_gate','pet_input'],headers)

    def test_yield_closes_listening_without_rest_or_cancelling_work(self):
        self.run_fixture(runtime.FIXTURE,r'''
int main(void){init();pet_wake_require(true);pet_wake_open(fake_now/1000);
 assert(pet_wake_active(fake_now/1000));unsigned before=pet_turn_current();
 dialogue_plan="{\"input\":\"direct\",\"action\":\"speak\",\"say\":\"嗯，你们聊。\",\"conversation_action\":\"yield\"}";
 dialogue("刚才不是和你说话",true,true,pet_turn_current());
 assert(spoken==1&&!pet_wake_active(fake_now/1000)&&!pet_wake_resting());
 assert(pet_turn_current()!=before&&discarded_captures>0);
 assert(pet_home_take_request()==PET_HOME_NONE);
 pet_wake_open(fake_now/1000);assert(pet_wake_active(fake_now/1000));return 0;}
''')

    def test_stale_yield_ack_cannot_close_a_newer_listening_turn(self):
        fixture=runtime.FIXTURE.replace('if (!pet_turn_valid(generation)) return -1; spoken++; return 0;', 'if (!pet_turn_valid(generation)) return -1; spoken++; pet_turn_next(); pet_wake_open(fake_now/1000); return -1;')
        self.run_fixture(fixture,r'''
int main(void){init();pet_wake_require(true);pet_wake_open(fake_now/1000);
 unsigned before=pet_turn_current();
 dialogue_plan="{\"input\":\"direct\",\"action\":\"speak\",\"say\":\"你们聊。\",\"conversation_action\":\"yield\"}";
 dialogue("刚才不是和你说话",true,true,before);
 assert(pet_turn_current()==before+1&&pet_wake_active(fake_now/1000)&&!discarded_captures);
 return 0;}
''')

    def test_sleep_preserves_unread_failure_until_explicit_wake_then_reports_once(self):
        fixture=runtime.FIXTURE.replace('bool pet_cloud_computer_configured(void){return false;}','bool pet_cloud_computer_configured(void){return true;}').replace('char *pet_cloud_computer(const char *o,const cJSON *r){return NULL;}',r'''char *pet_cloud_computer(const char *o,const cJSON *r){return pet_strdup("{\"ok\":true,\"job_id\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"state\":\"failed\",\"message\":\"浏览器任务未完成\"}");}''')
        self.run_fixture(fixture,r'''
int main(void){init();assert(!pet_computer_start());
 assert(!pet_computer_submit("检查网页","aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"));pet_computer_tick(100,false);
 pet_wake_require(true);pet_wake_rest();computer_updates(pet_turn_current());assert(!spoken);
 char text[448],receipt[80];assert(pet_computer_result_pending(text,sizeof(text),receipt,sizeof(receipt)));
 pet_wake_open(fake_now/1000);computer_updates(pet_turn_current());assert(spoken==1);
 assert(!pet_computer_result_pending(text,sizeof(text),receipt,sizeof(receipt)));
 fake_now+=3000000;computer_updates(pet_turn_current());assert(spoken==1);
 return 0;}
''')

    def test_media_delivery_waits_for_other_chat_modal_defer_and_acknowledges_actual_preview(self):
        fixture='#define CONFIG_DESKPET_MEDIA 1\n'+runtime.FIXTURE
        fixture=fixture.replace('bool pet_cloud_computer_configured(void){return false;}','bool pet_cloud_computer_configured(void){return true;}')
        fixture=fixture.replace('char *pet_cloud_computer(const char *o,const cJSON *r){return NULL;}',r'''char *pet_cloud_computer(const char *o,const cJSON *r){return pet_strdup("{\"ok\":true,\"job_id\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"state\":\"succeeded\",\"message\":\"小鸡画好啦。\",\"auto_preview\":true}");}''')
        self.run_fixture(fixture,r'''
static bool ui_ready=true,badge;static int previews;
bool pet_face_presentation_allowed(void){return ui_ready;}
void pet_face_result_pending(bool p){badge=p;}
void pet_media_context(char*out,size_t n){if(n)out[0]=0;}
void pet_media_tick(uint32_t generation){}
void pet_media_command(const char*a,int i,uint32_t generation){}
bool pet_media_present_result(const char*id,uint32_t generation){assert(!strcmp(id,"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"));previews++;return true;}
bool pet_media_self_test(void){return true;}
bool pet_media_active(void){return false;}
int main(void){init();assert(!pet_computer_start());
 assert(!pet_computer_submit("画一只小鸡","aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"));pet_computer_tick(100,false);
 s_media_owner_ended=false;pet_wake_require(true);pet_wake_open(fake_now/1000);
 computer_updates(pet_turn_current());assert(badge&&!previews&&!spoken); /* other chat active */
 fake_now+=21000000;ui_ready=false;computer_updates(pet_turn_current());assert(!previews);
 ui_ready=true;agency_value("media_deferred",cJSON_CreateBool(true));computer_updates(pet_turn_current());assert(!previews);
 agency_value("media_deferred",cJSON_CreateBool(false));s_media_owner_ended=true;computer_updates(pet_turn_current());assert(!previews);
 s_media_owner_ended=false;pet_wake_rest();computer_updates(pet_turn_current());assert(!previews);
 pet_wake_open(fake_now/1000);pet_wake_sleep();computer_updates(pet_turn_current());assert(previews==1&&spoken==1);
 char message[448],receipt[80];assert(pet_computer_result_pending(message,sizeof(message),receipt,sizeof(receipt)));
 fake_now+=3000000;computer_updates(pet_turn_current());assert(previews==1&&spoken==1);
 fake_now+=61000000;computer_updates(pet_turn_current());assert(previews==2&&spoken==1); /* retry view, not speech */
 assert(pet_computer_media_presented("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"));
 computer_updates(pet_turn_current());assert(!badge&&previews==2);
 /* Background cannot alter the owner's presentation policy. */
 dialogue_plan="{\"input\":\"background\",\"action\":\"ignore\",\"media_policy\":\"defer\"}";
 dialogue("旁人的话",true,true,pet_turn_current());assert(!cJSON_IsTrue(cJSON_GetObjectItem(s_agency,"media_deferred")));
 dialogue_plan="{\"input\":\"direct\",\"action\":\"speak\",\"say\":\"我先留着。\",\"media_policy\":\"defer\"}";
 dialogue("先别展示",true,true,pet_turn_current());assert(cJSON_IsTrue(cJSON_GetObjectItem(s_agency,"media_deferred")));
 return 0;}
''')

    def test_motion_voice_is_short_cooled_down_quiet_and_never_opens_microphone(self):
        fixture=runtime.FIXTURE.replace('.clock_valid = known_clock}', '.clock_valid = known_clock,.usb_power=true,.battery_percent=100,.motion_event=PET_MOTION_TILTED}')
        fixture=fixture.replace('bool pet_face_motion_allowed(void){return true;}','bool pet_face_motion_allowed(void){return motion_ui;}')
        fixture='static _Bool motion_ui=1;\n'+fixture
        self.run_fixture(fixture,r'''
int main(void){init();pet_wake_require(true);
 assert(!pet_wake_active(fake_now/1000));
 motion_voice(fake_now);assert(spoken==1&&!pet_wake_active(fake_now/1000)&&s_waiting_since==0);
 motion_voice(fake_now);assert(spoken==1);
 fake_now+=61000000;motion_voice(fake_now-3000000);assert(spoken==1);
 motion_ui=false;motion_voice(fake_now);assert(spoken==1);motion_ui=true;
 s_quiet_until=fake_now+1000000;motion_voice(fake_now);assert(spoken==1);s_quiet_until=0;
 minute=1380;motion_voice(fake_now);assert(spoken==1);minute=720;
 pet_wake_open(fake_now/1000);motion_voice(fake_now);assert(spoken==1);pet_wake_rest();
 /* Explicit sleep must remain undisturbed even if the UI was stale. */
 motion_voice(fake_now);assert(spoken==1);
 pet_wake_heard(fake_now/1000);fake_now+=21000000;motion_voice(fake_now);assert(spoken==2);
 return 0;}
''')

    def test_recent_own_reply_is_not_reaccepted_but_an_explicit_question_is(self):
        fixture=runtime.FIXTURE.replace('cJSON *pet_memory_history(void) { return cJSON_CreateArray(); }',r'''cJSON *pet_memory_history(void) {return cJSON_Parse("[{\"role\":\"assistant\",\"content\":\"巴基斯坦暂时关闭与伊朗的边境贸易通道，今天还有一条供暖费代缴骗局提醒。\"}]");}''')
        self.run_fixture(fixture,r'''
int main(void){init();
 assert(deliver("巴基斯坦暂时关闭与伊朗的边境贸易通道，今天还有一条供暖费代缴骗局提醒。",pet_turn_current(),false));
 dialogue_plan="{\"input\":\"direct\",\"action\":\"speak\",\"say\":\"收到\"}";
 dialogue("巴基斯坦暂时关闭与伊朗的边境贸易通道",true,true,pet_turn_current());assert(!memory_users&&spoken==1);
 dialogue("你说的巴基斯坦暂时关闭与伊朗的边境贸易通道是什么意思？",true,true,pet_turn_current());assert(memory_users==1&&spoken==2);
 return 0;}
''')

    def test_completed_explicit_task_reports_after_wake_window_expires_without_opening_mic(self):
        fixture=runtime.FIXTURE.replace('bool pet_cloud_computer_configured(void){return false;}','bool pet_cloud_computer_configured(void){return true;}').replace('char *pet_cloud_computer(const char *o,const cJSON *r){return NULL;}',r'''char *pet_cloud_computer(const char *o,const cJSON *r){return pet_strdup("{\"ok\":true,\"job_id\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"state\":\"succeeded\",\"message\":\"实际结果已保存\"}");}''')
        self.run_fixture(fixture,r'''
int main(void){init();assert(!pet_computer_start());
 assert(!pet_computer_submit("查询天气","aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"));pet_computer_tick(100,false);
 pet_wake_require(true);pet_wake_open(fake_now/1000);pet_wake_sleep();assert(!pet_wake_resting());
 computer_updates(pet_turn_current());assert(spoken==1&&!pet_wake_active(fake_now/1000));
 char text[448],receipt[80];assert(!pet_computer_result_pending(text,sizeof(text),receipt,sizeof(receipt)));
 fake_now+=3000000;computer_updates(pet_turn_current());assert(spoken==1);
 return 0;}
''')

if __name__=='__main__':unittest.main()
