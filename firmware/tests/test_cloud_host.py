"""Exercise actual cloud request/parser code without network or credentials."""
import unittest
import test_runtime_core

HTTP_SDK = r'''
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_HTTP_EAGAIN 2
#define HTTP_METHOD_POST 1
#define HTTP_EVENT_ON_DATA 1
#define HTTP_EVENT_ON_CONNECTED 2
#define ESP_TLS_ERR_SSL_WANT_READ -0x6900
#define ESP_TLS_ERR_SSL_WANT_WRITE -0x6880
typedef void *esp_http_client_handle_t;
typedef struct { int event_id, data_len; void *data, *user_data; } esp_http_client_event_t;
typedef struct {
    const char *url; int timeout_ms; bool is_async;
    int (*crt_bundle_attach)(void *);
    esp_err_t (*event_handler)(esp_http_client_event_t *);
    void *user_data; int buffer_size, buffer_size_tx;
} esp_http_client_config_t;
void *esp_http_client_init(const esp_http_client_config_t *);
int esp_http_client_set_method(void *, int);
int esp_http_client_set_header(void *, const char *, const char *);
int esp_http_client_set_post_field(void *, const void *, int);
int esp_http_client_set_url(void *,const char *);
int esp_http_client_set_user_data(void *,void *);
int esp_http_client_delete_header(void *,const char *);
int esp_http_client_perform(void *);
int esp_http_client_open(void *, int);
int esp_http_client_write(void *, const char *, int);
int64_t esp_http_client_fetch_headers(void *);
int esp_http_client_read(void *, char *, int);
int esp_http_client_set_timeout_ms(void *, int);
int esp_http_client_get_status_code(void *);
bool esp_http_client_is_complete_data_received(void *);
int esp_http_client_cleanup(void *);
int esp_crt_bundle_attach(void *);
int64_t esp_timer_get_time(void);
#define ESP_LOGW(...) ((void)0)
#define ESP_LOGI(...) ((void)0)
#define pdMS_TO_TICKS(x) (x)
void vTaskDelay(unsigned);
'''

