#include "pet_voice.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include "cJSON.h"
#include "pet_audio.h"
#include "pet_util.h"

static const float FREQS[PET_VOICE_BANDS] = {150, 250, 350, 500, 700, 900, 1100, 1400, 1700, 2000, 2400, 2800, 3200, 3600, 4000, 4500};
/* M_PI is a libc extension and is absent in strict C17 on some Linux hosts. */
static const float PI = 3.14159265358979323846f;
static float s_profile[PET_VOICE_BANDS];
static float s_window[400];
static bool s_loaded, s_valid;
static uint32_t s_sequence;

pet_voice_stats_t pet_voice_stats(const int16_t *pcm, int samples)
{
    pet_voice_stats_t stats = {0};
    if (!pcm || samples <= 0 || samples > PET_SAMPLE_RATE * 20) return stats;
    double power = 0; int clipped = 0, active = 0;
    for (int i = 0; i < samples; i++) {
        power += (double)pcm[i] * pcm[i];
        if (pcm[i] >= 32000 || pcm[i] <= -32000) clipped++;
        if (pcm[i] > 200 || pcm[i] < -200) active++;
    }
    stats.rms = sqrtf(power / samples);
    stats.clipped_permille = (int)((int64_t)clipped * 1000 / samples);
    stats.active_ms = active * 1000 / PET_SAMPLE_RATE;
    return stats;
}

bool pet_voice_reply_usable(const int16_t *pcm, int samples)
{
    if (!pcm || samples < PET_SAMPLE_RATE / 4 || samples > PET_SAMPLE_RATE * 20) return false;
    pet_voice_stats_t stats = pet_voice_stats(pcm, samples);
    return stats.rms >= 100 && stats.rms <= 14000 && stats.clipped_permille < 10 && stats.active_ms >= 50;
}

bool pet_voice_usable(const int16_t *pcm, int samples)
{
    if (!pcm || samples < PET_SAMPLE_RATE * 3 / 4 || samples > PET_SAMPLE_RATE * 20) return false;
    pet_voice_stats_t stats = pet_voice_stats(pcm, samples);
    return stats.rms >= 180 && stats.rms <= 14000 && stats.clipped_permille < 10 && stats.active_ms >= 333;
}

static void normalize(float *bands)
{
    float sum = 0; for (int i = 0; i < PET_VOICE_BANDS; i++) sum += bands[i] * bands[i];
    float norm = sqrtf(sum);
    if (norm > 1e-6f) for (int i = 0; i < PET_VOICE_BANDS; i++) bands[i] /= norm;
}

void pet_voice_measure(const int16_t *pcm, int samples, float bands[PET_VOICE_BANDS])
{
    if (s_window[200] == 0) for (int i = 0; i < 400; i++) s_window[i] = 0.5f - 0.5f * cosf(2 * PI * i / 399);
    memset(bands, 0, sizeof(float) * PET_VOICE_BANDS);
    for (int offset = 0; offset + 400 <= samples; offset += 400) {
        double energy = 0; for (int i = 0; i < 400; i++) energy += (double)pcm[offset + i] * pcm[offset + i];
        if (energy / 400 < 180 * 180) continue;
        for (int band = 0; band < PET_VOICE_BANDS; band++) {
            /* Hann-windowed narrow band energy; volume normalization keeps soft
             * speech comparable. This is a familiarity hint, not authentication. */
            float coefficient = 2 * cosf(2 * PI * FREQS[band] / PET_SAMPLE_RATE), a = 0, b = 0;
            for (int i = 0; i < 400; i++) { float value = pcm[offset + i] * s_window[i] + coefficient * a - b; b = a; a = value; }
            float power = a * a + b * b - coefficient * a * b;
            bands[band] += sqrtf(fmaxf(power, 0));
        }
    }
    normalize(bands);
}

static void load(void)
{
    if (s_loaded) return;
    s_loaded = true;
    char *json = pet_snapshot_load("/spiffs/voice", 2048, &s_sequence);
    cJSON *root = json ? cJSON_Parse(json) : NULL; free(json);
    cJSON *bands = root ? cJSON_GetObjectItem(root, "bands") : NULL;
    if (cJSON_GetArraySize(bands) == PET_VOICE_BANDS) {
        float norm = 0; s_valid = true;
        for (int i = 0; i < PET_VOICE_BANDS; i++) {
            cJSON *value = cJSON_GetArrayItem(bands, i);
            if (!cJSON_IsNumber(value) || !isfinite(value->valuedouble) || value->valuedouble < 0 || value->valuedouble > 1) { s_valid = false; break; }
            s_profile[i] = value->valuedouble; norm += s_profile[i] * s_profile[i];
        }
        s_valid = s_valid && norm > 0.9f && norm < 1.1f;
    }
    cJSON_Delete(root);
}

void pet_voice_save(const float bands[PET_VOICE_BANDS])
{
    cJSON *root = cJSON_CreateObject(), *array = cJSON_AddArrayToObject(root, "bands");
    cJSON_AddNumberToObject(root, "version", 2);
    for (int i = 0; i < PET_VOICE_BANDS; i++) cJSON_AddItemToArray(array, cJSON_CreateNumber(bands[i]));
    char *json = cJSON_PrintUnformatted(root);
    if (json && pet_snapshot_save("/spiffs/voice", json, 2048, &s_sequence) == 0) {
        s_loaded = false; load();
    }
    free(json); cJSON_Delete(root);
}

int pet_voice_has(void) { load(); return s_valid; }

float pet_voice_match(const int16_t *pcm, int samples)
{
    load();
    if (!s_valid || !pet_voice_usable(pcm, samples)) return 0;
    float bands[PET_VOICE_BANDS]; pet_voice_measure(pcm, samples, bands);
    float dot = 0; for (int i = 0; i < PET_VOICE_BANDS; i++) dot += bands[i] * s_profile[i];
    return fmaxf(0, fminf(1, dot));
}
