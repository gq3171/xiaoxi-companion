#include "pet_owner.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "esp_mac.h"
#include "esp_random.h"
#include "mbedtls/base64.h"
#include "mbedtls/md.h"
#include "cJSON.h"
#include "pet_audio.h"
#include "pet_cloud.h"
#include "pet_secrets.h"
#include "pet_util.h"
#include "pet_voice.h"

#ifndef PET_STORAGE_ROOT
#define PET_STORAGE_ROOT "/spiffs"
#endif
#define OWNER_BASE PET_STORAGE_ROOT "/owner"
#define XF_SERVICE "s1aa729d0"
static char s_group[33], s_feature[33], s_candidate[33];
static bool s_loaded, s_locked, s_candidate_verified;
static uint32_t s_sequence;
static char s_appid[240];
static bool s_unreadable;
static int s_enrollment_samples;
static uint32_t s_enrollment_crc[3];
static int s_last_service_code = -1;
int pet_owner_error_code(void) { return s_last_service_code; }

bool pet_owner_configured(void)
{
    return pet_secrets_xfyun_appid()[0] && pet_secrets_xfyun_key()[0] && pet_secrets_xfyun_secret()[0];
}

static char *b64(const unsigned char *bytes, size_t n)
{
    size_t room = ((n + 2) / 3) * 4 + 1, written = 0;
    char *out = pet_alloc(room);
    if (out && mbedtls_base64_encode((unsigned char *)out, room, &written, bytes, n) == 0) { out[written] = 0; return out; }
    free(out); return NULL;
}

static bool escape(char *out, size_t room, const char *text)
{
    static const char hex[] = "0123456789ABCDEF";
    size_t used = 0;
    for (; *text; text++) {
        unsigned char c = *text;
        bool plain = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.' || c == '~';
        if (used + (plain ? 1 : 3) >= room) return false;
        if (plain) out[used++] = c;
        else { out[used++] = '%'; out[used++] = hex[c >> 4]; out[used++] = hex[c & 15]; }
    }
    out[used] = 0; return true;
}

static char *signed_url(void)
{
    time_t now = time(NULL); if (now < 1735689600 || !pet_owner_configured()) return NULL;
    struct tm utc; gmtime_r(&now, &utc); char date[64], origin[256];
    strftime(date, sizeof(date), "%a, %d %b %Y %H:%M:%S GMT", &utc);
    snprintf(origin, sizeof(origin), "host: api.xf-yun.com\ndate: %s\nPOST /v1/private/" XF_SERVICE " HTTP/1.1", date);
    unsigned char digest[32]; const char *secret = pet_secrets_xfyun_secret();
    if (mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), (const unsigned char *)secret, strlen(secret), (const unsigned char *)origin, strlen(origin), digest) != 0) return NULL;
    char *signature = b64(digest, sizeof(digest)); if (!signature) return NULL;
    char auth[640]; snprintf(auth, sizeof(auth), "api_key=\"%s\", algorithm=\"hmac-sha256\", headers=\"host date request-line\", signature=\"%s\"", pet_secrets_xfyun_key(), signature); free(signature);
    char *encoded = b64((const unsigned char *)auth, strlen(auth)); memset(auth, 0, sizeof(auth));
    char *url = pet_alloc(3072); char escaped_date[193];
    if (!encoded || !url || !escape(escaped_date, sizeof(escaped_date), date)) { free(encoded); free(url); return NULL; }
    const char *prefix = "https://api.xf-yun.com/v1/private/" XF_SERVICE "?authorization=";
    strcpy(url, prefix); size_t used = strlen(url);
    if (!escape(url + used, 3072 - used - 256, encoded)) { free(encoded); free(url); return NULL; }
    used = strlen(url); snprintf(url + used, 3072 - used, "&host=api.xf-yun.com&date=%s", escaped_date);
    free(encoded); return url;
}

static const char *string(cJSON *o, const char *key)
{
    cJSON *v = cJSON_GetObjectItem(o, key); return cJSON_IsString(v) ? v->valuestring : "";
}

