#include "pet_setup.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdatomic.h>
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "freertos/task.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "pet_audio.h"
#include "pet_capture.h"
#include "pet_cloud.h"
#include "pet_face.h"
#include "pet_hardware.h"
#include "pet_secrets.h"
#include "pet_speech.h"
#include "pet_store.h"
#include "pet_birth.h"
#include "pet_turn.h"
#include "pet_util.h"
#include "pet_voice.h"
#include "pet_owner.h"
#include "pet_owner_session.h"
#ifdef ESP_PLATFORM
#include "sdkconfig.h"
#endif
#ifdef CONFIG_DESKPET_LOCAL_OWNER
#include "pet_owner_embedding.h"
#endif

static EventGroupHandle_t s_wifi;
static atomic_bool s_reconnect, s_configuring, s_prompted;
static atomic_int s_wifi_rssi=-127;
static atomic_bool s_setup_cancel, s_setup_keyboard;
#define WIFI_READY BIT0
#define WIFI_RECONFIGURE BIT1

static void configure_dns(void)
{
    esp_netif_dns_info_t original = {0}, dns = {0};
    esp_netif_get_dns_info(NULL, ESP_NETIF_DNS_MAIN, &original);
    dns.ip.type = ESP_IPADDR_TYPE_V4;
    esp_netif_str_to_ip4("223.5.5.5", &dns.ip.u_addr.ip4);
    esp_netif_set_dns_info(NULL, ESP_NETIF_DNS_MAIN, &dns);
    esp_netif_str_to_ip4("119.29.29.29", &dns.ip.u_addr.ip4);
    esp_netif_set_dns_info(NULL, ESP_NETIF_DNS_BACKUP, &dns);
    if (original.ip.u_addr.ip4.addr) esp_netif_set_dns_info(NULL, ESP_NETIF_DNS_FALLBACK, &original);
}

static void on_wifi(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START && s_reconnect) esp_wifi_connect();
    else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        atomic_store(&s_wifi_rssi,-127);
        xEventGroupClearBits(s_wifi, WIFI_READY); pet_owner_session_reset();
        if (s_reconnect) esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        configure_dns();
        xEventGroupClearBits(s_wifi, WIFI_RECONFIGURE);
        xEventGroupSetBits(s_wifi, WIFI_READY); s_prompted = false; pet_hardware_network_ready();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_LOST_IP) {
        atomic_store(&s_wifi_rssi,-127);
        xEventGroupClearBits(s_wifi, WIFI_READY); pet_owner_session_reset();
    }
}

bool pet_setup_connected(void) { return s_wifi && (xEventGroupGetBits(s_wifi) & WIFI_READY); }
pet_network_state_t pet_setup_network_state(void)
{
    bool connected=pet_setup_connected();
    return (pet_network_state_t){.connected=connected,.connecting=!connected&&(s_reconnect||s_configuring),.rssi=atomic_load(&s_wifi_rssi)};
}

/* Runs outside the cloud worker so a dead network can cancel a pending request. */
static void wifi_watch(void *arg)
{
    int64_t offline_since = -1;
    unsigned poll=0;
    while (true) {
        if(pet_setup_connected()&&poll++%5==0){
            wifi_ap_record_t ap;
            if(esp_wifi_sta_get_ap_info(&ap)==ESP_OK)atomic_store(&s_wifi_rssi,ap.rssi);
        }
        if (pet_setup_connected() || s_configuring) offline_since = -1;
        else {
            int64_t now = esp_timer_get_time();
            if (offline_since < 0) offline_since = now;
            if (!s_prompted && now - offline_since >= 30000000) {
                s_prompted = true;
                pet_audio_stop(); pet_turn_next();
                xEventGroupSetBits(s_wifi, WIFI_RECONFIGURE);
            }
        }
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

static void init_wifi(void)
{
    if (s_wifi) return;
    s_wifi = xEventGroupCreate(); assert(s_wifi);
    ESP_ERROR_CHECK(esp_netif_init()); ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t config = WIFI_INIT_CONFIG_DEFAULT(); ESP_ERROR_CHECK(esp_wifi_init(&config));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_wifi, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_wifi, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_LOST_IP, on_wifi, NULL));
    assert(xTaskCreate(wifi_watch, "pet_wifi_watch", 3072, NULL, 3, NULL) == pdPASS);
}

