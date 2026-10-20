"""Replay network changes against the actual setup worker and watchdog."""
import unittest
import test_runtime_core

SDK = r'''
#pragma once
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#define ESP_OK 0
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
#define ESP_ERROR_CHECK(x) assert((x) == 0)
#define BIT0 1
#define BIT1 2
#define pdFALSE 0
#define pdTRUE 1
#define pdPASS 1
#define pdMS_TO_TICKS(x) (x)
typedef uint32_t TickType_t;
typedef unsigned EventBits_t;
typedef void *EventGroupHandle_t;
typedef const void *esp_event_base_t;
#define WIFI_EVENT ((esp_event_base_t)1)
#define IP_EVENT ((esp_event_base_t)2)
#define WIFI_EVENT_STA_START 1
#define WIFI_EVENT_STA_DISCONNECTED 2
#define IP_EVENT_STA_GOT_IP 3
#define IP_EVENT_STA_LOST_IP 4
#define ESP_EVENT_ANY_ID -1
#define WIFI_STORAGE_RAM 0
#define WIFI_MODE_STA 0
#define WIFI_IF_STA 0
#define ESP_IPADDR_TYPE_V4 0
#define ESP_NETIF_DNS_MAIN 0
#define ESP_NETIF_DNS_BACKUP 1
#define ESP_NETIF_DNS_FALLBACK 2
typedef struct { struct { int type; union { struct { uint32_t addr; } ip4; } u_addr; } ip; } esp_netif_dns_info_t;
int esp_netif_get_dns_info(void *, int, esp_netif_dns_info_t *);
int esp_netif_set_dns_info(void *, int, esp_netif_dns_info_t *);
int esp_netif_str_to_ip4(const char *, void *);
typedef struct { int unused; } wifi_init_config_t;
#define WIFI_INIT_CONFIG_DEFAULT() ((wifi_init_config_t){0})
typedef struct { struct { uint8_t ssid[32], password[64]; } sta; } wifi_config_t;
typedef struct { uint8_t ssid[33]; int8_t rssi; } wifi_ap_record_t;
EventGroupHandle_t xEventGroupCreate(void);
EventBits_t xEventGroupGetBits(EventGroupHandle_t);
EventBits_t xEventGroupSetBits(EventGroupHandle_t, EventBits_t);
EventBits_t xEventGroupClearBits(EventGroupHandle_t, EventBits_t);
EventBits_t xEventGroupWaitBits(EventGroupHandle_t, EventBits_t, int, int, TickType_t);
int xTaskCreate(void (*)(void *), const char *, unsigned, void *, unsigned, void *);
void vTaskDelay(TickType_t);
int64_t esp_timer_get_time(void);
int esp_netif_init(void);
int esp_event_loop_create_default(void);
void *esp_netif_create_default_wifi_sta(void);
int esp_event_handler_register(esp_event_base_t, int, void (*)(void *, esp_event_base_t, int32_t, void *), void *);
int esp_wifi_init(const wifi_init_config_t *);
int esp_wifi_set_storage(int);
int esp_wifi_stop(void);
int esp_wifi_start(void);
int esp_wifi_connect(void);
int esp_wifi_set_mode(int);
int esp_wifi_set_config(int, const wifi_config_t *);
int esp_wifi_scan_start(void *, bool);
int esp_wifi_scan_get_ap_records(uint16_t *, wifi_ap_record_t *);
int esp_wifi_sta_get_ap_info(wifi_ap_record_t *);
'''

