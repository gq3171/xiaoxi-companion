#include "pet_cloud.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <stdatomic.h>
#include "sdkconfig.h"
#include "pet_model_config.h"
#include "esp_crt_bundle.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_tls.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "pet_audio.h"
#include "pet_secrets.h"
#include "pet_turn.h"
#include "pet_util.h"
#include "pet_stream.h"
#include "pet_latency.h"
#include "pet_tts.h"
#include "pet_search.h"
#include "pet_brain.h"
#ifdef ESP_PLATFORM
#include "esp_heap_caps.h"
#endif

static const char *TAG = "pet_cloud";
static uint32_t s_request_generation;
static bool s_bound;
static esp_http_client_handle_t s_minimax_client;
static atomic_uint s_fast_until;
static int s_last_http;
static int64_t s_keep_until;
static bool s_microphone;
void pet_cloud_input_source(bool microphone){s_microphone=microphone;}
bool pet_cloud_ready(void){
#ifdef CONFIG_DESKPET_REMOTE_BRAIN
return pet_brain_enabled();
#else
return pet_secrets_minimax()[0];
#endif
}
#ifdef PET_COMPUTER_CUSTOM_CA
extern const char pet_computer_ca[] asm("_binary_pet_computer_ca_start");
#endif
bool pet_cloud_network_active(void)
{
    unsigned until=atomic_load(&s_fast_until);
    return until&&(int32_t)(until-(uint32_t)(esp_timer_get_time()/1000))>0;
}
void pet_cloud_begin_turn(uint32_t generation) { s_request_generation = generation; s_bound = true; }
bool pet_cloud_cancelled(void) { return s_bound && !pet_turn_valid(s_request_generation); }

typedef struct {
    pet_sse_t sse;
    pet_audio_sink_fn sink;
    void *user;
    char *text;
    size_t text_used;
    int samples;
    bool tts, done, text_block, started, limited;
    int block_index;
} cloud_stream_t;
static bool stream_event(const char *data,size_t length,void *user);
typedef struct { char *data; size_t used, capacity, limit; bool failed; cloud_stream_t *stream; esp_http_client_handle_t client; int64_t started; } response_t;

static esp_err_t receive(esp_http_client_event_t *event)
{
    response_t *r = event->user_data;
    if(!r)return ESP_OK;
    if (pet_cloud_cancelled()) return ESP_FAIL;
    if(event->event_id==HTTP_EVENT_ON_CONNECTED)
        ESP_LOGI(TAG,"HTTPS connected in %lld ms",(long long)((esp_timer_get_time()-r->started)/1000));
    if (event->event_id != HTTP_EVENT_ON_DATA || event->data_len <= 0) return ESP_OK;
    if (r->stream) {
        if(esp_http_client_get_status_code(r->client)!=200 ||
           !pet_sse_feed(&r->stream->sse,event->data,event->data_len)) {r->failed=true;return ESP_FAIL;}
        return ESP_OK;
    }
    size_t needed = r->used + event->data_len + 1;
    if (needed > r->limit) { r->failed = true; return ESP_FAIL; }
    if (needed > r->capacity) {
        size_t capacity = r->capacity ? r->capacity * 2 : 4096;
        if (capacity < needed) capacity = needed;
        if (capacity > r->limit) capacity = r->limit;
        char *grown = pet_alloc(capacity);
        if (!grown) { r->failed = true; return ESP_FAIL; }
        if (r->data) memcpy(grown, r->data, r->used);
        free(r->data); r->data = grown; r->capacity = capacity;
    }
    memcpy(r->data + r->used, event->data, event->data_len);
    r->used += event->data_len; r->data[r->used] = 0;
    return ESP_OK;
}

static bool request_live(response_t *response, int64_t deadline)
{
    return !pet_cloud_cancelled() && !response->failed && esp_timer_get_time() < deadline;
}

static esp_err_t signed_read_body(esp_http_client_handle_t client, response_t *response, int64_t deadline)
{
    char buffer[1024];
    while (!esp_http_client_is_complete_data_received(client) && request_live(response, deadline)) {
        int n = esp_http_client_read(client, buffer, sizeof(buffer));
        if (n == -ESP_ERR_HTTP_EAGAIN) { vTaskDelay(pdMS_TO_TICKS(10)); continue; }
        if (n <= 0 && !esp_http_client_is_complete_data_received(client)) return ESP_FAIL;
    }
    return request_live(response, deadline) && esp_http_client_is_complete_data_received(client) ? ESP_OK : ESP_FAIL;
}

/* Bound each TLS write for large base64 voice uploads. The SDK's perform()
 * path sends the complete body at once, which stalled on the real device. */
