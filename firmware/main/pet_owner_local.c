#include "pet_owner.h"
#include "pet_owner_embedding.h"
#include "pet_owner_model.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include "cJSON.h"
#include "mbedtls/base64.h"
#include "pet_audio.h"
#include "pet_util.h"
#include "pet_voice.h"
#ifdef ESP_PLATFORM
#include "esp_log.h"
#define OWNER_SCORE_LOG(...) ESP_LOGI("pet_owner_local", __VA_ARGS__)
#else
#define OWNER_SCORE_LOG(...) ((void)0)
#endif

#ifndef PET_STORAGE_ROOT
#define PET_STORAGE_ROOT "/spiffs"
#endif
#define OWNER_BASE PET_STORAGE_ROOT "/owner"
static bool s_loaded, s_locked, s_unreadable, s_verified;
static uint32_t s_sequence, s_crc[3];
static int s_count, s_error = -1;
static float s_owner[PET_OWNER_EMBED_DIM], s_candidate[3][PET_OWNER_EMBED_DIM];

static const char *str(cJSON *root, const char *key)
{
    cJSON *v = cJSON_GetObjectItem(root, key);
    return cJSON_IsString(v) ? v->valuestring : "";
}

static bool normalize(float *v)
{
    double energy = 0;
    for (int i = 0; i < PET_OWNER_EMBED_DIM; i++) {
        if (!isfinite(v[i])) return false;
        energy += v[i] * v[i];
    }
    if (energy < 1e-8 || !isfinite(energy)) return false;
    float scale = 1.f / sqrtf(energy);
    for (int i = 0; i < PET_OWNER_EMBED_DIM; i++) v[i] *= scale;
    return true;
}

static float score(const float *a, const float *b)
{
    double sum = 0;
    for (int i = 0; i < PET_OWNER_EMBED_DIM; i++) sum += a[i] * b[i];
    return fminf(1, fmaxf(-1, sum));
}

static void load(void)
{
    if (s_loaded) return;
    s_loaded = true;
    char *text = pet_snapshot_load(OWNER_BASE, 2048, &s_sequence);
    cJSON *root = text ? cJSON_Parse(text) : NULL;
    free(text);
    bool ok = cJSON_IsObject(root) && cJSON_IsTrue(cJSON_GetObjectItem(root, "verified")) &&
        !strcmp(str(root, "provider"), "espdl-local-v1") &&
        !strcmp(str(root, "model"), PET_OWNER_LOCAL_MODEL_ID) &&
        !strcmp(str(root, "model_hash"), PET_OWNER_MODEL_SHA256);
    int16_t quantized[PET_OWNER_EMBED_DIM]; size_t size = 0;
    const char *encoded = str(root, "embedding");
    ok = ok && strlen(encoded) == 1368 &&
        mbedtls_base64_decode((unsigned char *)quantized, sizeof(quantized), &size,
                             (const unsigned char *)encoded, strlen(encoded)) == 0 && size == sizeof(quantized);
    if (ok) {
        double energy = 0;
        for (int i = 0; i < PET_OWNER_EMBED_DIM; i++) {
            s_owner[i] = quantized[i] / 32767.f;
            energy += s_owner[i] * s_owner[i];
        }
        ok = energy > .98 && energy < 1.02 && normalize(s_owner);
    }
    s_locked = ok;
    s_unreadable = !ok && pet_snapshot_exists(OWNER_BASE);
    cJSON_Delete(root);
    /* An existing cloud/other-model owner is preserved and blocks enrollment;
     * switching provider must never silently replace that owner's identity. */
}

bool pet_owner_configured(void) { return pet_owner_embedding_ready(); }
bool pet_owner_locked(void) { load(); return s_locked && pet_owner_configured(); }
bool pet_owner_storage_ok(void) { load(); return !s_unreadable; }
int pet_owner_error_code(void) { return s_error; }

static bool embed(const int16_t *pcm, int samples, float *out)
{
    s_error = -1;
    if (!pcm || samples < PET_SAMPLE_RATE * 3 / 4 || samples > PET_SAMPLE_RATE * 20 ||
        !pet_voice_usable(pcm, samples)) return false;
    if (!pet_owner_embedding(pcm, samples, out) || !normalize(out)) return false;
    s_error = 0; return true;
}