static void start_sta(const char *ssid, const char *password)
{
    s_reconnect = false; esp_wifi_stop(); xEventGroupClearBits(s_wifi, WIFI_READY); pet_owner_session_reset();
    wifi_config_t config = {0};
    memcpy(config.sta.ssid, ssid, strnlen(ssid, sizeof(config.sta.ssid)));
    memcpy(config.sta.password, password, strnlen(password, sizeof(config.sta.password)));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA)); ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &config));
    s_reconnect = true; ESP_ERROR_CHECK(esp_wifi_start());
}

static int connect_sta(const char *ssid, const char *password)
{
    start_sta(ssid, password);
    return (xEventGroupWaitBits(s_wifi, WIFI_READY, pdFALSE, pdTRUE, pdMS_TO_TICKS(20000)) & WIFI_READY) ? 0 : -1;
}

static int configure_once(void)
{
    init_wifi();
    s_reconnect = false; esp_wifi_stop(); ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA)); ESP_ERROR_CHECK(esp_wifi_start());
    char options[2048] = "手动输入名称";
    if (esp_wifi_scan_start(NULL, true) == ESP_OK) {
        wifi_ap_record_t records[16]; uint16_t count = 16;
        if (esp_wifi_scan_get_ap_records(&count, records) == ESP_OK) for (int i = 0; i < count; i++) {
            char ssid[33] = {0}; memcpy(ssid, records[i].ssid, 32);
            if (!ssid[0] || strchr(ssid, '\n') || strlen(options) + strlen(ssid) + 2 >= sizeof(options)) continue;
            strcat(options, "\n"); strcat(options, ssid);
        }
    }
    char ssid[80] = {0}, password[65] = {0};
    if (pet_face_choose("选择当前环境的 Wi-Fi", options, ssid, sizeof(ssid)) != 0) return -2;
    if (!strcmp(ssid, "手动输入名称") && pet_face_input("Wi-Fi 名称", "", 0, ssid, 33) != 0) return -2;
    if (strlen(ssid) > 32) return -1;
    if (pet_face_input("Wi-Fi 密码", "输入所选无线网络的密码", 1, password, sizeof(password)) != 0) return -2;
    pet_face_set("连", "正在连接这个网络");
    int result = connect_sta(ssid, password);
    if (result == 0) pet_store_save_wifi(ssid, password);
    memset(password, 0, sizeof(password));
    return result;
}

int pet_setup_wifi_configure(void)
{
    pet_owner_session_reset();
    s_configuring = true; init_wifi();
    xEventGroupClearBits(s_wifi, WIFI_RECONFIGURE);
    pet_audio_stop(); pet_turn_next(); pet_capture_discard();
    int result;
    while ((result = configure_once()) != 0) {
        if (result == -2) break;
        char choice[64];
        if (pet_face_choose("还没连上网络", "重新配网\n暂时离线", choice, sizeof(choice)) != 0 || !strcmp(choice, "暂时离线")) break;
    }
    if (result != 0) {
        /* A cancelled/failed new network must not replace the saved working one. */
        char ssid[33] = {0}, password[65] = {0};
        if (pet_store_load_wifi(ssid, sizeof(ssid), password, sizeof(password)) == 0) start_sta(ssid, password);
        memset(password, 0, sizeof(password));
        s_prompted = true; /* Respect "offline" until a connection actually returns. */
        pet_face_set("在这儿", "先离线陪着你。设置里随时可以重新配网。");
    }
    pet_capture_discard(); pet_turn_next(); s_configuring = false;
    return result == 0 ? 0 : -1;
}

void pet_setup_wifi_poll(void)
{
    if (!s_wifi || !(xEventGroupGetBits(s_wifi) & WIFI_RECONFIGURE)) return;
    xEventGroupClearBits(s_wifi, WIFI_RECONFIGURE);
    if (pet_setup_connected()) return;
    pet_face_set("换个网络", "原来的网络连不上了，选一个这里的 Wi-Fi 吧。");
    pet_setup_wifi_configure();
}