FIXTURE = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "http_test_sdk.h"
#include "cJSON.h"
#include "pet_cloud.h"
#include "pet_turn.h"
static esp_http_client_config_t config;
static char last_url[256];
static const char *response;
static char *request;
static int calls, cleaned, status = 200, mode;
static bool complete = true, bearer, api_key, version, chinese_asr;
static int64_t ticks;
static bool signed_mode;
static int body_used, body_length, writes, read_offset, reads, header_polls;
const char *pet_secrets_deepseek(void) { return "test-only-key"; }
const char *pet_secrets_minimax(void) { return "test-only-key"; }
int esp_crt_bundle_attach(void *x) { return 0; }
void vTaskDelay(unsigned ticks) {}
int64_t esp_timer_get_time(void) { return ++ticks * 10000; }
void *esp_http_client_init(const esp_http_client_config_t *c) {
    config = *c; snprintf(last_url,sizeof(last_url),"%s",c->url);config.url=last_url; calls = 0; bearer = api_key = version = signed_mode = false;
    assert(c->timeout_ms == 10000 || c->timeout_ms == 1000); return (void *)1;
}
int esp_http_client_set_method(void *c, int method) { assert(method == HTTP_METHOD_POST);calls=0;bearer=api_key=version=false;return 0; }
int esp_http_client_set_url(void *c,const char *url){snprintf(last_url,sizeof(last_url),"%s",url);return ESP_OK;}
int esp_http_client_set_user_data(void *c,void *data){config.user_data=data;return ESP_OK;}
int esp_http_client_delete_header(void *c,const char *key){if(!strcmp(key,"x-api-key"))api_key=false;if(!strcmp(key,"anthropic-version"))version=false;if(!strcmp(key,"language"))chinese_asr=false;return ESP_OK;}
int esp_http_client_set_header(void *c, const char *key, const char *value) {
    if (!strcmp(key, "Authorization")) { bearer = true; assert(!strcmp(value, "Bearer test-only-key") || !strcmp(value,"Bearer 01234567890123456789012345678901")); }
    if (!strcmp(key, "x-api-key")) { api_key = true; assert(!strcmp(value, "test-only-key")); }
    if (!strcmp(key, "anthropic-version")) version = true;
    if (!strcmp(key,"language")){assert(!strcmp(value,"zh"));chinese_asr=true;}
    return 0;
}
int esp_http_client_set_post_field(void *c, const void *body, int n) {
    if(!body||!n)return 0;
    free(request); request = malloc(n + 1); memcpy(request, body, n); request[n] = 0; return 0;
}
int esp_http_client_perform(void *client) {
    assert(config.is_async);
    calls++;
    if (mode == 1) { pet_turn_next(); return ESP_ERR_HTTP_EAGAIN; }
    if (calls < 3) return ESP_ERR_HTTP_EAGAIN;
    size_t size = strlen(response), first = size / 2;
    esp_http_client_event_t e = {.event_id = HTTP_EVENT_ON_DATA, .data_len = first, .data = (void *)response, .user_data = config.user_data};
    if (config.event_handler(&e) != ESP_OK) return ESP_FAIL;
    e.data = (void *)(response + first); e.data_len = size - first;
    return config.event_handler(&e);
}
int esp_http_client_open(void *client,int n) {
    signed_mode=!config.is_async;calls++;
    if(mode==1) {pet_turn_next();return ESP_ERR_HTTP_EAGAIN;}
    if(calls<3)return ESP_ERR_HTTP_EAGAIN;
    free(request);request=calloc(n+1,1);body_length=n;body_used=writes=read_offset=reads=header_polls=0;
    return ESP_OK;
}
int esp_http_client_write(void *client,const char *p,int n) {
    assert(n<=1024 && body_used+n<=body_length);writes++;
    if(mode==2 && body_used>=62)return 0;
    if(writes%5==0)return -ESP_ERR_HTTP_EAGAIN;
    int sent=n>31 ? 31 : n;memcpy(request+body_used,p,sent);body_used+=sent;return sent;
}
int64_t esp_http_client_fetch_headers(void *client) {
    if(body_used<body_length && mode!=2)return -ESP_ERR_HTTP_EAGAIN;
    header_polls++;
    return header_polls==1 ? -ESP_ERR_HTTP_EAGAIN : (int64_t)strlen(response);
}
int esp_http_client_set_timeout_ms(void *client,int ms) {assert(ms==1000 || ms==10000);return ESP_OK;}
int esp_http_client_read(void *client,char *out,int cap) {
    reads++;if(reads==1)return -ESP_ERR_HTTP_EAGAIN;
    int n=(int)strlen(response)-read_offset;if(n>7)n=7;
    memcpy(out,response+read_offset,n);
    esp_http_client_event_t e={.event_id=HTTP_EVENT_ON_DATA,.data_len=n,.data=(void *)(response+read_offset),.user_data=config.user_data};
    read_offset+=n;return config.event_handler(&e)==ESP_OK ? n : ESP_FAIL;
}
int esp_http_client_get_status_code(void *c) { return status; }
bool esp_http_client_is_complete_data_received(void *c) { return complete && (!signed_mode || read_offset==(int)strlen(response)); }
int esp_http_client_cleanup(void *c) { cleaned++; return 0; }
'''


class CloudHostTests(unittest.TestCase):
    def test_asr_uses_documented_chinese_header_without_leaking_it_into_other_calls(self):
        self.run_fixture(r'''
int main(void){
 int16_t pcm[512]={0};char text[128];response="{\"text\":\"休息熄屏吧\"}";
 assert(pet_cloud_transcribe(pcm,512,text,sizeof(text))==0&&chinese_asr);
 assert(!strcmp(text,"休息熄屏吧")&&strstr(last_url,"/v1/speech_to_text"));
 response="{\"content\":[{\"type\":\"text\",\"text\":\"{}\"}]}";
 char *out=pet_cloud_minimax("system","hello",true);assert(out&&!chinese_asr);free(out);
 free(request);return 0;
}
''')

    def run_fixture(self, body, search=False, computer=False):
        headers = {"http_test_sdk.h": HTTP_SDK,
                   "sdkconfig.h": '#define CONFIG_DESKPET_MINIMAX_HOST "https://api.minimaxi.com"\n'}
        if computer:
            headers["sdkconfig.h"] += '#define CONFIG_DESKPET_COMPUTER_URL "https://computer.example"\n#define CONFIG_DESKPET_COMPUTER_TOKEN "01234567890123456789012345678901"\n'
        if search:
            headers["sdkconfig.h"] += '#define CONFIG_DESKPET_MINIMAX_SEARCH 1\n'
        for name in ["esp_crt_bundle.h", "esp_http_client.h", "esp_log.h", "esp_timer.h", "esp_tls.h", "freertos/FreeRTOS.h", "freertos/task.h"]:
            headers[name] = '#include "http_test_sdk.h"\n'
        test_runtime_core.RuntimeCoreTests.run_c(self, FIXTURE + body, ["pet_cloud", "pet_tts", "pet_search", "pet_util", "pet_turn", "pet_stream", "pet_latency"], headers)

    def test_computer_rpc_uses_only_fixed_https_origin_and_pairing_token(self):
        self.run_fixture(r'''