void pet_owner_abort(void)
{
    memset(s_candidate, 0, sizeof(s_candidate)); memset(s_crc, 0, sizeof(s_crc));
    s_count = 0; s_verified = false;
}

int pet_owner_stage(const int16_t *pcm, int samples)
{
    load(); pet_owner_abort();
    if (s_unreadable || samples < PET_SAMPLE_RATE * 3 || !embed(pcm, samples, s_candidate[0])) return -1;
    s_crc[0] = pet_crc32(pcm, samples * sizeof(int16_t)); s_count = 1; return 0;
}

int pet_owner_add_sample(const int16_t *pcm, int samples)
{
    s_verified = false;
    if (s_count < 1 || s_count >= 3 || !pcm || samples < PET_SAMPLE_RATE * 3 || samples > PET_SAMPLE_RATE * 20) return -1;
    uint32_t crc = pet_crc32(pcm, samples * sizeof(int16_t));
    for (int i = 0; i < s_count; i++) if (crc == s_crc[i]) return -1;
    float value[PET_OWNER_EMBED_DIM];
    if (!embed(pcm, samples, value)) return -1;
    for (int i = 0; i < s_count; i++) {
        float similarity = score(value, s_candidate[i]);
        OWNER_SCORE_LOG("sample consistency reference=%d score=%.4f", i + 1, similarity);
        if (similarity < PET_OWNER_THRESHOLD) return -1;
    }
    memcpy(s_candidate[s_count], value, sizeof(value)); s_crc[s_count++] = crc; return 0;
}

static bool centroid(float *out)
{
    if (s_count != 3) return false;
    for (int i = 0; i < PET_OWNER_EMBED_DIM; i++)
        out[i] = (s_candidate[0][i] + s_candidate[1][i] + s_candidate[2][i]) / 3;
    return normalize(out);
}

float pet_owner_verify_candidate(const int16_t *pcm, int samples)
{
    s_verified = false;
    if (s_count != 3 || !pcm || samples < PET_SAMPLE_RATE * 3 || samples > PET_SAMPLE_RATE * 20) return -1;
    uint32_t crc = pet_crc32(pcm, samples * sizeof(int16_t));
    for (int i = 0; i < 3; i++) if (crc == s_crc[i]) return -1;
    float value[PET_OWNER_EMBED_DIM], center[PET_OWNER_EMBED_DIM];
    if (!embed(pcm, samples, value) || !centroid(center)) return -1;
    float result = score(value, center);
    OWNER_SCORE_LOG("fresh verification score=%.4f", result);
    s_verified = result >= PET_OWNER_THRESHOLD;
    return result;
}

int pet_owner_commit(void)
{
    float center[PET_OWNER_EMBED_DIM];
    if (!s_verified || !centroid(center)) return -1;
    int16_t quantized[PET_OWNER_EMBED_DIM];
    for (int i = 0; i < PET_OWNER_EMBED_DIM; i++) quantized[i] = (int16_t)lrintf(center[i] * 32767.f);
    unsigned char encoded[1369]; size_t size = 0;
    if (mbedtls_base64_encode(encoded, sizeof(encoded), &size, (unsigned char *)quantized, sizeof(quantized)) != 0) return -1;
    encoded[size] = 0;
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "provider", "espdl-local-v1");
    cJSON_AddStringToObject(root, "model", PET_OWNER_LOCAL_MODEL_ID);
    cJSON_AddStringToObject(root, "model_hash", PET_OWNER_MODEL_SHA256);
    cJSON_AddBoolToObject(root, "verified", true);
    cJSON_AddStringToObject(root, "embedding", (const char *)encoded);
    char *text = cJSON_PrintUnformatted(root); cJSON_Delete(root);
    int result = text ? pet_snapshot_save(OWNER_BASE, text, 2048, &s_sequence) : -1;
    free(text);
    if (result == 0) { memcpy(s_owner, center, sizeof(center)); s_locked = true; pet_owner_abort(); }
    return result;
}

float pet_owner_verify(const int16_t *pcm, int samples)
{
    float value[PET_OWNER_EMBED_DIM];
    if (!pet_owner_locked() || !embed(pcm, samples, value)) return -1;
    float result = score(value, s_owner);
    OWNER_SCORE_LOG("owner verification score=%.4f", result);
    return result;
}