void pet_setup_wifi(void)
{
    s_configuring = true; init_wifi();
    char ssid[33] = {0}, password[65] = {0};
    if (pet_store_load_wifi(ssid, sizeof(ssid), password, sizeof(password)) == 0) {
        pet_face_set("连", "正在找网络");
        int result = connect_sta(ssid, password); memset(password, 0, sizeof(password));
        if (result == 0) { s_configuring = false; return; }
        pet_face_set("换个网络", "原来的网络连不上了，重新配一下网络吧。");
    }
    pet_setup_wifi_configure();
}

int pet_setup_keys(bool force)
{
#ifdef CONFIG_DESKPET_REMOTE_BRAIN
    if(force)pet_face_set("主机管理模型", "模型服务和密钥由小主机管理，这里无需填写。");
    return 0;
#endif
    char deepseek[240], minimax[240];
    pet_utf8_copy(deepseek, sizeof(deepseek), pet_secrets_deepseek());
    pet_utf8_copy(minimax, sizeof(minimax), pet_secrets_minimax());
    if (minimax[0] && !force) return 0;
    if (force) {
        char input[240] = {0};
        if (pet_face_input("设置 DeepSeek", "留空保留当前 API key", 1, input, sizeof(input)) != 0) return -1;
        if (input[0]) pet_utf8_copy(deepseek, sizeof(deepseek), input);
        memset(input, 0, sizeof(input));
        if (pet_face_input("设置 MiniMax", "留空保留当前 API key", 1, input, sizeof(input)) != 0) { memset(deepseek, 0, sizeof(deepseek)); return -1; }
        if (input[0]) pet_utf8_copy(minimax, sizeof(minimax), input);
        memset(input, 0, sizeof(input));
    }
    if (!minimax[0] && (pet_face_input("设置 MiniMax", "输入 API key，只保存在这块板子", 1, minimax, sizeof(minimax)) != 0 || !minimax[0])) {
        memset(deepseek, 0, sizeof(deepseek)); return -1;
    }
    int result = pet_secrets_save(deepseek, minimax);
    memset(deepseek, 0, sizeof(deepseek)); memset(minimax, 0, sizeof(minimax)); return result;
}

void pet_setup_cancel(void) { s_setup_cancel = true; pet_audio_stop(); pet_turn_next(); }

void pet_setup_keyboard(void) { s_setup_keyboard = true; pet_audio_stop(); pet_turn_next(); }

static bool wait_utterance(pet_utterance_t *utterance)
{
    while (!s_setup_cancel && !s_setup_keyboard && pet_setup_connected()) {
        if (pet_capture_take(utterance, pdMS_TO_TICKS(100))) return true;
    }
    return false;
}

static int ask(const char *question, char *answer, int capacity, int16_t *speaker, int speaker_capacity)
{
    if (s_setup_cancel) return -1;
    s_setup_keyboard = false;
    pet_face_birth_input(1);
    int outcome = -1;
    uint32_t generation = pet_turn_current(); pet_cloud_begin_turn(generation);
    pet_speech_say(question, generation, speaker, speaker_capacity);
    pet_face_set("等你开口", question);
    while (!s_setup_cancel && !s_setup_keyboard && pet_setup_connected()) {
        pet_utterance_t utterance;
        if (!wait_utterance(&utterance)) break;
        if (!pet_turn_valid(utterance.generation) || utterance.too_long) {
            free(utterance.pcm);
            pet_face_set("再说一次", "刚才没有完整听清，请再说一次。"); continue;
        }
        pet_cloud_begin_turn(utterance.generation);
        bool usable = pet_owner_conversation_accept(utterance.pcm, utterance.samples, utterance.generation);
        if (!pet_turn_valid(utterance.generation)) { free(utterance.pcm); continue; }
        if (!usable) {
            free(utterance.pcm);
            pet_face_set("请再说一句", pet_owner_session_hint()); continue;
        }
        pet_face_set("听清内容", "正在听清你说的话。");
        answer[0] = 0;
        int result = pet_cloud_transcribe(utterance.pcm, utterance.samples, answer, capacity);
        free(utterance.pcm);
        if (result == 0 && answer[0] && pet_turn_valid(utterance.generation)) { pet_owner_session_activity(); outcome = 0; break; }
        pet_face_set("再说一次", "语音内容暂时没有识别成功，请再说一次，或稍后用屏幕输入。");
    }
    pet_face_birth_input(0);
    if (s_setup_cancel || !pet_setup_connected()) return -1;
    if (s_setup_keyboard) return pet_face_input("屏幕输入", question, 0, answer, capacity);
    return outcome;
}

