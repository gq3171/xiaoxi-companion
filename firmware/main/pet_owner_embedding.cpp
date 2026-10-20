#include "pet_owner_embedding.h"
#include <cmath>
#include <cstring>
#include <memory>
#include <cstdio>
#include <vector>
#include "dl_fbank.hpp"
#include "dl_model_base.hpp"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "mbedtls/sha256.h"
#include "pet_owner_model.h"
extern "C" {
#include "pet_audio.h"
#include "pet_turn.h"
}

extern const uint8_t model_start[] asm("_binary_pet_owner_sv_s3_espdl_start");
extern const uint8_t model_end[] asm("_binary_pet_owner_sv_s3_espdl_end");
static const char *TAG = "pet_owner_local";
static bool s_checked, s_hash_ok, s_tested, s_test_ok;

extern "C" bool pet_owner_embedding_ready(void)
{
    if (!s_checked) {
        s_checked = true;
        unsigned char hash[32];
        char hex[65];
        size_t length = model_end - model_start;
        if (length == PET_OWNER_MODEL_BYTES && !memcmp(model_start, "EDL2", 4) &&
            mbedtls_sha256(model_start, length, hash, 0) == 0) {
            for (int i = 0; i < 32; i++) snprintf(hex + i * 2, 3, "%02x", hash[i]);
            s_hash_ok = !strcmp(hex, PET_OWNER_MODEL_SHA256);
        }
        ESP_LOGI(TAG, "model integrity %s (%u bytes)", s_hash_ok ? "OK" : "FAILED", (unsigned)length);
    }
    return s_hash_ok && (!s_tested || s_test_ok);
}

static bool reference_check(dl::Model &model)
{
    auto fbs = model.get_fbs_model();
    if (!fbs || model.get_inputs().empty() || model.get_outputs().empty()) return false;
    fbs->load_map();
    std::unique_ptr<dl::TensorBase> input(fbs->get_test_input_tensor("input"));
    std::unique_ptr<dl::TensorBase> expected(fbs->get_test_output_tensor("embedding"));
    auto actual_input = model.get_inputs().begin()->second;
    auto output = model.get_outputs().begin()->second;
    if (!input || !expected || !actual_input || !output || !input->data || !expected->data ||
        !actual_input->data || !output->data || input->size != 24000 || expected->size != PET_OWNER_EMBED_DIM ||
        !actual_input->assign(input.get())) return false;
    model.run(dl::RUNTIME_MODE_MULTI_CORE);
    if (output->size != expected->size || output->dtype != expected->dtype || output->exponent != expected->exponent)
        return false;
    auto actual = static_cast<const int16_t *>(output->data);
    auto baseline = static_cast<const int16_t *>(expected->data);
    double ab = 0, aa = 0, bb = 0, error = 0;
    for (int i = 0; i < output->size; i++) {
        ab += double(actual[i]) * baseline[i]; aa += double(actual[i]) * actual[i];
        bb += double(baseline[i]) * baseline[i];
        error += double(actual[i] - baseline[i]) * (actual[i] - baseline[i]);
    }
    double similarity = aa > 0 && bb > 0 ? ab / sqrt(aa * bb) : -1;
    double relative_error = bb > 0 ? sqrt(error / bb) : 1;
    ESP_LOGI(TAG, "reference cosine=%.9f relative_error=%.6f", similarity, relative_error);
    // This gate checks the normalized embedding and relative vector error.
    // It does not relabel ESP-DL's stricter elementwise test as passing.
    return similarity > .9999 && relative_error < .01;
}

extern "C" bool pet_owner_embedding_prepare(void)
{
    if (!pet_owner_embedding_ready()) return false;
    if (s_tested) return s_test_ok;
    size_t available = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
    size_t internal = heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    ESP_LOGI(TAG, "prepare memory psram=%u internal=%u", (unsigned)available, (unsigned)internal);
    if (available < 2 * 1024 * 1024 || internal < 32 * 1024) return false;
    bool copy = available >= 5800 * 1024 && heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM) >= 3700 * 1024;
    dl::Model model(reinterpret_cast<const char *>(model_start), fbs::MODEL_LOCATION_IN_FLASH_RODATA,
                    0, dl::MEMORY_MANAGER_GREEDY, nullptr, copy);
    s_test_ok = reference_check(model); s_tested = true;
    ESP_LOGI(TAG, "local inference self-check %s", s_test_ok ? "OK" : "FAILED");
    return s_test_ok;
}