FIXTURE = r'''
#include <setjmp.h>
#include "pet_setup.c"
static unsigned bits;
static int64_t now;
static int saved, choices, stops, waits, ticks, stop_tick;
static bool saved_exists = true, accept_new = true, cancel_form, reconnect_briefly;
static int capture_mode, capture_polls, owner_sample;
static int owner_checks, cloud_checks, spoken_prompts, manual_inputs;
static bool reject_first, cloud_fail_once, owner_registered;
static float owner_score = -1;
static char selected[33], stored[33] = "old-network";
static jmp_buf watch_done;
EventGroupHandle_t xEventGroupCreate(void) { return (void *)1; }
EventBits_t xEventGroupGetBits(EventGroupHandle_t g) { return bits; }
EventBits_t xEventGroupSetBits(EventGroupHandle_t g, EventBits_t b) { return bits |= b; }
EventBits_t xEventGroupClearBits(EventGroupHandle_t g, EventBits_t b) { unsigned old = bits; bits &= ~b; return old; }
EventBits_t xEventGroupWaitBits(EventGroupHandle_t g, EventBits_t b, int c, int a, TickType_t t) {
    waits++; now += t * 1000LL;
    if (accept_new && !strcmp(selected, "new-network")) on_wifi(NULL, IP_EVENT, IP_EVENT_STA_GOT_IP, NULL);
    return bits;
}
int xTaskCreate(void (*f)(void *), const char *n, unsigned z, void *a, unsigned p, void *h) { return pdPASS; }
void vTaskDelay(TickType_t t) {
    now += t * 1000LL; ticks++;
    if (reconnect_briefly && ticks == 5) on_wifi(NULL, IP_EVENT, IP_EVENT_STA_GOT_IP, NULL);
    if (reconnect_briefly && ticks == 10) on_wifi(NULL, WIFI_EVENT, WIFI_EVENT_STA_DISCONNECTED, NULL);
    if (ticks == 30) assert(!(bits & WIFI_RECONFIGURE));
    if (ticks >= stop_tick) longjmp(watch_done, 1);
}
int64_t esp_timer_get_time(void) { return now; }
int esp_netif_init(void) { return 0; }
int esp_netif_get_dns_info(void *n,int type,esp_netif_dns_info_t *dns) { dns->ip.u_addr.ip4.addr=1;return 0; }
int esp_netif_set_dns_info(void *n,int type,esp_netif_dns_info_t *dns) { assert(dns->ip.u_addr.ip4.addr);return 0; }
int esp_netif_str_to_ip4(const char *s,void *p) { *(uint32_t *)p=2;return 0; }
int esp_event_loop_create_default(void) { return 0; }
void *esp_netif_create_default_wifi_sta(void) { return (void *)1; }
int esp_event_handler_register(esp_event_base_t b, int i, void (*f)(void *, esp_event_base_t, int32_t, void *), void *a) { return 0; }
int esp_wifi_init(const wifi_init_config_t *c) { return 0; }
int esp_wifi_set_storage(int m) { return 0; }
int esp_wifi_stop(void) { bits &= ~WIFI_READY; return 0; }
int esp_wifi_start(void) { on_wifi(NULL, WIFI_EVENT, WIFI_EVENT_STA_START, NULL); return 0; }
int esp_wifi_connect(void) { return 0; }
int esp_wifi_set_mode(int m) { return 0; }
int esp_wifi_set_config(int m, const wifi_config_t *c) { memcpy(selected, c->sta.ssid, 32); selected[32] = 0; return 0; }
int esp_wifi_scan_start(void *c, bool wait) { return 0; }
int esp_wifi_scan_get_ap_records(uint16_t *n, wifi_ap_record_t *r) { *n = 1; strcpy((char *)r[0].ssid, "new-network"); return 0; }
int esp_wifi_sta_get_ap_info(wifi_ap_record_t *r){r->rssi=-68;return 0;}
void pet_hardware_network_ready(void) {}
void pet_audio_stop(void) { stops++; }
void pet_capture_discard(void) {}
void pet_capture_pause_turns(bool paused) {}
bool pet_capture_take(pet_utterance_t *u, TickType_t t) {
    if (!capture_mode) return false;
    if (capture_mode == 5 && owner_checks >= 4) {pet_setup_keyboard();return false;}
    if (capture_mode == 4 || capture_mode == 5) {
        u->pcm=calloc(24000,sizeof(int16_t));u->samples=24000;
        u->generation=pet_turn_current();u->too_long=false;return true;
    }
    now += t * 1000LL; capture_polls++;
    if (capture_mode == 2 && capture_polls == 2) pet_setup_cancel();
    if (capture_mode == 3 && capture_polls == 2) bits &= ~WIFI_READY;
    if (capture_mode == 1 && (capture_polls == 2 || capture_polls == 510)) {
        u->pcm=calloc(48000,sizeof(int16_t));u->samples=capture_polls==2 ? 16000 : 48000;
        u->generation=pet_turn_current();u->too_long=false;return true;
    }
    return false;
}
void pet_face_set(const char *p, const char *t) {}
void pet_face_birth_input(int visible) {}
void pet_face_owner_recording(int sample) {owner_sample=sample;}
void pet_face_owner_prompt(int sample,const char *phrase) {assert(phrase && phrase[0]);}
void pet_face_owner_end(void) {}
void pet_face_identity(const char *c) {}
int pet_face_choose(const char *title, const char *options, char *out, int n) {
    choices++;
    if (strstr(options, "暂时离线")) { snprintf(out, n, "暂时离线"); return 0; }
    if (cancel_form) return -1;
    snprintf(out, n, "new-network"); return 0;
}
int pet_face_input(const char *title, const char *hint, int secret, char *out, int n) { manual_inputs++; snprintf(out, n, "example"); return 0; }
int pet_face_confirm(const char *a, const char *b) { return -1; }
int pet_store_load_wifi(char *ssid, int n, char *password, int p) {
    if (!saved_exists) return -1;
    snprintf(ssid, n, "%s", stored); snprintf(password, p, "example"); return 0;
}
void pet_store_save_wifi(const char *ssid, const char *password) { saved++; snprintf(stored, sizeof(stored), "%s", ssid); }
int pet_store_has_soul(void) { return 1; }
bool pet_store_identity_needs_review(void) { return false; }
cJSON *pet_store_identity_legacy(void) { return NULL; }
int pet_store_write_identity(const cJSON *identity) { return 0; }
char *pet_cloud_minimax(const char *system, const char *request, bool reflection) { return NULL; }
const char *pet_secrets_deepseek(void) { return ""; }
const char *pet_secrets_minimax(void) { return ""; }
int pet_secrets_save_xfyun(const char *a,const char *b,const char *c) { return 0; }
bool pet_owner_locked(void) { return owner_registered; }
bool pet_owner_configured(void) { return false; }
float pet_owner_verify(const int16_t *p,int n) { owner_checks++; return reject_first && owner_checks==1 ? -1 : owner_score; }
float pet_owner_verify_candidate(const int16_t *p,int n) { return -1; }
int pet_owner_stage(const int16_t *p,int n) { return -1; }
int pet_owner_add_sample(const int16_t *p,int n) { return -1; }
bool pet_owner_storage_ok(void) { return true; }
int pet_owner_error_code(void) {return -1;}
int pet_owner_commit(void) { return -1; }
void pet_owner_abort(void) {}
int pet_secrets_save(const char *a, const char *b) { return 0; }
void pet_cloud_begin_turn(uint32_t g) {}
int pet_cloud_transcribe(const int16_t *p, int n, char *o, int z) {
    cloud_checks++; assert(o[0]==0);
    if(cloud_fail_once && cloud_checks==1)return -1;
    snprintf(o,z,"chosen-name");return 0;
}
int pet_speech_say(const char *t, uint32_t g, int16_t *p, int n) { spoken_prompts++;return -1; }
int pet_voice_has(void) { return 1; }
bool pet_voice_reply_usable(const int16_t *p,int n) { return p && n>=4000; }
bool pet_voice_usable(const int16_t *p, int n) { return p && n>=12000; }
pet_voice_stats_t pet_voice_stats(const int16_t *p,int n) {return (pet_voice_stats_t){.rms=1000,.active_ms=n/16};}
void pet_voice_measure(const int16_t *p, int n, float *b) {}
void pet_voice_save(const float *b) {}
static void run_watch(int n) { ticks = 0; stop_tick = n; if (setjmp(watch_done) == 0) wifi_watch(NULL); }
'''