int main(void){
 assert(pet_cloud_computer_configured());response="{\"ok\":true,\"ready\":true}";
 cJSON *request=cJSON_CreateObject();char *raw=pet_cloud_computer("health",request);
 assert(raw&&strstr(raw,"ready")&&bearer&&!api_key&&!version);free(raw);
 assert(!strcmp(config.url,"https://computer.example/v1/computer/health")&&config.timeout_ms==1000);
 assert(!pet_cloud_computer("https://other.example",request));cJSON_Delete(request);return 0;
}
''',computer=True)

    def test_panel_resource_rpc_accepts_a_slice_larger_than_normal_rpc_budget(self):
        self.run_fixture(r'''
int main(void){
 char payload[9200];memset(payload,'A',sizeof(payload)-1);payload[sizeof(payload)-1]=0;response=payload;
 pet_cloud_begin_turn(pet_turn_current());cJSON *r=cJSON_CreateObject();
 char *raw=pet_cloud_computer("resource",r);
 assert(raw&&strlen(raw)==sizeof(payload)-1&&bearer&&!api_key&&!version);
 assert(!strcmp(last_url,"https://computer.example/v1/computer/resource"));
 free(raw);cJSON_Delete(r);free(request);return 0;
}
''',computer=True)

    def test_subscription_search_uses_minimax_key_and_bounded_sources_without_deepseek(self):
        self.run_fixture(r'''
int main(void){
 response="{\"base_resp\":{\"status_code\":0},\"organic\":[{\"title\":\"丰台天气\",\"snippet\":\"目标日预报\",\"link\":\"https://www.weather.com.cn/example\",\"date\":\"2026-10-17\"}]}";
 char*found=pet_cloud_search("北京丰台 2026年10月18日 天气");assert(found&&strstr(found,"目标日预报"));free(found);
 assert(strstr(config.url,"api.minimaxi.com/v1/coding_plan/search"));
 cJSON*j=cJSON_Parse(request);assert(cJSON_IsString(cJSON_GetObjectItem(j,"q")));cJSON_Delete(j);
 assert(!strstr(request,"deepseek"));
 response="{\"base_resp\":{\"status_code\":1004}}";assert(!pet_cloud_search("天气"));
 return 0;
}
''', search=True)

    def test_explicit_preview_voice_does_not_change_the_saved_voice(self):
        self.run_fixture(r'''
#include "pet_tts.h"
int main(void){
 int16_t pcm[4];response="{\"base_resp\":{\"status_code\":0},\"data\":{\"audio\":\"00000100ffff0080\"}}";
 assert(pet_tts_current()==4);
 assert(pet_cloud_speak_voice("试听","lovely_girl",pcm,4)==4);
 cJSON*j=cJSON_Parse(request);cJSON*v=cJSON_GetObjectItem(j,"voice_setting");
 assert(!strcmp(cJSON_GetObjectItem(v,"voice_id")->valuestring,"lovely_girl"));cJSON_Delete(j);
 assert(pet_tts_current()==4);
 assert(pet_cloud_speak("你好",pcm,4)==4);
 j=cJSON_Parse(request);v=cJSON_GetObjectItem(j,"voice_setting");
 assert(!strcmp(cJSON_GetObjectItem(v,"voice_id")->valuestring,"female-shaonv"));cJSON_Delete(j);
 return 0;
}
''')

    def test_signed_provider_request_uses_url_auth_without_bearer(self):
        self.run_fixture(r'''