extern "C" bool pet_owner_embedding(const int16_t *pcm, int samples, float *result)
{
    if (!pcm || !result || samples < PET_SAMPLE_RATE * 3 / 4 || samples > PET_SAMPLE_RATE * 20 ||
        !pet_owner_embedding_ready()) return false;
    uint32_t generation = pet_turn_current();
    size_t available = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
    size_t internal = heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (available < 2 * 1024 * 1024 || internal < 32 * 1024) {
        ESP_LOGW(TAG, "not enough inference memory: psram=%u internal=%u", (unsigned)available, (unsigned)internal);
        return false;
    }
    bool copy_weights = available >= 5800 * 1024 &&
        heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM) >= 3700 * 1024;
    int64_t before = esp_timer_get_time();
    // Release weights/workspace before ASR/TTS; do not reserve them permanently.
    dl::Model model(reinterpret_cast<const char *>(model_start),
                    fbs::MODEL_LOCATION_IN_FLASH_RODATA, 0,
                    dl::MEMORY_MANAGER_GREEDY, nullptr, copy_weights);
    if (!s_tested) {
        s_test_ok = reference_check(model); s_tested = true;
        if (!s_test_ok) return false;
    }
    if (model.get_inputs().empty() || model.get_outputs().empty()) return false;
    model.minimize();
    auto input = model.get_inputs().begin()->second;
    auto output = model.get_outputs().begin()->second;
    if (!input || !output || !input->data || !output->data || input->size != 24000 || output->size != PET_OWNER_EMBED_DIM ||
        input->dtype != dl::DATA_TYPE_INT16 || output->dtype != dl::DATA_TYPE_INT16) return false;
    const int target = 299 * 160 + 400;
    std::vector<float> audio(target, 0), features(24000);
    int offset = samples > target ? (samples - target) / 2 : 0;
    for (int i = 0; i < target && i + offset < samples; i++) audio[i] = pcm[i + offset] / 32768.f;
    dl::audio::SpeechFeatureConfig cfg;
    cfg.sample_rate = 16000; cfg.num_mel_bins = 80; cfg.frame_length = 25; cfg.frame_shift = 10;
    cfg.window_type = dl::audio::WinType::HAMMING;
    cfg.use_energy = false; cfg.use_log_fbank = 1; cfg.low_freq = 20; cfg.high_freq = 0;
    dl::audio::Fbank frontend(cfg);
    if (frontend.process(audio.data(), target, features.data()) != ESP_OK) return false;
    auto values = static_cast<int16_t *>(input->data);
    for (int d = 0; d < 80; d++) {
        float mean = 0;
        for (int t = 0; t < 300; t++) mean += features[t * 80 + d];
        mean /= 300;
        for (int t = 0; t < 300; t++)
            values[t * 80 + d] = dl::quantize<int16_t>(features[t * 80 + d] - mean, DL_RESCALE(input->exponent));
    }
    if (!pet_turn_valid(generation)) return false;
    model.run(dl::RUNTIME_MODE_MULTI_CORE);
    if (!pet_turn_valid(generation)) return false;
    auto out = static_cast<const int16_t *>(output->data);
    double norm = 0;
    for (int i = 0; i < PET_OWNER_EMBED_DIM; i++) {
        result[i] = dl::dequantize(out[i], DL_SCALE(output->exponent));
        norm += result[i] * result[i];
    }
    if (!std::isfinite(norm) || norm < 1e-8) return false;
    float scale = 1.f / sqrtf(norm);
    for (int i = 0; i < PET_OWNER_EMBED_DIM; i++) result[i] *= scale;
    ESP_LOGI(TAG, "embedding complete ms=%ld weights_in_psram=%d", (long)((esp_timer_get_time() - before) / 1000), copy_weights);
    return true;
}