int pet_setup_soul(int16_t *mic, int mic_capacity, int16_t *speaker, int speaker_capacity)
{
    if (!pet_owner_locked()) return -1;
    s_setup_cancel = false;
    if (pet_store_has_soul() && !pet_store_identity_needs_review()) return 0;
    pet_birth_t birth; pet_birth_init(&birth);
    cJSON *legacy = pet_store_identity_legacy();
    char answer[1536] = "", question[384] = "", summary[2600];
    int outcome = -1;
    while (!s_setup_cancel && pet_setup_connected()) {
        uint32_t generation = pet_turn_current();
        pet_cloud_begin_turn(generation);
        pet_face_set("想", "我在理解你的意思，请稍等。");
        /* Understanding cannot be cancelled by room noise; capture resumes
         * for the next spoken question. Menus still cancel via generation. */
        pet_capture_pause_turns(true); pet_capture_discard();
        char *request = pet_birth_request(&birth, answer, legacy);
#ifdef CONFIG_DESKPET_REMOTE_BRAIN
        char *reply = request ? pet_cloud_birth(pet_birth_prompt(), request) : NULL;
#else
        char *reply = request ? pet_cloud_minimax(pet_birth_prompt(), request, true) : NULL;
#endif
        free(request);
        int result = reply && pet_turn_valid(generation) && !s_setup_cancel ?
            pet_birth_apply(&birth, reply, question, sizeof(question)) : -1;
        free(reply); pet_capture_pause_turns(false);
        if (s_setup_cancel || !pet_setup_connected()) break;
        if (result < 0) {
            char choice[48];
            if (pet_face_choose("这次还没理解清楚", "重试理解\n稍后再说", choice, sizeof(choice)) != 0 ||
                strcmp(choice, "重试理解")) break;
            continue; /* Keep the same answer; never save raw fallback text. */
        }
        cJSON_Delete(legacy); legacy = NULL;
        if (result == 1) {
            cJSON *identity = pet_birth_identity(&birth);
            if (!identity) break;
            pet_birth_summary(identity, summary, sizeof(summary));
            pet_face_set("我们的约定", summary);
            if (pet_face_confirm("这是我理解的意思，向下滑动看全文", summary) != 0) {
                cJSON_Delete(identity);
                if (s_setup_cancel) break;
                pet_birth_free(&birth); pet_birth_init(&birth); answer[0] = 0; continue;
            }
            outcome = pet_store_write_identity(identity);
            if (!outcome) {
                cJSON *creature = cJSON_GetObjectItem(identity, "creature");
                pet_face_identity(cJSON_IsString(creature) ? creature->valuestring : "桌宠");
                pet_face_set("在这儿", "约定记好了，其他的我们慢慢认识。");
            } else pet_face_set("在这儿", "这次没有保存成功，约定还没写好。");
            cJSON_Delete(identity); break;
        }
        answer[0] = 0;
        if (ask(question, answer, sizeof(answer), speaker, speaker_capacity) != 0) break;
    }
    pet_capture_pause_turns(false); cJSON_Delete(legacy); pet_birth_free(&birth); return outcome;
}