int main(void) {
    pet_cloud_begin_turn(pet_turn_current());
    response="{\"header\":{\"code\":0}}";
    cJSON *body=cJSON_Parse("{\"header\":{\"app_id\":\"test-app\",\"status\":3}}");
    char payload[4097];memset(payload,'a',4096);payload[4096]=0;cJSON_AddStringToObject(body,"audio",payload);
    char *text=pet_cloud_signed_json("https://api.xf-yun.com/v1/private/s1aa729d0?authorization=test",body);
    assert(text && !strcmp(text,response));
    assert(calls==3 && cleaned==1 && !bearer && !api_key && !version);
    assert(strstr(request,"test-app"));
    cJSON *decoded=cJSON_Parse(request);assert(decoded && !strcmp(cJSON_GetObjectItem(decoded,"audio")->valuestring,payload));cJSON_Delete(decoded);
    free(text);
    status=500;response="{\"header\":{\"code\":23009}}";
    text=pet_cloud_signed_json("https://api.xf-yun.com/v1/private/s1aa729d0?authorization=test",body);
    assert(text && strstr(text,"23009") && cleaned==2 && !bearer);
    free(text);mode=2;response="{\"header\":{\"code\":23998}}";
    text=pet_cloud_signed_json("https://api.xf-yun.com/v1/private/s1aa729d0?authorization=test",body);
    assert(text && strstr(text,"23998") && body_used<body_length && cleaned==3);free(text);
    status=200;response="{\"header\":{\"code\":0}}";
    assert(pet_cloud_signed_json("https://api.xf-yun.com/v1/private/s1aa729d0?authorization=test",body)==NULL && cleaned==4);
    mode=1;pet_cloud_begin_turn(pet_turn_current());
    assert(pet_cloud_signed_json("https://api.xf-yun.com/v1/private/s1aa729d0?authorization=test",body)==NULL && cleaned==5);
    free(request);cJSON_Delete(body);return 0;
}
''')

    def test_request_roles_headers_and_thinking_separation(self):
        self.run_fixture(r'''
int main(void) {
    pet_cloud_begin_turn(pet_turn_current());
    cJSON *history = cJSON_Parse("[{\"role\":\"user\",\"content\":\"你好\"},{\"role\":\"assistant\",\"content\":\"你好呀\"},{\"role\":\"user\",\"content\":\"继续\"}]");
    response = "data: {\"type\":\"message_start\"}\n\n"
      "data: {\"type\":\"content_block_start\",\"index\":0,\"content_block\":{\"type\":\"thinking\"}}\n\n"
      "data: {\"type\":\"content_block_delta\",\"index\":0,\"delta\":{\"type\":\"thinking_delta\",\"thinking\":\"内部思考\"}}\n\n"
      "data: {\"type\":\"content_block_stop\",\"index\":0}\n\n"
      "data: {\"type\":\"content_block_start\",\"index\":1,\"content_block\":{\"type\":\"text\"}}\n\n"
      "data: {\"type\":\"content_block_delta\",\"index\":1,\"delta\":{\"type\":\"text_delta\",\"text\":\"可说的正文\"}}\n\n"
      "data: {\"type\":\"content_block_stop\",\"index\":1}\n\n"
      "data: {\"type\":\"message_stop\"}\n\n";
    char *text = pet_cloud_dialogue("system", history);
    assert(text && !strcmp(text, "可说的正文") && bearer && api_key && version && calls >= 3); free(text);
    cJSON *sent = cJSON_Parse(request);
    assert(cJSON_GetArraySize(cJSON_GetObjectItem(sent, "messages")) == 3);
    assert(cJSON_IsTrue(cJSON_GetObjectItem(sent,"stream")));
    assert(!strcmp(cJSON_GetObjectItem(cJSON_GetObjectItem(sent,"output_config"),"effort")->valuestring,"low"));
    assert(!strcmp(cJSON_GetObjectItem(sent,"system")->valuestring,"system"));
    assert(strstr(config.url,"api.minimaxi.com") && !strstr(config.url,"deepseek"));
    assert(pet_cloud_search("test search")==NULL); /* default never charges DeepSeek */
    cJSON_Delete(sent); cJSON_Delete(history);
    response = "{\"content\":[{\"type\":\"thinking\",\"thinking\":\"内部思考\"},{\"type\":\"text\",\"text\":\"{\\\"action\\\":\\\"wait\\\"}\"}]}";
    text = pet_cloud_minimax("system", "plan", false);
    assert(text && strstr(text, "wait") && !strstr(text, "内部思考") && bearer && api_key && version);
    assert(!strcmp(config.url, "https://api.minimaxi.com/anthropic/v1/messages")); free(text);
    free(request); return 0;
}
''')

    def test_pcm_validation_and_cancelled_or_incomplete_responses(self):
        self.run_fixture(r'''
