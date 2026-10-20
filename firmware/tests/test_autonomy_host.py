"""Replay the actual runtime's autonomous decisions with fake sensors/providers."""
import unittest
import test_runtime_core

SDK = r'''
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
typedef int esp_err_t;
#define ESP_OK 0
typedef int wifi_ps_type_t;
#define WIFI_PS_NONE 0
#define WIFI_PS_MIN_MODEM 1
int esp_wifi_set_ps(wifi_ps_type_t);
#define ESP_LOGW(...) ((void)0)
#define ESP_LOGI(...) ((void)0)
typedef uint32_t TickType_t;
typedef int BaseType_t;
typedef void *QueueHandle_t;
typedef int portMUX_TYPE;
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(x) ((void)0)
#define portEXIT_CRITICAL(x) ((void)0)
#define pdPASS 1
#define pdTRUE 1
#define pdFALSE 0
#define pdMS_TO_TICKS(x) (x)
int64_t esp_timer_get_time(void);
QueueHandle_t xQueueCreate(unsigned, unsigned);
int xQueueSend(void *, const void *, TickType_t);
int xQueueReceive(void *, void *, TickType_t);
int xTaskCreate(void (*)(void *), const char *, unsigned, void *, unsigned, void *);
void vTaskDelay(TickType_t);
typedef int nvs_handle_t;
#define NVS_READONLY 0
#define NVS_READWRITE 1
int nvs_open(const char *, int, nvs_handle_t *);
void nvs_close(nvs_handle_t);
int nvs_set_u16(nvs_handle_t, const char *, uint16_t);
int nvs_get_u16(nvs_handle_t, const char *, uint16_t *);
int nvs_set_i32(nvs_handle_t, const char *, int32_t);
int nvs_get_i32(nvs_handle_t, const char *, int32_t *);
int nvs_set_i64(nvs_handle_t, const char *, int64_t);
int nvs_get_i64(nvs_handle_t, const char *, int64_t *);
int nvs_commit(nvs_handle_t);
'''