static esp_err_t signed_transfer(esp_http_client_handle_t client, const char *body, int length,
                                 response_t *response, int64_t deadline)
{
    esp_err_t err;
    do {
        if (!request_live(response, deadline)) return ESP_FAIL;
        err = esp_http_client_open(client, length);
        if (err == ESP_ERR_HTTP_EAGAIN) vTaskDelay(pdMS_TO_TICKS(10));
    } while (err == ESP_ERR_HTTP_EAGAIN);
    if (err != ESP_OK) return err;
    int sent = 0, logged_block = -1;
    while (sent < length && request_live(response, deadline)) {
        if (sent / 16384 != logged_block) {
            logged_block = sent / 16384;
            ESP_LOGI(TAG, "signed upload %d/%d bytes", sent, length);
        }
        int count = length - sent; if (count > 1024) count = 1024;
        errno = 0;
        int n = esp_http_client_write(client, body + sent, count);
        if (n > 0 && n <= count) sent += n;
        else if (n == 0 || n == -ESP_ERR_HTTP_EAGAIN || n == ESP_TLS_ERR_SSL_WANT_READ || n == ESP_TLS_ERR_SSL_WANT_WRITE || errno == EAGAIN || errno == EWOULDBLOCK) {
            /* A gateway may refuse the request without draining its body.
             * Read that error instead of waiting for a closed receive window. */
            ESP_LOGW(TAG, "signed upload waiting at %d/%d bytes", sent, length);
            esp_http_client_set_timeout_ms(client, 1000);
            int64_t early = esp_http_client_fetch_headers(client);
            esp_http_client_set_timeout_ms(client, 10000);
            if (early >= 0) {
                esp_err_t read = signed_read_body(client, response, deadline);
                int status = esp_http_client_get_status_code(client);
                /* Partial uploads can only expose errors, never success. */
                return read == ESP_OK && status >= 400 && status < 600 ? ESP_OK : ESP_FAIL;
            }
            if (early != -ESP_ERR_HTTP_EAGAIN) return ESP_FAIL;
            vTaskDelay(pdMS_TO_TICKS(10));
        }
        else return ESP_FAIL;
    }
    if (sent != length || !request_live(response, deadline)) return ESP_FAIL;
    ESP_LOGI(TAG, "signed request body sent (%d bytes)", sent);
    int64_t headers;
    do {
        if (!request_live(response, deadline)) return ESP_FAIL;
        headers = esp_http_client_fetch_headers(client);
        if (headers == -ESP_ERR_HTTP_EAGAIN) vTaskDelay(pdMS_TO_TICKS(10));
    } while (headers == -ESP_ERR_HTTP_EAGAIN);
    if (headers < 0) return ESP_FAIL;
    return signed_read_body(client, response, deadline);
}

/* Bound writes to one TLS fragment even on nonblocking sockets. */
static esp_err_t bounded_upload(esp_http_client_handle_t client,const void *body,int length,response_t *response,int64_t deadline)
{
    esp_err_t err;
    do{
        if(!request_live(response,deadline))return ESP_FAIL;
        err=esp_http_client_open(client,length);
        if(err==ESP_ERR_HTTP_EAGAIN)vTaskDelay(pdMS_TO_TICKS(10));
    }while(err==ESP_ERR_HTTP_EAGAIN);
    if(err!=ESP_OK)return err;
    int sent=0;int64_t started=esp_timer_get_time();
    ESP_LOGI(TAG,"upload begin: %d bytes",length);
    while(sent<length&&request_live(response,deadline)){
        int n=length-sent;if(n>1024)n=1024;
        errno=0;int written=esp_http_client_write(client,(const char *)body+sent,n);
        if(written>0&&written<=n)sent+=written;
        else if(written==ESP_TLS_ERR_SSL_WANT_READ||written==ESP_TLS_ERR_SSL_WANT_WRITE||written== -ESP_ERR_HTTP_EAGAIN||errno==EAGAIN||errno==EWOULDBLOCK)
            vTaskDelay(pdMS_TO_TICKS(10));
        else {
            ESP_LOGW(TAG,"upload stalled: sent=%d/%d result=%d elapsed_ms=%lld",sent,length,written,(long long)((esp_timer_get_time()-started)/1000));
            return ESP_FAIL;
        }
    }
    ESP_LOGI(TAG,"upload end: sent=%d/%d elapsed_ms=%lld",sent,length,(long long)((esp_timer_get_time()-started)/1000));
    return sent==length&&request_live(response,deadline)?ESP_OK:ESP_FAIL;
}