static int record_owner(const char *prompt, pet_utterance_t *utterance, int16_t *speaker, int capacity, int sample)
{
    if (s_setup_cancel) return -1;
    pet_capture_pause_turns(true);
    pet_capture_discard(); pet_cloud_begin_turn(pet_turn_current());
    pet_face_owner_prompt(sample, prompt);
#ifndef CONFIG_DESKPET_LOCAL_OWNER
    char spoken[384]; snprintf(spoken, sizeof(spoken), "请读屏幕上的这句话。%s", prompt);
    pet_speech_say(spoken, pet_turn_current(), speaker, capacity);
#else
    (void)speaker; (void)capacity;
#endif
    pet_capture_discard(); pet_capture_pause_turns(false);
    pet_face_set("请读这一句", "用正常速度读完，读完后停约 2 秒。");
    pet_face_owner_recording(sample);
    ESP_LOGI("pet_setup", "owner recording ready (%d/4)", sample);
    /* Registration is a visible, cancellable conversation, not a 45-second
     * window that silently stops accepting the owner's voice. */
    while (!s_setup_cancel && pet_setup_connected()) {
        if (!pet_capture_take(utterance, pdMS_TO_TICKS(100))) continue;
        pet_voice_stats_t stats = pet_voice_stats(utterance->pcm, utterance->samples);
        ESP_LOGI("pet_setup", "owner clip stats: ms=%d rms=%d clipped=%d/1000 active_ms=%d valid_turn=%d too_long=%d",
                 utterance->samples * 1000 / PET_SAMPLE_RATE, (int)stats.rms, stats.clipped_permille, stats.active_ms,
                 pet_turn_valid(utterance->generation), utterance->too_long);
        bool valid = pet_turn_valid(utterance->generation) && !utterance->too_long &&
            utterance->samples >= PET_SAMPLE_RATE * 3 && utterance->samples <= PET_SAMPLE_RATE *
#ifdef CONFIG_DESKPET_LOCAL_OWNER
            12 &&
#else
            6 &&
#endif
            pet_voice_usable(utterance->pcm, utterance->samples);
        if (valid) {
            pet_capture_pause_turns(true);
            ESP_LOGI("pet_setup", "owner clip accepted: %d ms", utterance->samples * 1000 / PET_SAMPLE_RATE);
            pet_face_owner_recording(0);
            pet_face_set("核验这一段", "听到了，正在确认声音。请稍等。");
            pet_cloud_begin_turn(utterance->generation); return 0;
        }
        const char *reason = !pet_turn_valid(utterance->generation) ? "刚才被新声音打断了，请再读一次。" :
                             utterance->too_long ? "刚才有点长，请读一句后停下来。" :
                             utterance->samples > PET_SAMPLE_RATE *
#ifdef CONFIG_DESKPET_LOCAL_OWNER
                             12
#else
                             6
#endif
                             ? "刚才有点长，请读一句后停下来。" :
                             utterance->samples < PET_SAMPLE_RATE * 3 ? "刚才有点短，请连续说 3到5 秒。" :
                             stats.rms > 14000 || stats.clipped_permille >= 10 ? "声音太响或失真，请稍微离远一点。" :
                             stats.rms < 180 ? "声音偏小，请靠近一些正常说话。" : "有效人声不足，请完整读出这句话。";
        free(utterance->pcm); utterance->pcm = NULL;
        ESP_LOGI("pet_setup", "owner clip rejected; waiting for the same sample");
        pet_face_set("再试这一段", reason);
    }
    pet_capture_pause_turns(false); pet_face_owner_recording(0); return -1;
}

static bool confirm_current_owner(int16_t *speaker, int capacity)
{
    pet_owner_session_reset();
    pet_utterance_t u;
    if (record_owner("这是我原来的声音，我想重新确认我们的约定。", &u, speaker, capacity, 0) != 0) { pet_face_owner_end(); return false; }
    float score = pet_owner_verify(u.pcm, u.samples); free(u.pcm);
    pet_capture_pause_turns(false);
    pet_face_owner_end();
    return score >= PET_OWNER_THRESHOLD;
}

int pet_setup_voice_keys(int16_t *speaker, int capacity)
{
#ifdef CONFIG_DESKPET_LOCAL_OWNER
    (void)speaker; (void)capacity;
    pet_face_set("本地声纹测试", "声音在这块板子上核验，不需要配置声纹服务。可在设置里重新录入主人声音。");
    return -1;
#endif
    s_setup_cancel = false;
    if (pet_owner_locked() && !confirm_current_owner(speaker, capacity)) {
        pet_face_set("没有更改", "需要原主人声音通过验证，才能更改声纹服务。"); return -1;
    }
    char app[240] = {0}, key[240] = {0}, secret[240] = {0}; int result = -1;
    if (pet_face_input("讯飞声纹 APPID", "新版声纹识别服务的 APPID", 1, app, sizeof(app)) == 0 && app[0] &&
        pet_face_input("讯飞声纹 APIKey", "这不是 Wi-Fi 密码", 1, key, sizeof(key)) == 0 && key[0] &&
        pet_face_input("讯飞声纹 APISecret", "只存入这块板子的服务设置", 1, secret, sizeof(secret)) == 0 && secret[0])
        result = pet_secrets_save_xfyun(app, key, secret);
    memset(app, 0, sizeof(app)); memset(key, 0, sizeof(key)); memset(secret, 0, sizeof(secret)); return result;
}