static cJSON *request(const char *action, const char *feature, const int16_t *pcm, int samples)
{
    s_last_service_code = -1;
    char *url = signed_url(); if (!url) return NULL;
    char result_key[64]; snprintf(result_key, sizeof(result_key), "%sRes", action);
    cJSON *body = cJSON_CreateObject(), *header = cJSON_AddObjectToObject(body, "header");
    cJSON_AddStringToObject(header, "app_id", pet_secrets_xfyun_appid()); cJSON_AddNumberToObject(header, "status", 3);
    cJSON *parameter = cJSON_AddObjectToObject(body, "parameter"), *operation = cJSON_AddObjectToObject(parameter, XF_SERVICE);
    cJSON_AddStringToObject(operation, "func", action); cJSON_AddStringToObject(operation, "groupId", s_group);
    if (feature && feature[0]) cJSON_AddStringToObject(operation, !strcmp(action, "searchScoreFea") ? "dstFeatureId" : "featureId", feature);
    if (!strcmp(action, "updateFeature")) cJSON_AddBoolToObject(operation, "cover", false);
    cJSON *format = cJSON_AddObjectToObject(operation, result_key);
    cJSON_AddStringToObject(format, "encoding", "utf8"); cJSON_AddStringToObject(format, "compress", "raw"); cJSON_AddStringToObject(format, "format", "json");
    if (pcm) {
        if (samples <= 0 || samples > PET_SAMPLE_RATE * 20) { free(url); cJSON_Delete(body); return NULL; }
        char *audio = b64((const unsigned char *)pcm, samples * sizeof(int16_t));
        if (!audio) { free(url); cJSON_Delete(body); return NULL; }
        cJSON *payload = cJSON_AddObjectToObject(body, "payload"), *resource = cJSON_AddObjectToObject(payload, "resource");
        cJSON_AddStringToObject(resource, "encoding", "raw"); cJSON_AddNumberToObject(resource, "sample_rate", 16000);
        cJSON_AddNumberToObject(resource, "channels", 1); cJSON_AddNumberToObject(resource, "bit_depth", 16);
        cJSON_AddNumberToObject(resource, "status", 3); cJSON_AddStringToObject(resource, "audio", audio); free(audio);
    }
    char *response = pet_cloud_signed_json(url, body); free(url); cJSON_Delete(body);
    cJSON *root = response ? cJSON_Parse(response) : NULL; free(response);
    cJSON *code = cJSON_GetObjectItem(cJSON_GetObjectItem(root, "header"), "code"), *decoded = NULL;
    if (cJSON_IsNumber(code)) s_last_service_code = code->valueint;
    if (cJSON_IsNumber(code) && code->valueint == 0) {
        cJSON *payload = cJSON_GetObjectItem(root, "payload"), *result = cJSON_GetObjectItem(payload, result_key);
        const char *text = string(result, "text"); size_t size = strlen(text), written = 0;
        unsigned char *bytes = size && size <= 8192 ? pet_alloc(size + 1) : NULL;
        if (bytes && mbedtls_base64_decode(bytes, size, &written, (const unsigned char *)text, size) == 0) { bytes[written] = 0; decoded = cJSON_Parse((char *)bytes); }
        free(bytes);
        cJSON *business_code = cJSON_GetObjectItem(decoded, "code");
        bool shape_ok = !strcmp(action, "queryFeatureList") ? cJSON_IsArray(decoded) : cJSON_IsObject(decoded);
        if (!shape_ok || (business_code && (!cJSON_IsNumber(business_code) || business_code->valueint != 0))) { cJSON_Delete(decoded); decoded = NULL; }
    }
    cJSON_Delete(root); return decoded;
}