FIXTURE = r'''
#include "pet_runtime.c"
static int64_t fake_now = 3000000000LL;
static int minute = 720, provider_calls, search_calls, spoken;
static bool known_clock = true, allowed = true, connected = true, cancelled;
static bool has_soul = true, has_voice = true, has_keys = true;
static int birth_calls, enrollment_calls, outcome_failures, outcome_successes;
static int owner_checks, transcriptions, memory_users, memory_evidence;
static bool dialogue_cancelled;
static bool transcribe_success;
static const char *dialogue_plan="{\"action\":\"ignore\"}";
static const char *plan = "{\"action\":\"wait\",\"next_check_minutes\":15}";
static bool capture_paused;
static int voice_step,voice_preview_plays,voice_syntheses;
static int voice_actions[8]={PET_VOICE_CLOSE},voice_indices[8];
static bool voice_failure;
static int face_updates,screen_off_requests,discarded_captures;
static bool off_after_rest;
static int first_wake_contexts;
void pet_audio_stop(void){}
void pet_capture_pause_turns(bool value){capture_paused=value;}
bool pet_face_voice_open(void){return true;}
void pet_face_voice_close(void){}
void pet_face_voice_status(const char *text){}
int pet_face_voice_wait(int *index,uint32_t *generation){
 *generation=pet_turn_next();*index=voice_indices[voice_step];return voice_actions[voice_step++];
}
int pet_cloud_speak_voice(const char *text,const char *id,int16_t *pcm,int n){
 assert(capture_paused&&pet_tts_find(id)>=0);voice_syntheses++;
 if(voice_failure)return -1;
 assert(n>=1600);for(int i=0;i<1600;i++)pcm[i]=(int16_t)i;return 1600;
}
int pet_audio_play_turn(const int16_t *pcm,size_t n,uint32_t generation){
 assert(capture_paused&&pet_turn_valid(generation));voice_preview_plays++;return 0;
}
int64_t esp_timer_get_time(void) { return fake_now; }
void *xQueueCreate(unsigned n, unsigned size) { return (void *)1; }
int xQueueSend(void *q, const void *m, TickType_t t) { return pdTRUE; }
int xQueueReceive(void *q, void *m, TickType_t t) { return pdFALSE; }
int xTaskCreate(void (*f)(void *), const char *n, unsigned z, void *a, unsigned p, void *h) { return pdPASS; }
void vTaskDelay(TickType_t t) {}
int nvs_open(const char *ns, int mode, nvs_handle_t *h) { return -1; }
void nvs_close(nvs_handle_t h) {}
int nvs_set_u16(nvs_handle_t h, const char *key, uint16_t n) { return 0; }
int nvs_get_u16(nvs_handle_t h, const char *key, uint16_t *n) { return -1; }
int nvs_set_i32(nvs_handle_t h, const char *key, int32_t n) { return 0; }
int nvs_get_i32(nvs_handle_t h, const char *key, int32_t *n) { return -1; }
int nvs_set_i64(nvs_handle_t h, const char *key, int64_t n) { return 0; }
int nvs_get_i64(nvs_handle_t h, const char *key, int64_t *n) { return -1; }
int nvs_commit(nvs_handle_t h) { return 0; }
pet_hardware_state_t pet_hardware_state(void) { return (pet_hardware_state_t){.clock_valid = known_clock}; }
int pet_hardware_local_minute(void) { return minute; }
void pet_hardware_description(char *out, size_t n) { snprintf(out, n, "模拟北京时间"); }
bool pet_setup_connected(void) { return connected; }
int pet_setup_wifi_configure(void) { return 0; }
void pet_setup_wifi_poll(void) {}
int pet_setup_keys(bool force) { return 0; }
int pet_setup_voice_keys(int16_t *pcm, int n) { return 0; }
bool pet_owner_locked(void) { return has_voice; }
bool pet_voice_reply_usable(const int16_t *p,int n) { return p && n>=4000; }
bool pet_voice_usable(const int16_t *pcm, int n) { return pcm && n>=12000; }
float pet_owner_verify(const int16_t *pcm, int n) { owner_checks++; return -1; }
int pet_setup_soul(int16_t *mic, int n, int16_t *pcm, int capacity) { birth_calls++; return -1; }
int pet_setup_voice(int16_t *pcm, int n, bool force) { enrollment_calls++; return -1; }
int pet_store_has_soul(void) { return has_soul; }
void pet_wake_phrase(char*out,size_t n){snprintf(out,n,"小西小西");}
bool pet_wake_ready(void){return true;}
bool pet_store_identity_needs_review(void) { return false; }
int pet_voice_has(void) { return has_voice; }
const char *pet_secrets_deepseek(void) { return has_keys ? "test" : ""; }
const char *pet_secrets_minimax(void) { return has_keys ? "test" : ""; }
int pet_store_system(char *out, int n) { snprintf(out, n, "我是一只有自己兴趣的桌宠。"); return 0; }
void pet_store_creature(char *out, int n) { snprintf(out, n, "猫"); }
void pet_audio_allow_output(bool a) { allowed = a; }
bool pet_audio_output_allowed(void) { return allowed; }
bool pet_audio_playing(void) {return false;}
bool pet_cloud_network_active(void) {return false;}
int esp_wifi_set_ps(wifi_ps_type_t type){return ESP_OK;}
int pet_audio_get_volume(void) { return 5; }
bool pet_capture_listening(void) { return false; }
bool pet_capture_pending(void){return false;}
bool pet_capture_take(pet_utterance_t *u, TickType_t t) { return false; }
void pet_capture_discard(void) {discarded_captures++;}
void pet_capture_reply_pending(bool p,uint32_t g){}
bool pet_capture_claim(pet_utterance_t*u){return pet_turn_valid(u->generation);}
float pet_voice_match(const int16_t *pcm, int n) { return 0.9f; }
void pet_face_set(const char *phase, const char *text) {face_updates++;}
void pet_face_hint(const char *phase,const char *text){face_updates++;}
void pet_face_screen_off(bool after_rest){screen_off_requests++;off_after_rest=after_rest;assert(spoken>0&&!pet_wake_active(fake_now/1000));}
void pet_face_message(const char *text) {}
void pet_face_read(const char *text) {}
bool pet_face_motion_allowed(void){return true;}
void pet_face_mood(const char *mood) {}
void pet_face_identity(const char *creature) {}
int pet_face_input(const char *title, const char *hint, int secret, char *out, int n) { return -1; }
int pet_face_choose(const char *title, const char *choices, char *out, int n) { return -1; }
int pet_speech_say(const char *text, uint32_t generation, int16_t *pcm, int n) {
    if (!pet_turn_valid(generation)) return -1; spoken++; return 0;
}
size_t pet_speech_delivered_bytes(void) { return 0; }
#ifndef CONFIG_DESKPET_REMOTE_BRAIN
bool pet_speech_audible(void) { return false; }
#endif
void pet_cloud_begin_turn(uint32_t generation) {}
char *pet_cloud_dialogue(const char *system, const cJSON *history) {
 if(system&&strstr(system,"本轮是明确叫名字"))first_wake_contexts++;
 assert(cJSON_GetArraySize(history)>0); /* Candidate must reach the model. */
 if(dialogue_cancelled)pet_turn_next();
 return strcmp(dialogue_plan,"FAIL")?pet_strdup(dialogue_plan):NULL;
}
bool pet_cloud_computer_configured(void){return false;}
char *pet_cloud_computer(const char *o,const cJSON *r){return NULL;}
char *pet_cloud_search(const char *query) { search_calls++; return pet_strdup("真实检索结果"); }
char *pet_cloud_minimax(const char *system, const char *request, bool reflection) {
    provider_calls++; if (cancelled) pet_turn_next(); return pet_strdup(plan);
}
int pet_cloud_transcribe(const int16_t *pcm, int n, char *out, int capacity) {
    transcriptions++; if(transcribe_success){snprintf(out,capacity,"嗯");return 0;}return -1;
}
int pet_memory_observe(const char *kind, const char *detail) { if(!strcmp(kind,"failure"))outcome_failures++;else outcome_successes++;return 1; }
int pet_memory_add(const char *role, const char *text, bool owner) {if(!strcmp(role,"user")){memory_users++;memory_evidence+=owner;}return 1;}
int pet_memory_reject_sources(const pet_memory_rejection_t*s,size_t n){return 0;}
int pet_memory_ignore_message(int id) { return 0; }
cJSON *pet_memory_history(void) { return cJSON_CreateArray(); }
void pet_memory_context(const char *query, char *out, size_t n) { snprintf(out, n, "主人喜欢天文"); }
bool pet_memory_needs_reflection(void) { return false; }
char *pet_memory_reflection_request(void) { return 0; }
int pet_memory_apply_reflection(const char *json) { return 0; }
static void init(void) {
    pet_life_start();pet_computer_start();
    s_agency = cJSON_Parse("{\"reminders\":[],\"curiosity\":\"\",\"next_reminder\":1}");
    s_last_user = fake_now - 30 * MINUTE_US; s_last_spoke = s_last_user;
    s_next_plan = 0; s_daily_count = 0;
}
'''