class WifiHostTests(unittest.TestCase):
    def test_badge_state_tracks_real_ip_loss_reconnect_and_cached_signal(self):
        self.run_fixture(r'''
int main(void){
 init_wifi();s_reconnect=false;s_configuring=false;
 pet_network_state_t s=pet_setup_network_state();assert(!s.connected&&!s.connecting&&s.rssi==-127);
 s_reconnect=true;assert(pet_setup_network_state().connecting);
 on_wifi(NULL,IP_EVENT,IP_EVENT_STA_GOT_IP,NULL);run_watch(2);
 s=pet_setup_network_state();assert(s.connected&&!s.connecting&&s.rssi==-68);
 on_wifi(NULL,IP_EVENT,IP_EVENT_STA_LOST_IP,NULL);
 s=pet_setup_network_state();assert(!s.connected&&s.connecting&&s.rssi==-127);
 return 0;
}
''')
    def test_owner_replacement_still_requires_fresh_successful_voice_match(self):
        self.run_fixture(r'''
int main(void) {
 init_wifi();bits|=WIFI_READY;owner_registered=true;capture_mode=1;
 owner_score=-1;pet_owner_session_begin();
 assert(!confirm_current_owner(NULL,0) && owner_checks==1);
 capture_polls=0;owner_score=PET_OWNER_THRESHOLD;
 assert(confirm_current_owner(NULL,0) && owner_checks==2);
 return 0;
}
''')

    def run_fixture(self, body):
        headers = {"wifi_test_sdk.h": SDK}
        for name in ("esp_event.h", "esp_netif.h", "esp_wifi.h", "esp_timer.h", "esp_log.h", "freertos/task.h",
                     "freertos/FreeRTOS.h", "freertos/event_groups.h"):
            headers[name] = '#include "wifi_test_sdk.h"\n'
        test_runtime_core.RuntimeCoreTests.run_c(self, FIXTURE + body, ["pet_util", "pet_turn", "pet_owner_session", "pet_birth"], headers)

    def test_birth_retries_transcription_without_identity_challenge_or_repeated_prompt(self):
        self.run_fixture(r''' 
int main(void) {
    init_wifi();bits|=WIFI_READY;owner_registered=true;capture_mode=4;reject_first=true;cloud_fail_once=true;owner_score=PET_OWNER_THRESHOLD;
    char answer[96]="stale";
    assert(ask("question",answer,sizeof(answer),NULL,0)==0);
    assert(!strcmp(answer,"chosen-name"));
    assert(owner_checks==0 && cloud_checks==2 && spoken_prompts==1 && manual_inputs==0);
    pet_owner_session_reset();reject_first=false;cloud_fail_once=false;owner_score=-1;capture_mode=5;owner_checks=cloud_checks=spoken_prompts=0;
    assert(ask("question",answer,sizeof(answer),NULL,0)==0);
    assert(owner_checks==0 && cloud_checks==1 && spoken_prompts==1 && manual_inputs==0);
    s_setup_cancel=true;
    assert(ask("question",answer,sizeof(answer),NULL,0)==-1 && manual_inputs==0);
    return 0;
}
''')

    def test_birth_waits_past_45_seconds_and_leaves_on_cancel_or_network_loss(self):
        self.run_fixture(r'''
int main(void) {
    init_wifi();bits|=WIFI_READY;capture_mode=1;
    pet_utterance_t u={0};assert(wait_utterance(&u));free(u.pcm);
    assert(wait_utterance(&u));free(u.pcm);assert(now>45000000 && capture_polls==510);
    capture_mode=2;capture_polls=0;assert(!wait_utterance(&u) && s_setup_cancel);
    s_setup_cancel=false;capture_mode=3;capture_polls=0;assert(!wait_utterance(&u) && !pet_setup_connected());
    return 0;
}
''')

    def test_owner_recording_waits_past_45_seconds_and_remains_cancellable(self):
        self.run_fixture(r'''
int main(void) {
    init_wifi();bits|=WIFI_READY;capture_mode=1;
    pet_utterance_t u={0};
    assert(record_owner("prompt",&u,NULL,0,1)==0);
    assert(now>45000000 && capture_polls==510 && u.samples==48000 && owner_sample==0);
    free(u.pcm);assert(!s_setup_cancel);
    capture_mode=2;capture_polls=0;
    assert(record_owner("prompt",&u,NULL,0,2)==-1 && s_setup_cancel && owner_sample==0);
    s_setup_cancel=false;capture_mode=3;capture_polls=0;
    assert(record_owner("prompt",&u,NULL,0,3)==-1 && !pet_setup_connected() && owner_sample==0);
    return 0;
}
''')

    def test_boot_missing_saved_network_opens_setup_and_saves_only_success(self):
        self.run_fixture(r'''
int main(void) {
    pet_setup_wifi();
    assert(waits == 2 && choices == 1 && saved == 1);
    assert(pet_setup_connected() && !strcmp(stored, "new-network") && !s_configuring);
    return 0;
}
''')

    def test_transient_outage_recovers_sustained_outage_cancels_and_prompts(self):
        self.run_fixture(r'''
int main(void) {
    init_wifi(); reconnect_briefly = true; uint32_t old = pet_turn_current();
    run_watch(41);
    assert(bits & WIFI_RECONFIGURE); assert(!pet_turn_valid(old) && stops == 1);
    pet_setup_wifi_poll(); assert(choices == 1 && saved == 1 && pet_setup_connected());
    assert(!(bits & WIFI_RECONFIGURE));
    /* Reconnection clears a queued prompt before the UI consumes it. */
    bits |= WIFI_RECONFIGURE; on_wifi(NULL, IP_EVENT, IP_EVENT_STA_GOT_IP, NULL);
    pet_setup_wifi_poll(); assert(choices == 1);
    return 0;
}
''')

    def test_cancel_or_bad_password_retains_previous_network_without_repeated_popups(self):
        self.run_fixture(r'''
int main(void) {
    init_wifi(); accept_new = false;
    assert(pet_setup_wifi_configure() == -1);
    assert(saved == 0 && !strcmp(stored, "old-network") && !strcmp(selected, "old-network"));
    assert(s_prompted && !s_configuring && s_reconnect);
    run_watch(40); assert(!(bits & WIFI_RECONFIGURE));
    cancel_form = true; int before = choices; assert(pet_setup_wifi_configure() == -1);
    assert(choices == before + 1); /* Cancel exits immediately, without another dialog. */
    assert(saved == 0 && !strcmp(stored, "old-network"));
    on_wifi(NULL, IP_EVENT, IP_EVENT_STA_GOT_IP, NULL); assert(!s_prompted);
    on_wifi(NULL, IP_EVENT, IP_EVENT_STA_LOST_IP, NULL); assert(!pet_setup_connected());
    reconnect_briefly = false; run_watch(31); assert(bits & WIFI_RECONFIGURE);
    return 0;
}
''')


if __name__ == "__main__":
    unittest.main()