int main(void) {
    pet_cloud_begin_turn(pet_turn_current());
    response = "{\"data\":{\"audio\":\"0100ffff0080ff7f\"},\"base_resp\":{\"status_code\":0}}";
    int16_t pcm[4]; assert(pet_cloud_speak("你好", pcm, 4) == 4);
    assert(pcm[0] == 1 && pcm[1] == -1 && pcm[2] == -32768 && pcm[3] == 32767);
    assert(pet_cloud_speak("你好", pcm, 3) == -2);
    complete = false; assert(pet_cloud_speak("你好", pcm, 4) == -1); complete = true;
    status = 401; assert(pet_cloud_speak("你好", pcm, 4) == -1); status = 200;
    response = "{\"data\":{\"audio\":\"xx00\"},\"base_resp\":{\"status_code\":0}}";
    assert(pet_cloud_speak("你好", pcm, 4) == -1);
    mode = 1; int before = cleaned; pet_cloud_begin_turn(pet_turn_current());
    assert(pet_cloud_speak("过时的话", pcm, 4) == -1 && calls == 1 && cleaned == before + 1);
    free(request); return 0;
}
''')

    def test_streamed_pcm_terminal_errors_invalid_hex_and_cancellation(self):
        self.run_fixture(r'''
static int received;
static bool cancel_sink;
static bool sink(const int16_t *pcm,size_t n,void *u){
 assert(n==4&&pcm[0]==1&&pcm[1]==-1&&pcm[2]==-32768&&pcm[3]==32767);
 received+=n;if(cancel_sink){pet_turn_next();return false;}return true;
}
int main(void){
 pet_cloud_begin_turn(pet_turn_current());
 const char *valid="data: {\"data\":{\"status\":1,\"audio\":\"0100ffff0080ff7f\"},\"base_resp\":{\"status_code\":0}}\r\n\r\n"
   "data: {\"data\":{\"status\":2,\"audio\":\"\"},\"base_resp\":{\"status_code\":0}}\r\n\r\n";
 response=valid;assert(pet_cloud_speak_stream("你好",sink,0)==4&&received==4);
 cJSON *sent=cJSON_Parse(request);assert(cJSON_IsTrue(cJSON_GetObjectItem(sent,"stream")));
 assert(cJSON_IsTrue(cJSON_GetObjectItem(cJSON_GetObjectItem(sent,"stream_options"),"exclude_aggregated_audio")));cJSON_Delete(sent);
 received=0;status=401;assert(pet_cloud_speak_stream("你好",sink,0)==-1&&!received);status=200;
 response="data: {\"data\":{\"status\":1,\"audio\":\"0100xxff\"}}\n\n";
 assert(pet_cloud_speak_stream("你好",sink,0)==-1&&!received);
 response="data: {\"data\":{\"status\":1,\"audio\":\"0100ffff0080ff7f\"}}\n\n";
 assert(pet_cloud_speak_stream("你好",sink,0)==-1&&received==4); /* Missing terminal. */
 received=0;response="data: {\"data\":{\"status\":2,\"audio\":\"0100ffff0080ff7f\"}}\n\n";
 assert(pet_cloud_speak_stream("你好",sink,0)==-1&&!received); /* Never replay aggregate. */
 response="data: {\"data\":null,\"base_resp\":{\"status_code\":1008}}\n\n";
 assert(pet_cloud_speak_stream("你好",sink,0)==-1&&!received);
 response=valid;cancel_sink=true;assert(pet_cloud_speak_stream("你好",sink,0)==-1);
 int before=received;assert(pet_cloud_speak_stream("过时的声音",sink,0)==-1&&received==before);
 free(request);return 0;
}
''')

    def test_streamed_dialogue_never_accepts_truncation_or_wrong_text_block(self):
        self.run_fixture(r'''
int main(void){
 pet_cloud_begin_turn(pet_turn_current());cJSON *history=cJSON_CreateArray();
 response="data: {\"type\":\"message_start\"}\n\n"
  "data: {\"type\":\"content_block_start\",\"index\":0,\"content_block\":{\"type\":\"text\"}}\n\n"
  "data: {\"type\":\"content_block_delta\",\"index\":1,\"delta\":{\"type\":\"text_delta\",\"text\":\"不该说\"}}\n\n";
 assert(!pet_cloud_dialogue("system",history));
 response="data: {\"type\":\"message_start\"}\n\n"
  "data: {\"type\":\"content_block_start\",\"index\":0,\"content_block\":{\"type\":\"text\"}}\n\n"
  "data: {\"type\":\"content_block_delta\",\"index\":0,\"delta\":{\"type\":\"text_delta\",\"text\":\"部分内容\"}}\n\n";
 assert(!pet_cloud_dialogue("system",history));
 cJSON_Delete(history);free(request);return 0;
}
''')


if __name__ == "__main__":
    unittest.main()