class AutonomyHostTests(unittest.TestCase):
    def test_explicit_wake_can_answer_at_night_but_does_not_override_explicit_quiet(self):
        self.run_fixture(r'''
int main(void){
 init();minute=1380;pet_wake_require(true);pet_wake_sleep();
 s_voice_until=s_quiet_until=s_quiet_epoch=0;assert(!pet_runtime_audio_allowed());
 pet_wake_heard(fake_now/1000);assert(pet_runtime_audio_allowed());
 s_quiet_until=fake_now+MINUTE_US;assert(!pet_runtime_audio_allowed());
 s_quiet_until=0;s_quiet_epoch=time(NULL)+120;assert(!pet_runtime_audio_allowed());
 s_quiet_epoch=0;dialogue_plan="{\"input\":\"direct\",\"action\":\"speak\",\"say\":\"你是让我上床休息，顺便关掉屏幕吗？\",\"remember\":false}";
 dialogue("休息，视频吧",true,true,pet_turn_current());
 assert(first_wake_contexts==1&&spoken==1&&!screen_off_requests&&pet_home_take_request()==PET_HOME_NONE);
 dialogue("我想看看视频",true,true,pet_turn_current());assert(first_wake_contexts==1);
 pet_wake_sleep();assert(!pet_runtime_audio_allowed());
 pet_wake_open(fake_now/1000);dialogue("你好",true,true,pet_turn_current());assert(first_wake_contexts==2);
 return 0;
}
''')

    def test_rest_acknowledges_then_closes_capture_and_only_direct_can_turn_screen_off(self):
        self.run_fixture(r'''
int main(void){
 init();pet_wake_require(true);pet_wake_open(fake_now/1000);
 uint32_t before=pet_turn_current();
 dialogue_plan="{\"input\":\"background\",\"action\":\"speak\",\"say\":\"台词\",\"home_action\":\"rest\",\"screen_action\":\"off\"}";
 dialogue("背景",true,true,before);assert(!spoken&&!screen_off_requests&&!pet_wake_resting());
 assert(pet_home_take_request()==PET_HOME_NONE);
 pet_wake_open(fake_now/1000);
 dialogue_plan="{\"input\":\"direct\",\"action\":\"speak\",\"say\":\"好，我躺好就熄屏。\",\"home_action\":\"rest\",\"screen_action\":\"off\"}";
 dialogue("上床休息然后熄屏",true,true,before);
 assert(spoken==1&&screen_off_requests==1&&off_after_rest&&discarded_captures==1);
 assert(pet_wake_resting()&&!pet_wake_active(fake_now/1000)&&!pet_turn_valid(before));
 assert(pet_home_take_request()==PET_HOME_REST);
 s_next_plan=0;fake_now+=2*MINUTE_US;autonomous(pet_turn_current());assert(!provider_calls);
 pet_wake_heard(fake_now/1000);assert(!pet_wake_resting()&&pet_wake_active(fake_now/1000));
 dialogue_plan="{\"input\":\"direct\",\"action\":\"speak\",\"say\":\"好，屏幕关掉了。\",\"screen_action\":\"off\"}";
 dialogue("关屏",true,true,pet_turn_current());
 assert(screen_off_requests==2&&!off_after_rest&&!pet_wake_resting());
 return 0;
}
''')

    def test_playback_candidate_background_and_failures_do_not_replace_ui_or_enter_memory(self):
        self.run_fixture(r'''
int main(void){
 init();transcribe_success=true;int16_t pcm[1]={0};
 pet_utterance_t u={.pcm=pcm,.samples=8000,.generation=pet_turn_current(),.overlap=true};
 int64_t old=s_last_user;
 dialogue_plan="{\"input\":\"background\",\"action\":\"ignore\",\"remember\":false}";
 voice_turn(&u);assert(transcriptions==1&&!memory_users&&!face_updates&&s_last_user==old);
 transcribe_success=false;voice_turn(&u);assert(transcriptions==2&&!memory_users&&!face_updates&&!outcome_failures);
 u.too_long=true;voice_turn(&u);assert(transcriptions==2&&!face_updates);
 return 0;
}
''')
    def test_persisted_goal_controls_only_from_direct_conversation_and_autonomy_cannot_replace_it(self):
        self.run_fixture(r'''
int main(void){
 init();
 dialogue_plan="{\"input\":\"background\",\"action\":\"speak\",\"remember\":false,\"say\":\"背景\",\"life_plan\":{\"goal\":\"背景安排\",\"steps\":[\"rest\"]}}";
 dialogue("背景",true,true,pet_turn_current());assert(!pet_life_active());
 dialogue_plan="{\"input\":\"direct\",\"action\":\"speak\",\"remember\":false,\"say\":\"好，我先洗漱，再看看窗外。\",\"life_plan\":{\"goal\":\"晨间活动\",\"reason\":\"你刚刚提出\",\"steps\":[\"wash\",\"window\"]}}";
 dialogue("先洗脸再看看窗外",true,true,pet_turn_current());assert(pet_life_active());
 pet_life_tick(100,0,false,false,false);assert(pet_home_take_request()==PET_HOME_WASH);
 plan="{\"action\":\"wait\",\"life_plan\":{\"goal\":\"不该覆盖\",\"steps\":[\"rest\"]}}";s_next_plan=0;fake_now+=2*MINUTE_US;
 autonomous(pet_turn_current());
 char context[3000];pet_life_context(context,sizeof(context));assert(strstr(context,"晨间活动")&&!strstr(context,"不该覆盖"));
 dialogue_plan="{\"action\":\"speak\",\"say\":\"先暂停。\",\"life_control\":\"pause\"}";
 dialogue("先暂停",true,false,pet_turn_current());pet_life_context(context,sizeof(context));assert(strstr(context,"暂停"));
 plan="{\"action\":\"search\",\"query\":\"未经授权自主搜索\"}";s_next_plan=0;fake_now+=2*MINUTE_US;
 autonomous(pet_turn_current());assert(search_calls==0);
 return 0;
}
''')

    def test_voice_preview_cancel_and_failed_save_leave_current_voice_and_memory_unchanged(self):
        self.run_fixture(r'''
int main(void){
 init();pet_tts_start();
 voice_actions[0]=PET_VOICE_PREVIEW;voice_indices[0]=18;voice_actions[1]=PET_VOICE_CLOSE;
 choose_voice();assert(pet_tts_current()==4&&voice_preview_plays==1&&voice_syntheses==1&&!capture_paused&&!memory_users);
 voice_step=0;voice_actions[0]=PET_VOICE_SAVE;voice_indices[0]=18;
 choose_voice();assert(pet_tts_current()==18&&voice_syntheses==2&&!capture_paused&&!memory_users);
 pet_tts_start();assert(pet_tts_current()==18&&pet_tts_ack_size()==1600);
 voice_step=0;voice_failure=true;voice_indices[0]=0;
 choose_voice();assert(pet_tts_current()==18&&!capture_paused&&!memory_users);
 return 0;
}
''')
    def test_home_knowledge_requests_and_disconnected_computer_do_not_fabricate_work(self):
        self.run_fixture(r'''
int main(void){
 init();char *context=system_context("");assert(context&&strstr(context,"虚拟家")&&strstr(context,"实体电脑尚未配置连接"));free(context);
 dialogue_plan="{\"action\":\"speak\",\"say\":\"我去工作台坐好等连接。\",\"home_action\":\"work\"}";
 dialogue("去工作台",true,false,pet_turn_current());assert(pet_home_take_request()==PET_HOME_WORK);
 assert(pet_home_computer_state()==PET_COMPUTER_DISCONNECTED);
 dialogue_plan="{\"action\":\"ignore\",\"home_action\":\"rest\"}";
 dialogue("background",true,false,pet_turn_current());assert(pet_home_take_request()==PET_HOME_NONE);
 dialogue_plan="{\"action\":\"speak\",\"say\":\"test\",\"home_action\":\"run_shell\"}";
 dialogue("test",true,false,pet_turn_current());assert(pet_home_take_request()==PET_HOME_NONE);
 init();plan="{\"action\":\"wait\",\"home_action\":\"rest\"}";
 autonomous(pet_turn_current());assert(pet_home_take_request()==PET_HOME_REST);
 init();cancelled=true;plan="{\"action\":\"wait\",\"home_action\":\"work\"}";
 autonomous(pet_turn_current());assert(pet_home_take_request()==PET_HOME_NONE);
 return 0;
}
''')

    def test_daily_first_short_reply_and_idle_reply_go_to_asr_without_voice_verification(self):
        self.run_fixture(r'''
int main(void) {
 init();transcribe_success=true;int16_t pcm[1]={0};
 pet_utterance_t u={.pcm=pcm,.samples=8000,.generation=pet_turn_current()};
 voice_turn(&u);assert(transcriptions==1 && owner_checks==0);
 fake_now+=3600000000LL;pet_owner_session_reset();
 voice_turn(&u);assert(transcriptions==2 && owner_checks==0);
 pet_turn_next();voice_turn(&u);assert(transcriptions==2 && owner_checks==0);
 u.generation=pet_turn_current();has_voice=false;voice_turn(&u);assert(transcriptions==2);
 return 0;
}
''')

    def test_audio_admission_commits_only_after_valid_current_direct_reply(self):
        self.run_fixture(r'''
int main(void){
 init();pet_wake_require(true);pet_wake_open(fake_now/1000);
 int64_t old=s_last_user;
 dialogue_plan="{\"input\":\"background\",\"action\":\"ignore\",\"remember\":true}";
 dialogue("影视台词",true,true,pet_turn_current());
 assert(memory_users==0&&memory_evidence==0&&s_last_user==old&&!pet_wake_active(fake_now/1000));
 dialogue_plan="{\"action\":\"speak\",\"say\":\"错误缺少来源\"}";
 dialogue("候选语音",true,true,pet_turn_current());assert(memory_users==0);
 dialogue_plan="FAIL";dialogue("网络失败",true,true,pet_turn_current());assert(memory_users==0);
 dialogue_plan="{\"input\":\"direct\",\"action\":\"speak\",\"remember\":true,\"say\":\"好的\"}";
 dialogue_cancelled=true;dialogue("已被打断",true,true,pet_turn_current());assert(memory_users==0);
 dialogue_cancelled=false;dialogue("我喜欢茶",true,true,pet_turn_current());assert(memory_users==1&&memory_evidence==1);
 dialogue_plan="{\"input\":\"direct\",\"action\":\"speak\",\"remember\":false,\"say\":\"嗯\"}";
 dialogue("嗯",true,true,pet_turn_current());assert(memory_users==2&&memory_evidence==1);
 return 0;
}
''')

    def run_fixture(self, body):
        headers = {"runtime_test_sdk.h": SDK}
        for name in ["esp_log.h", "esp_timer.h", "esp_wifi.h", "nvs.h", "freertos/FreeRTOS.h", "freertos/queue.h", "freertos/task.h"]:
            headers[name] = '#include "runtime_test_sdk.h"\n'
        test_runtime_core.RuntimeCoreTests.run_c(self, FIXTURE + body, ["pet_tts", "pet_search", "pet_util", "pet_policy", "pet_turn", "pet_owner_session", "pet_life", "pet_computer", "pet_home", "pet_latency", "pet_wake_gate", "pet_input"], headers)

    def test_real_action_failures_feed_reflection_instead_of_claiming_success(self):
        self.run_fixture(r'''
int main(void){
 init();dialogue_plan="{\"action\":\"cancel_reminder\",\"reminder_id\":999}";
 dialogue("取消这条提醒",true,false,pet_turn_current());assert(outcome_failures==1 && outcome_successes==0);
 dialogue_plan="{\"action\":\"speak\",\"reminder\":{\"text\":\"test\",\"due\":\"invalid\"}}";
 dialogue("提醒我",true,false,pet_turn_current());assert(outcome_failures==2 && outcome_successes==0);
 return 0;
}
''')

    def test_owner_verification_precedes_identity_and_blocks_failed_enrollment(self):
        self.run_fixture(r'''
int main(void) {
    init(); has_voice = false; has_soul = false;
    maybe_setup(); assert(enrollment_calls == 1 && birth_calls == 0);
    maybe_setup(); assert(enrollment_calls == 1 && birth_calls == 0);
    autonomous(pet_turn_current()); assert(provider_calls == 0);
    has_voice = true; maybe_setup(); assert(birth_calls == 1);
    return 0;
}
''')

    def test_deferred_onboarding_does_not_repeat_or_initiate_without_identity(self):
        self.run_fixture(r'''
int main(void) {
    init(); has_soul = false; has_keys = false;
    maybe_setup(); assert(birth_calls == 0);
    has_keys = true; connected = false; maybe_setup(); assert(birth_calls == 0);
    connected = true; maybe_setup(); assert(birth_calls == 1);
    maybe_setup(); assert(birth_calls == 1); /* Cancellation leaves normal UI usable. */
    autonomous(pet_turn_current()); assert(provider_calls == 0);
    s_birth_attempted = false; maybe_setup(); assert(birth_calls == 2);
    has_soul = true; has_voice = false; maybe_setup(); assert(enrollment_calls == 1);
    maybe_setup(); assert(enrollment_calls == 1);
    return 0;
}
''')

    def test_wait_night_cancellation_quota_and_unanswered_backoff(self):
        self.run_fixture(r'''
int main(void) {
    init(); uint32_t generation = pet_turn_current();pet_wake_require(true);
    autonomous(generation); assert(provider_calls == 1 && spoken == 0 && s_daily_count == 0);
    s_next_plan = 0; minute = 1380; s_voice_until = fake_now + MINUTE_US;
    assert(audio_allowed()); /* A manual voice exception permits replies, not night-time initiatives. */
    plan="{\"action\":\"speak\",\"text\":\"不该在夜间说话\",\"home_action\":\"rest\"}";
    autonomous(generation); assert(provider_calls == 2 && spoken == 0);
    assert(pet_home_take_request()==PET_HOME_REST); /* Silent planning still happens. */
    minute = 720; s_voice_until = 0; known_clock = false;
    s_next_plan=0;autonomous(generation); assert(provider_calls == 2);
    known_clock = true; cancelled = true; plan = "{\"action\":\"speak\",\"text\":\"过时的话\"}";
    autonomous(generation); assert(provider_calls == 3 && spoken == 0 && s_daily_count == 0);
    cancelled = false; s_next_plan = 0; generation = pet_turn_current();
    autonomous(generation); assert(spoken == 1 && s_daily_count == 1 && s_waiting_since == fake_now);
    assert(!pet_wake_active((uint32_t)(fake_now/1000))); /* Initiatives must not open ambient ASR. */
    fake_now += 4 * MINUTE_US; feedback_tick();
    assert(s_ignored == 1 && s_next_plan >= fake_now + 30 * MINUTE_US);
    assert(number(s_agency, "ignored", 0) == 1);
    int before = provider_calls; s_next_plan = 0; s_daily_count = s_policy.daily_limit;
    autonomous(pet_turn_current()); assert(provider_calls == before+1 && spoken==1);
    return 0;
}
''')

    def test_actual_virtual_life_survives_reboot_without_becoming_owner_fact(self):
        self.run_fixture(r'''
int main(void){
 init();pet_home_request(PET_HOME_WASH);life_tick();assert(!cJSON_GetObjectItem(s_agency,"last_virtual_life"));
 pet_home_complete(PET_HOME_WASHING);life_tick();
 assert(strstr(str(cJSON_GetObjectItem(s_agency,"last_virtual_life"),"event"),"洗漱"));
 uint32_t sequence=0;char *stored=pet_snapshot_load(AGENCY_BASE,8192,&sequence);assert(stored);
 cJSON_Delete(s_agency);s_agency=cJSON_Parse(stored);free(stored);assert(s_agency);
 char *context=system_context("");assert(context&&strstr(context,"持久虚拟生活记录")&&strstr(context,"不能据此编造现实工作"));free(context);
 assert(!outcome_successes&&!outcome_failures); /* Not an invented owner experience. */
 s_agency_writable=false;pet_home_complete(PET_HOME_WAKING);life_tick();
 assert(strstr(str(cJSON_GetObjectItem(s_agency,"last_virtual_life"),"event"),"洗漱")); /* Failed save rolls back. */
 return 0;
}
''')

    def test_reminder_persistence_cancellation_and_quiet_deferral(self):
        self.run_fixture(r'''
int main(void) {
    init(); setenv("TZ", "CST-8", 1); tzset();
    time_t later = time(NULL) + 600; struct tm local; localtime_r(&later, &local); char date[64];
    strftime(date, sizeof(date), "%Y-%m-%d %H:%M", &local);
    cJSON *reminder = cJSON_CreateObject(); cJSON_AddStringToObject(reminder, "text", "记得喝水");
    cJSON_AddStringToObject(reminder, "due", date); cJSON_AddNumberToObject(reminder, "repeat_minutes", 0);
    assert(save_reminder(reminder));
    char *listing = reminder_listing(); assert(strstr(listing, "1：") && strstr(listing, "记得喝水")); free(listing);
    assert(cancel_reminder(1)); assert(!cancel_reminder(1));
    assert(save_reminder(reminder));
    cJSON *items = cJSON_GetObjectItem(s_agency, "reminders"), *item = cJSON_GetArrayItem(items, 0);
    cJSON_SetNumberValue(cJSON_GetObjectItem(item, "due"), time(NULL) - 10);
    minute = 1380; reminders(pet_turn_current()); assert(spoken == 0 && cJSON_GetArraySize(items) == 1);
    minute = 720; reminders(pet_turn_current()); assert(spoken == 1 && cJSON_GetArraySize(items) == 0);
    cJSON_Delete(reminder); return 0;
}
''')


if __name__ == "__main__":
    unittest.main()