int pet_setup_voice(int16_t *speaker, int capacity, bool force)
{
    s_setup_cancel = false;
    if (pet_owner_locked() && !force) return 0;
    if (!pet_owner_storage_ok()) {
        ESP_LOGW("pet_setup", "owner storage incompatible or unreadable; preserving files");
        pet_face_set("主人记录需要检查", "声纹记录无法读取，我保留了原文件，没有替换主人。"); return -1;
    }
#ifdef CONFIG_DESKPET_LOCAL_OWNER
    pet_face_set("本地声纹自检", "正在检查板上的声音模型，请稍等。");
    if (!pet_owner_embedding_prepare()) {
        pet_face_set("本地声纹尚未就绪", "模型自检或内存检查未通过，没有更改主人。请稍后重试。"); return -1;
    }
#endif
    if (!pet_owner_configured()) {
        pet_cloud_begin_turn(pet_turn_current());
        pet_speech_say("先认识主人的声音。请在设置里配置讯飞声纹服务，再来录入。", pet_turn_current(), speaker, capacity);
        pet_face_set("先锁定主人声音", "请在设置里配置声纹服务。录入并复验通过后，再设置我的名字和性格。"); return -1;
    }
    if (pet_owner_locked() && !confirm_current_owner(speaker, capacity)) return -1;
    const char *prompts[] = {"我正在和桌宠认识，今天的声音就是我。", "我喜欢自然的交流，我们可以慢慢熟悉。", "请记住我的声音，以后我会常常来看你。"};
    int taken = 0;
    for (int attempts = 0; taken < 3 && attempts < 8 && !s_setup_cancel; attempts++) {
        pet_utterance_t u;
        if (record_owner(prompts[taken], &u, speaker, capacity, taken + 1) != 0) break;
        int result = taken ? pet_owner_add_sample(u.pcm, u.samples) : pet_owner_stage(u.pcm, u.samples);
        free(u.pcm);
        if (result != 0) {
            int error = pet_owner_error_code();
#ifdef CONFIG_DESKPET_LOCAL_OWNER
            if (error == 0 && !s_setup_cancel) {
                pet_capture_pause_turns(false);
                pet_face_set("这一段没对上", "请保持正常语速，再读同一句。之前通过的段落会保留。");
                continue;
            }
#endif
            ESP_LOGI("pet_setup", "owner enrollment failed: code=%d", error);
            pet_owner_abort(); pet_capture_pause_turns(false); pet_face_owner_end();
            char message[240];
#ifdef CONFIG_DESKPET_LOCAL_OWNER
            snprintf(message, sizeof(message), "本地声纹运算没有完成，没有保存新主人。请稍后在设置里重试。");
#else
            if (error > 0) snprintf(message, sizeof(message), "声纹服务返回错误 %d，没有保存新主人。", error);
            else snprintf(message, sizeof(message), "%s", error < 0 ? "声纹请求没有完成，没有保存新主人。" : "这几段声音还没通过同一人核验，没有保存新主人。");
#endif
            pet_face_set("还没锁定", message); return -1;
        }
        taken++;
        ESP_LOGI("pet_setup", "owner enrollment accepted (%d/3)", taken);
    }
    if (taken != 3) { pet_owner_abort(); pet_capture_pause_turns(false); pet_face_owner_end(); pet_face_set("还没锁定", "声音录入没有完成，原来的主人设置没有更改。"); return -1; }
    pet_utterance_t u;
    if (record_owner("今天我坐在桌边，想和你聊聊身边的小事。", &u, speaker, capacity, 4) != 0) { pet_owner_abort(); pet_capture_pause_turns(false); pet_face_owner_end(); return -1; }
    float score = pet_owner_verify_candidate(u.pcm, u.samples); free(u.pcm);
    if (score < PET_OWNER_THRESHOLD || pet_owner_commit() != 0) {
        pet_owner_abort(); pet_capture_pause_turns(false); pet_face_owner_end(); pet_face_set("还没锁定", "复验没有通过，没有保存新主人。可以稍后重新录入。"); return -1;
    }
    pet_capture_pause_turns(false); pet_face_owner_end();
    pet_owner_session_begin();
    pet_face_set("主人声音已保存", "复验通过了。接下来认识我是谁。"); return 0;
}