static char *http_post_ex(const char *url, const char *content_type, const char *key,
                       bool anthropic, const void *body, int length, size_t limit, bool error_json,cloud_stream_t *stream)
{
    s_last_http=0;
    bool computer=false;
#ifdef CONFIG_DESKPET_COMPUTER_URL
    size_t computer_url_length=strlen(CONFIG_DESKPET_COMPUTER_URL);
    computer=computer_url_length>8&&!strncmp(url,CONFIG_DESKPET_COMPUTER_URL,computer_url_length)&&url[computer_url_length]=='/';
#endif
#ifdef ESP_PLATFORM
    ESP_LOGI(TAG,"heap internal=%u largest=%u psram=%u",
        (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
        (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
        (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
#endif
    if (!key || pet_cloud_cancelled() || !body || length <= 0) return NULL;
    atomic_store(&s_fast_until,(uint32_t)(esp_timer_get_time()/1000)+60000);
    response_t response = {.limit = limit,.stream=stream,.started=esp_timer_get_time()};
    esp_http_client_config_t config = {
        /* IDF 5.5.5 can end perform() as incomplete data when a socket poll
         * expires between response fragments. Audio JSON needs a realistic
         * read gap; turn cancellation still prevents stale playback. */
        .url = url, .timeout_ms = (computer&&!strstr(url,"/v1/brain/"))?1000:10000, .is_async = !error_json,
        .crt_bundle_attach = esp_crt_bundle_attach,
        .event_handler = receive, .user_data = &response,
        .buffer_size = 2048, .buffer_size_tx = 2048,
    };
#ifdef PET_COMPUTER_CUSTOM_CA
    if(computer){config.crt_bundle_attach=NULL;config.cert_pem=pet_computer_ca;}
#endif
    size_t host_length=strlen(CONFIG_DESKPET_MINIMAX_HOST);
    bool reusable=!error_json&&!strncmp(url,CONFIG_DESKPET_MINIMAX_HOST,host_length)&&url[host_length]=='/';
    if(reusable&&s_minimax_client&&esp_timer_get_time()>=s_keep_until){
        esp_http_client_cleanup(s_minimax_client);s_minimax_client=NULL;
    }
    esp_http_client_handle_t client=reusable?s_minimax_client:NULL;
    bool reused=client!=NULL;
    if(client){
        if(esp_http_client_set_url(client,url)!=ESP_OK||esp_http_client_set_user_data(client,&response)!=ESP_OK){
            esp_http_client_cleanup(client);s_minimax_client=NULL;return NULL;
        }
    }else client=esp_http_client_init(&config);
    if (!client) return NULL;
    if(reusable)s_minimax_client=client;
    ESP_LOGI(TAG,"HTTPS connection %s",reused?"reused":"new");
    response.client=client;
    char auth[256];
    snprintf(auth, sizeof(auth), "Bearer %s", key);
    esp_http_client_set_post_field(client,NULL,0);
    esp_http_client_set_method(client, HTTP_METHOD_POST);
    esp_http_client_set_header(client, "Content-Type", content_type);
#ifdef CONFIG_DESKPET_REMOTE_BRAIN
    if(computer&&strstr(url,"/v1/brain/asr")){
        cJSON *session=pet_brain_envelope();char *raw=session?cJSON_PrintUnformatted(session):NULL;cJSON_Delete(session);
        if(raw){esp_http_client_set_header(client,"X-Pet-Session",raw);free(raw);}
    }else esp_http_client_delete_header(client,"X-Pet-Session");
#endif
    if(strstr(url,"/v1/speech_to_text"))esp_http_client_set_header(client,"language","zh");
    else esp_http_client_delete_header(client,"language");
    if (key[0]) esp_http_client_set_header(client, "Authorization", auth);
    if (anthropic) {
        esp_http_client_set_header(client, "x-api-key", key);
        esp_http_client_set_header(client, "anthropic-version", "2023-06-01");
    }else{
        esp_http_client_delete_header(client,"x-api-key");
        esp_http_client_delete_header(client,"anthropic-version");
    }
    bool slow_brain=computer&&(strstr(url,"/v1/brain/model")||strstr(url,"/v1/brain/tts")||strstr(url,"/v1/brain/asr")||strstr(url,"/v1/brain/search"));
    int64_t deadline = esp_timer_get_time() + (computer&&!slow_brain?8000000:90000000);
    esp_err_t err;
    if (error_json) err = signed_transfer(client, body, length, &response, deadline);
    else {
      err=bounded_upload(client,body,length,&response,deadline);
      if(err==ESP_OK)do {
        if (pet_cloud_cancelled() || response.failed || esp_timer_get_time() >= deadline) {
            err = ESP_FAIL; break;
        }
        err = esp_http_client_perform(client);
        if (err == ESP_ERR_HTTP_EAGAIN) vTaskDelay(pdMS_TO_TICKS(10));
    } while (err == ESP_ERR_HTTP_EAGAIN);
    }
    int status = esp_http_client_get_status_code(client);
    s_last_http=status;
    bool complete = esp_http_client_is_complete_data_received(client);
    bool keep=reusable&&err==ESP_OK&&!response.failed&&complete&&!pet_cloud_cancelled()&&status>=200&&status<300&&
        (!stream||(stream->done&&pet_sse_complete(&stream->sse)));
    if(keep){
        s_keep_until=esp_timer_get_time()+10000000;
        esp_http_client_set_user_data(client,NULL);
        esp_http_client_set_post_field(client,NULL,0);
    }else{esp_http_client_cleanup(client);if(reusable)s_minimax_client=NULL;}
    memset(auth, 0, sizeof(auth));
    if (err != ESP_OK || response.failed || !complete || pet_cloud_cancelled() ||
        (stream && (!stream->done || !pet_sse_complete(&stream->sse)))) {
        /* API errors can echo credentials; never log response bodies or headers. */
        if (!pet_cloud_cancelled()) ESP_LOGW(TAG, "request failed: HTTP %d, transport %d", status, err);
        free(response.data); return NULL;
    }
    if (status < 200 || status >= 300) {
        ESP_LOGW(TAG, "provider response: HTTP %d", status);
        if (!error_json || status < 400 || status >= 600) { free(response.data); return NULL; }
    } else ESP_LOGI(TAG, "request complete: HTTP %d", status);
    return stream ? pet_strdup("ok") : response.data;
}

static char *http_post(const char *url,const char *content_type,const char *key,bool anthropic,
                       const void *body,int length,size_t limit,bool error_json)
{return http_post_ex(url,content_type,key,anthropic,body,length,limit,error_json,NULL);}

/* Allocate per response in PSRAM, not on the small runtime stack. */
static bool stream_init(cloud_stream_t *s,bool tts)
{
    size_t cap=tts?131072:32768;
    char *line=pet_alloc(cap),*data=pet_alloc(cap);
    if(!line||!data){free(line);free(data);return false;}
    s->tts=tts;pet_sse_init(&s->sse,line,data,cap,stream_event,s);return true;
}
static void stream_free(cloud_stream_t *s){free(s->sse.line);free(s->sse.data);free(s->text);}

static bool api_ok(cJSON *root)
{
    cJSON *base = cJSON_GetObjectItem(root, "base_resp");
    cJSON *status = base ? cJSON_GetObjectItem(base, "status_code") : NULL;
    return !cJSON_IsNumber(status) || status->valueint == 0;
}

char *pet_cloud_signed_json(const char *url, const cJSON *request)
{
    char *body = cJSON_PrintUnformatted(request);
    if (!body) return NULL;
    char *result = http_post(url, "application/json", "", false, body, strlen(body), 8192, true);
    free(body); return result;
}

static char *post_json(const char *url, const char *key, bool anthropic, cJSON *request, size_t limit)
{
    if (!key || !key[0]) return NULL;
    char *body = cJSON_PrintUnformatted(request);
    if (!body) return NULL;
    char *response = http_post(url, "application/json", key, anthropic, body, strlen(body), limit, false);
    free(body); return response;
}

static char *anthropic_text(cJSON *root)
{
    cJSON *blocks = cJSON_GetObjectItem(root, "content"), *block;
    size_t length = 0;
    cJSON_ArrayForEach(block, blocks) {
        cJSON *type = cJSON_GetObjectItem(block, "type"), *text = cJSON_GetObjectItem(block, "text");
        if (cJSON_IsString(type) && !strcmp(type->valuestring, "text") && cJSON_IsString(text)) length += strlen(text->valuestring) + 1;
    }
    if (!length) return NULL;
    char *out = pet_alloc(length + 1);
    if (!out) return NULL;
    out[0] = 0;
    cJSON_ArrayForEach(block, blocks) {
        cJSON *type = cJSON_GetObjectItem(block, "type"), *text = cJSON_GetObjectItem(block, "text");
        if (cJSON_IsString(type) && !strcmp(type->valuestring, "text") && cJSON_IsString(text)) {
            strcat(out, text->valuestring); strcat(out, "\n");
        }
    }
    return out;
}

bool pet_cloud_computer_configured(void)
{
#if defined(CONFIG_DESKPET_COMPUTER_URL) && defined(CONFIG_DESKPET_COMPUTER_TOKEN)
    const char *url=CONFIG_DESKPET_COMPUTER_URL,*token=CONFIG_DESKPET_COMPUTER_TOKEN;
    return !strncmp(url,"https://",8)&&strlen(url)>8&&strlen(url)<320&&
        !strchr(url,'?')&&!strchr(url,'#')&&!strchr(url,'@')&&strlen(token)>=32&&strlen(token)<=192;
#else
    return false;
#endif
}
char *pet_cloud_computer(const char *operation,const cJSON *request)
{
#if defined(CONFIG_DESKPET_COMPUTER_URL) && defined(CONFIG_DESKPET_COMPUTER_TOKEN)
    if(!pet_cloud_computer_configured()||!operation||
       (strcmp(operation,"private_input")&&strcmp(operation,"health")&&strcmp(operation,"submit")&&strcmp(operation,"status")&&strcmp(operation,"cancel")&&strcmp(operation,"resume")&&strcmp(operation,"media_list")&&strcmp(operation,"media_probe")&&strcmp(operation,"media_chunk")&&strcmp(operation,"resource")))return NULL;
    char url[384];snprintf(url,sizeof(url),"%s/v1/computer/%s",CONFIG_DESKPET_COMPUTER_URL,operation);
    return post_json(url,CONFIG_DESKPET_COMPUTER_TOKEN,false,(cJSON*)request,!strcmp(operation,"media_chunk")?96*1024:!strcmp(operation,"resource")?32*1024:8192);
#else
    (void)operation;(void)request;return NULL;
#endif
}

char *pet_cloud_brain(const char *operation,const cJSON *request)
{
#ifdef CONFIG_DESKPET_REMOTE_BRAIN
    const char *allowed[]={"open","memory","state","snapshot","health","cancel","model","search"};bool valid=false;
    for(size_t i=0;i<sizeof(allowed)/sizeof(allowed[0]);i++)if(!strcmp(operation,allowed[i]))valid=true;
    if(!valid||!pet_cloud_computer_configured())return NULL;
    char url[384];snprintf(url,sizeof(url),"%s/v1/brain/%s",CONFIG_DESKPET_COMPUTER_URL,operation);
    return post_json(url,CONFIG_DESKPET_BRAIN_TOKEN,false,(cJSON*)request,160*1024);
#else
    (void)operation;(void)request;return NULL;
#endif
}
#ifdef CONFIG_DESKPET_REMOTE_BRAIN
static char *remote_model(const char *kind,const char *system,const char *text)
{
    if(!pet_brain_reconcile())return NULL;
    cJSON *request=pet_brain_envelope();if(!request)return NULL;
    cJSON_AddStringToObject(request,"kind",kind);cJSON_AddStringToObject(request,"system",system);
    cJSON_AddStringToObject(request,!strcmp(kind,"dialogue")?"candidate":"request",text);
    cJSON_AddBoolToObject(request,"microphone",s_microphone);
    char *raw=pet_cloud_brain("model",request);cJSON_Delete(request);
    cJSON *reply=raw?cJSON_Parse(raw):NULL;free(raw);cJSON *value=cJSON_GetObjectItem(reply,"text");
    char *out=cJSON_IsString(value)&&cJSON_IsTrue(cJSON_GetObjectItem(reply,"ok"))?pet_strdup(value->valuestring):NULL;
    cJSON_Delete(reply);return out;
}
#endif
char *pet_cloud_birth(const char *system,const char *text)
{
#ifdef CONFIG_DESKPET_REMOTE_BRAIN
    return remote_model("birth",system,text);
#else
    return pet_cloud_minimax(system,text,true);
#endif
}
char *pet_cloud_dialogue(const char *system_prompt, const cJSON *history)
{
#ifdef CONFIG_DESKPET_REMOTE_BRAIN
    const cJSON *last=cJSON_GetArrayItem(history,cJSON_GetArraySize(history)-1),*value=cJSON_GetObjectItem(last,"content");
    pet_latency_mark(s_request_generation,PET_TIME_LLM_START);
    char *out=cJSON_IsString(value)?remote_model("dialogue",system_prompt,value->valuestring):NULL;
    pet_latency_mark(s_request_generation,PET_TIME_LLM_END);return out;
#endif
    cJSON *request = cJSON_CreateObject();
    cJSON_AddStringToObject(request, "model", CONFIG_DESKPET_MINIMAX_MODEL);
    cJSON_AddNumberToObject(request, "max_tokens", 4096);
    cJSON_AddNumberToObject(request, "temperature", 1);
    cJSON_AddBoolToObject(request, "stream", true);
    cJSON *output=cJSON_AddObjectToObject(request,"output_config");
    cJSON_AddStringToObject(output,"effort","low");
    cJSON_AddStringToObject(request, "system", system_prompt);
    cJSON *messages = cJSON_Duplicate(history, true);
    cJSON_AddItemToObject(request, "messages", messages);
    char url[192]; snprintf(url, sizeof(url), "%s/anthropic/v1/messages", CONFIG_DESKPET_MINIMAX_HOST);
    cloud_stream_t stream={0};
    if(!stream_init(&stream,false)){cJSON_Delete(request);return NULL;}
    stream.text=pet_alloc(65536);
    if(!stream.text){stream_free(&stream);cJSON_Delete(request);return NULL;}
    stream.text[0]=0;
    char *body=cJSON_PrintUnformatted(request);
    pet_latency_mark(s_request_generation,PET_TIME_LLM_START);
    char *response=body?http_post_ex(url,"application/json",pet_secrets_minimax(),true,body,strlen(body),0,false,&stream):NULL;
    free(body);
    cJSON_Delete(request);
    char *text=NULL;
    if(response && !stream.limited && stream.text_used){text=stream.text;stream.text=NULL;}
    free(response);stream_free(&stream);
    pet_latency_mark(s_request_generation,PET_TIME_LLM_END);
    return text;
}

char *pet_cloud_minimax(const char *system_prompt, const char *request_text, bool reflection)
{
#ifdef CONFIG_DESKPET_REMOTE_BRAIN
    return remote_model(reflection?"reflection":"plan",system_prompt,request_text);
#endif
    cJSON *request = cJSON_CreateObject();
    cJSON_AddStringToObject(request, "model", CONFIG_DESKPET_MINIMAX_MODEL);
    cJSON_AddNumberToObject(request, "max_tokens", 8192);
    cJSON_AddNumberToObject(request, "temperature", reflection ? 0 : 1);
    cJSON_AddStringToObject(request, "system", system_prompt);
    cJSON *output = cJSON_AddObjectToObject(request, "output_config");
    cJSON_AddStringToObject(output, "effort", reflection ? "high" : "low");
    cJSON *messages = cJSON_AddArrayToObject(request, "messages"), *message = cJSON_CreateObject();
    cJSON_AddStringToObject(message, "role", "user");
    cJSON_AddStringToObject(message, "content", request_text);
    cJSON_AddItemToArray(messages, message);
    char url[192]; snprintf(url, sizeof(url), "%s/anthropic/v1/messages", CONFIG_DESKPET_MINIMAX_HOST);
    char *response = post_json(url, pet_secrets_minimax(), true, request, 256 * 1024);
    cJSON_Delete(request);
    if (!response) return NULL;
    cJSON *root = cJSON_Parse(response); free(response);
    char *text = root ? anthropic_text(root) : NULL;
    cJSON_Delete(root); return text;
}

char *pet_cloud_search(const char *query)
{
#ifdef CONFIG_DESKPET_REMOTE_BRAIN
    {
    if(!pet_brain_ensure())return NULL;
    cJSON *r=pet_brain_envelope();cJSON_AddStringToObject(r,"query",query);
    char *raw=pet_cloud_brain("search",r);cJSON_Delete(r);cJSON *reply=raw?cJSON_Parse(raw):NULL;free(raw);
    cJSON *sources=cJSON_GetObjectItem(reply,"sources");char *out=cJSON_IsArray(sources)?cJSON_PrintUnformatted(sources):NULL;cJSON_Delete(reply);return out;
    }
#endif
#ifndef CONFIG_DESKPET_MINIMAX_SEARCH
    ESP_LOGW(TAG, "MiniMax subscription search disabled");
    return NULL;
#else
    if(!query||!query[0]||strlen(query)>512)return NULL;
    cJSON *request = cJSON_CreateObject();cJSON_AddStringToObject(request,"q",query);
    char url[192];snprintf(url,sizeof(url),"%s/v1/coding_plan/search",CONFIG_DESKPET_MINIMAX_HOST);
    char *response=post_json(url,pet_secrets_minimax(),false,request,64*1024);
    cJSON_Delete(request);
    char *sources=pet_search_sources(response);free(response);
    ESP_LOGI(TAG,"MiniMax subscription search usable=%d",sources!=NULL);return sources;
#endif
}

static void wav_header(uint8_t *h, int samples)
{
    memset(h, 0, 44);
    memcpy(h, "RIFF", 4); memcpy(h + 8, "WAVEfmt ", 8); memcpy(h + 36, "data", 4);
    uint32_t chunk = 36 + samples * 2, fmt = 16, rate = PET_SAMPLE_RATE, bytes = rate * 2, data = samples * 2;
    uint16_t pcm = 1, channels = 1, block = 2, bits = 16;
    memcpy(h + 4, &chunk, 4); memcpy(h + 16, &fmt, 4); memcpy(h + 20, &pcm, 2);
    memcpy(h + 22, &channels, 2); memcpy(h + 24, &rate, 4); memcpy(h + 28, &bytes, 4);
    memcpy(h + 32, &block, 2); memcpy(h + 34, &bits, 2); memcpy(h + 40, &data, 4);
}

int pet_cloud_transcribe(const int16_t *mono, int samples, char *text, int capacity)
{
    if (capacity > 0) text[0] = 0;
    if (samples <= 0 || capacity < 2) return -1;
    const char *head = "------deskpet\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n" CONFIG_DESKPET_ASR_MODEL "\r\n"
                       "------deskpet\r\nContent-Disposition: form-data; name=\"file\"; filename=\"speech.wav\"\r\nContent-Type: audio/wav\r\n\r\n";
    const char *tail = "\r\n------deskpet--\r\n";
    size_t h = strlen(head), t = strlen(tail), wav = 44 + samples * 2, length = h + wav + t;
    uint8_t *body = pet_alloc(length);
    if (!body) return -1;
    memcpy(body, head, h); wav_header(body + h, samples); memcpy(body + h + 44, mono, samples * 2);
    memcpy(body + h + wav, tail, t);
    char url[192]; snprintf(url, sizeof(url), "%s/v1/speech_to_text", CONFIG_DESKPET_MINIMAX_HOST);
#ifdef CONFIG_DESKPET_REMOTE_BRAIN
    if(!pet_brain_ensure()){free(body);return -1;}
    snprintf(url,sizeof(url),"%s/v1/brain/asr",CONFIG_DESKPET_COMPUTER_URL);
    const char *asr_key=CONFIG_DESKPET_BRAIN_TOKEN;
#else
    const char *asr_key=pet_secrets_minimax();
#endif
    char *response = http_post(url, "multipart/form-data; boundary=----deskpet", asr_key, false, body, length, 32 * 1024, false);
    free(body);
    if (!response) return s_last_http==400?-2:s_last_http==401||s_last_http==403?-3:s_last_http==429?-4:-1;
    cJSON *root = cJSON_Parse(response); free(response);
    cJSON *value = root ? cJSON_GetObjectItem(root, "text") : NULL;
    int okay = api_ok(root) && cJSON_IsString(value) && strlen(value->valuestring) < (size_t)capacity;
    if (okay) pet_utf8_copy(text, capacity, value->valuestring);
    else {
        const cJSON *base=root?cJSON_GetObjectItem(root,"base_resp"):NULL;
        const cJSON *code=base?cJSON_GetObjectItem(base,"status_code"):NULL;
        ESP_LOGW(TAG,"ASR response unusable: provider_code=%d text_present=%d",cJSON_IsNumber(code)?code->valueint:0,cJSON_IsString(value));
    }
    cJSON_Delete(root); return okay ? 0 : -1;
}

int pet_cloud_chat(const char *system, const char *user, char *reply, int capacity)
{
    cJSON *history = cJSON_CreateArray(), *message = cJSON_CreateObject();
    cJSON_AddStringToObject(message, "role", "user"); cJSON_AddStringToObject(message, "content", user);
    cJSON_AddItemToArray(history, message);
    char *text = pet_cloud_dialogue(system, history); cJSON_Delete(history);
    if (!text || strlen(text) >= (size_t)capacity) { free(text); return -1; }
    pet_utf8_copy(reply, capacity, text); free(text); return 0;
}

static int hex_nibble(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static const char *string_at(cJSON *root,const char *key)
{cJSON *v=cJSON_GetObjectItemCaseSensitive(root,key);return cJSON_IsString(v)?v->valuestring:"";}
static bool stream_event(const char *bytes,size_t length,void *user)
{
    cloud_stream_t *s=user;
    if(pet_cloud_cancelled())return false;
    if(length==6&&!memcmp(bytes,"[DONE]",6))return s->done;
    cJSON *root=cJSON_ParseWithLength(bytes,length+1);
    if(!cJSON_IsObject(root)||!api_ok(root)){cJSON_Delete(root);return false;}
    bool okay=true;
    if(s->tts){
        cJSON *data=cJSON_GetObjectItemCaseSensitive(root,"data");
        cJSON *status=cJSON_GetObjectItemCaseSensitive(data,"status");
        const char *audio=string_at(data,"audio");size_t n=strlen(audio);
        if(!cJSON_IsNumber(status)||s->done)okay=false;
        else if(status->valueint==2){
            /* exclude_aggregated_audio=true: final audio would be a replay. */
            okay=!n && s->samples>0;s->done=okay;
        }else if(status->valueint!=1||n%4)okay=false;
        else if(n){
            for(size_t i=0;i<n;i++)if(hex_nibble(audio[i])<0){okay=false;break;}
            if(s->samples+(int)(n/4)>PET_SAMPLE_RATE*120)okay=false;
            if(okay){
                pet_latency_mark(s_request_generation,PET_TIME_TTS_AUDIO);
                int16_t pcm[512];
                for(size_t offset=0;okay&&offset<n/4;){
                    size_t count=n/4-offset;if(count>512)count=512;
                    for(size_t i=0;i<count;i++){
                        const char *h=audio+(offset+i)*4;
                        pcm[i]=(int16_t)((hex_nibble(h[0])<<4)|hex_nibble(h[1])|(hex_nibble(h[2])<<12)|(hex_nibble(h[3])<<8));
                    }
                    okay=!pet_cloud_cancelled()&&s->sink(pcm,count,s->user);
                    if(okay){offset+=count;s->samples+=count;}
                }
            }
        }
    }else{
        const char *type=string_at(root,"type");
        if(s->done)okay=false;
        else if(!strcmp(type,"error"))okay=false;
        else if(!strcmp(type,"message_start"))s->started=true;
        else if(!strcmp(type,"content_block_start")){
            cJSON *index=cJSON_GetObjectItemCaseSensitive(root,"index");
            s->text_block=!strcmp(string_at(cJSON_GetObjectItem(root,"content_block"),"type"),"text");
            s->block_index=cJSON_IsNumber(index)?index->valueint:-1;
        }else if(!strcmp(type,"content_block_delta")){
            cJSON *delta=cJSON_GetObjectItemCaseSensitive(root,"delta"),*index=cJSON_GetObjectItemCaseSensitive(root,"index");
            if(!strcmp(string_at(delta,"type"),"text_delta")){
                const char *text=string_at(delta,"text");size_t n=strlen(text);
                okay=s->started&&s->text_block&&cJSON_IsNumber(index)&&index->valueint==s->block_index&&s->text_used+n<65536;
                if(okay){memcpy(s->text+s->text_used,text,n+1);s->text_used+=n;if(n)pet_latency_mark(s_request_generation,PET_TIME_LLM_TEXT);}
            }
        }else if(!strcmp(type,"content_block_stop"))s->text_block=false;
        else if(!strcmp(type,"message_delta")){
            const char *reason=string_at(cJSON_GetObjectItem(root,"delta"),"stop_reason");
            if(!strcmp(reason,"max_tokens"))s->limited=true;
        }else if(!strcmp(type,"message_stop")){okay=s->started&&!s->text_block;s->done=okay;}
        /* Thinking/tool deltas never enter the speakable text buffer. */
    }
    cJSON_Delete(root);return okay;
}

static cJSON *speech_request(const char *text,bool stream,const char *voice_id)
{
    cJSON *request=cJSON_CreateObject();
    cJSON_AddStringToObject(request,"model",CONFIG_DESKPET_TTS_MODEL);
    cJSON_AddStringToObject(request,"text",text);cJSON_AddBoolToObject(request,"stream",stream);
    cJSON_AddStringToObject(request,"output_format","hex");
    if(stream)cJSON_AddBoolToObject(cJSON_AddObjectToObject(request,"stream_options"),"exclude_aggregated_audio",true);
    cJSON *voice=cJSON_AddObjectToObject(request,"voice_setting");
    cJSON_AddStringToObject(voice,"voice_id",voice_id);
    cJSON_AddNumberToObject(voice,"speed",1);cJSON_AddNumberToObject(voice,"vol",1);cJSON_AddNumberToObject(voice,"pitch",0);
    cJSON *audio=cJSON_AddObjectToObject(request,"audio_setting");
    cJSON_AddNumberToObject(audio,"sample_rate",PET_SAMPLE_RATE);cJSON_AddStringToObject(audio,"format","pcm");cJSON_AddNumberToObject(audio,"channel",1);
    return request;
}
static char *speech_body(cJSON *speech)
{
#ifdef CONFIG_DESKPET_REMOTE_BRAIN
    if(!pet_brain_ensure())return NULL;
    cJSON *r=pet_brain_envelope();if(!r)return NULL;cJSON_AddNumberToObject(r,"tts_protocol",2);cJSON_AddItemToObject(r,"speech",cJSON_Duplicate(speech,true));char *body=cJSON_PrintUnformatted(r);cJSON_Delete(r);return body;
#else
    return cJSON_PrintUnformatted(speech);
#endif
}
int pet_cloud_speak_stream(const char *text,pet_audio_sink_fn sink,void *user)
{
    if(!text||!text[0]||!sink)return -1;
    cloud_stream_t stream={.sink=sink,.user=user};
    if(!stream_init(&stream,true))return -1;
    cJSON *request=speech_request(text,true,pet_tts_id(pet_tts_current()));char *body=speech_body(request);cJSON_Delete(request);
    char url[192];snprintf(url,sizeof(url),"%s/v1/t2a_v2",CONFIG_DESKPET_MINIMAX_HOST);
#ifdef CONFIG_DESKPET_REMOTE_BRAIN
    snprintf(url,sizeof(url),"%s/v1/brain/tts",CONFIG_DESKPET_COMPUTER_URL);const char *speech_key=CONFIG_DESKPET_BRAIN_TOKEN;
#else
    const char *speech_key=pet_secrets_minimax();
#endif
    pet_latency_mark(s_request_generation,PET_TIME_TTS_START);
    char *response=body?http_post_ex(url,"application/json",speech_key,false,body,strlen(body),0,false,&stream):NULL;
    int samples=response?stream.samples:-1;
    free(body);free(response);stream_free(&stream);return samples;
}

int pet_cloud_speak(const char *text, int16_t *mono, int max_samples)
{
    return pet_cloud_speak_voice(text,pet_tts_id(pet_tts_current()),mono,max_samples);
}
int pet_cloud_speak_voice(const char *text,const char *voice_id,int16_t *mono,int max_samples)
{
    if(!text||!text[0]||!mono||max_samples<=0||pet_tts_find(voice_id)<0)return -1;
    cJSON *request = speech_request(text,false,voice_id);
    char url[192]; snprintf(url, sizeof(url), "%s/v1/t2a_v2", CONFIG_DESKPET_MINIMAX_HOST);
    char *body=speech_body(request);
#ifdef CONFIG_DESKPET_REMOTE_BRAIN
    snprintf(url,sizeof(url),"%s/v1/brain/tts",CONFIG_DESKPET_COMPUTER_URL);const char *speech_key=CONFIG_DESKPET_BRAIN_TOKEN;
#else
    const char *speech_key=pet_secrets_minimax();
#endif
    char *response=body?http_post(url,"application/json",speech_key,false,body,strlen(body),2*1024*1024,false):NULL;free(body);
    cJSON_Delete(request);
    if (!response) return -1;
    cJSON *root = cJSON_Parse(response); free(response);
    cJSON *data = root ? cJSON_GetObjectItem(root, "data") : NULL, *hex = data ? cJSON_GetObjectItem(data, "audio") : NULL;
    if (!api_ok(root) || !cJSON_IsString(hex)) { cJSON_Delete(root); return -1; }
    size_t length = strlen(hex->valuestring);
    if (!length || length % 4 || length / 4 > (size_t)max_samples) { cJSON_Delete(root); return -2; }
    for (size_t i = 0; i < length / 4; i++) {
        int a = hex_nibble(hex->valuestring[i * 4]), b = hex_nibble(hex->valuestring[i * 4 + 1]);
        int c = hex_nibble(hex->valuestring[i * 4 + 2]), d = hex_nibble(hex->valuestring[i * 4 + 3]);
        if (a < 0 || b < 0 || c < 0 || d < 0) { cJSON_Delete(root); return -1; }
        mono[i] = (int16_t)((a << 4) | b | (c << 12) | (d << 8));
    }
    cJSON_Delete(root); return length / 4;
}