static void load(void)
{
    if (s_loaded && !strcmp(s_appid, pet_secrets_xfyun_appid())) return;
    s_loaded = true; s_locked = false; s_feature[0] = 0; s_unreadable = false;
    pet_utf8_copy(s_appid, sizeof(s_appid), pet_secrets_xfyun_appid());
    uint8_t mac[6]; esp_read_mac(mac, ESP_MAC_WIFI_STA);
    snprintf(s_group, sizeof(s_group), "pet_%02x%02x%02x%02x%02x%02x", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    char *text = pet_snapshot_load(OWNER_BASE, 2048, &s_sequence); cJSON *root = text ? cJSON_Parse(text) : NULL; free(text);
    cJSON *verified = cJSON_GetObjectItem(root, "verified");
    bool valid = cJSON_IsObject(root) && cJSON_IsTrue(verified) && !strcmp(string(root, "provider"), "xfyun-v2") &&
        string(root, "appid")[0] && !strcmp(string(root, "group"), s_group) &&
        strlen(string(root, "feature")) > 0 && strlen(string(root, "feature")) < 33;
    if (!valid && pet_snapshot_exists(OWNER_BASE)) s_unreadable = true;
    if (valid && !strcmp(string(root, "appid"), pet_secrets_xfyun_appid())) {
        pet_utf8_copy(s_feature, sizeof(s_feature), string(root, "feature")); s_locked = true;
    }
    cJSON_Delete(root);
}

bool pet_owner_locked(void) { load(); return pet_owner_configured() && s_locked; }
bool pet_owner_storage_ok(void) { load(); return !s_unreadable; }

int pet_owner_stage(const int16_t *pcm, int samples)
{
    load(); if (s_unreadable || !pet_owner_configured() || !pet_voice_usable(pcm, samples) || samples < PET_SAMPLE_RATE * 3) return -1;
    cJSON *group = request("createGroup", NULL, NULL, 0);
    if (group && strcmp(string(group, "groupId"), s_group)) { cJSON_Delete(group); group = NULL; }
    if (!group) group = request("queryFeatureList", NULL, NULL, 0);
    if (!group) return -1;
    cJSON_Delete(group);
    snprintf(s_candidate, sizeof(s_candidate), "owner_%08lx", (unsigned long)esp_random()); s_candidate_verified = false;
    cJSON *created = request("createFeature", s_candidate, pcm, samples);
    bool ok = created && !strcmp(string(created, "featureId"), s_candidate); cJSON_Delete(created);
    if (!ok) { s_candidate[0] = 0; return -1; }
    s_enrollment_samples = 1; s_enrollment_crc[0] = pet_crc32(pcm, samples * sizeof(int16_t));
    return 0;
}

static float verify(const char *feature, const int16_t *pcm, int samples)
{
    if (!feature[0] || !pet_voice_usable(pcm, samples)) return -1;
    cJSON *result = request("searchScoreFea", feature, pcm, samples);
    cJSON *score = cJSON_GetObjectItem(result, "score"); float value = -1;
    if (cJSON_IsNumber(score) && isfinite(score->valuedouble) && score->valuedouble >= -1 && score->valuedouble <= 1 &&
        !strcmp(string(result, "featureId"), feature)) value = score->valuedouble;
    cJSON_Delete(result); return value;
}

float pet_owner_verify_candidate(const int16_t *pcm, int samples)
{
    s_candidate_verified = false;
    if (s_enrollment_samples != 3 || !pcm || samples < PET_SAMPLE_RATE * 3 || samples > PET_SAMPLE_RATE * 20) return -1;
    uint32_t hash = pet_crc32(pcm, samples * sizeof(int16_t));
    for (int i = 0; i < 3; i++) if (hash == s_enrollment_crc[i]) return -1;
    float score = verify(s_candidate, pcm, samples);
    s_candidate_verified = score >= PET_OWNER_THRESHOLD; return score;
}

int pet_owner_add_sample(const int16_t *pcm, int samples)
{
    s_candidate_verified = false;
    if (!s_candidate[0] || s_enrollment_samples < 1 || s_enrollment_samples >= 3 || !pcm || samples < PET_SAMPLE_RATE * 3 || samples > PET_SAMPLE_RATE * 20) return -1;
    uint32_t hash = pet_crc32(pcm, samples * sizeof(int16_t));
    for (int i = 0; i < s_enrollment_samples; i++) if (hash == s_enrollment_crc[i]) return -1;
    if (verify(s_candidate, pcm, samples) < PET_OWNER_THRESHOLD) return -1;
    cJSON *updated = request("updateFeature", s_candidate, pcm, samples);
    bool ok = updated && !strcmp(string(updated, "msg"), "success"); cJSON_Delete(updated);
    if (!ok) return -1;
    s_enrollment_crc[s_enrollment_samples++] = hash; return 0;
}

int pet_owner_commit(void)
{
    if (s_enrollment_samples != 3 || !s_candidate_verified || !s_candidate[0]) return -1;
    cJSON *root = cJSON_CreateObject(); cJSON_AddStringToObject(root, "provider", "xfyun-v2");
    cJSON_AddStringToObject(root, "appid", pet_secrets_xfyun_appid()); cJSON_AddStringToObject(root, "group", s_group);
    cJSON_AddStringToObject(root, "feature", s_candidate); cJSON_AddBoolToObject(root, "verified", true);
    char *text = cJSON_PrintUnformatted(root); cJSON_Delete(root);
    int result = text ? pet_snapshot_save(OWNER_BASE, text, 2048, &s_sequence) : -1; free(text);
    if (result == 0) {
        char old[33]; strcpy(old, s_feature); strcpy(s_feature, s_candidate); s_locked = true; s_candidate[0] = 0; s_candidate_verified = false;
        if (old[0]) { cJSON *deleted = request("deleteFeature", old, NULL, 0); cJSON_Delete(deleted); }
    }
    return result;
}

void pet_owner_abort(void)
{
    if (s_candidate[0]) { cJSON *deleted = request("deleteFeature", s_candidate, NULL, 0); cJSON_Delete(deleted); }
    s_candidate[0] = 0; s_candidate_verified = false;
    s_enrollment_samples = 0;
}

float pet_owner_verify(const int16_t *pcm, int samples)
{
    return pet_owner_locked() ? verify(s_feature, pcm, samples) : -1;
}
