#include "pet_secrets.h"
#include <string.h>
#include "sdkconfig.h"
#include "nvs.h"
#include "pet_util.h"

static char s_deepseek[240];
static char s_minimax[240];
static char s_xf_app[240], s_xf_key[240], s_xf_secret[240];

void pet_secrets_start(void)
{
#ifdef CONFIG_DESKPET_REMOTE_BRAIN
    /* Old NVS credentials remain solely for app rollback, never loaded or used
     * in remote-brain mode. The new app contains no cloud-provider key. */
    return;
#endif
    pet_utf8_copy(s_xf_app, sizeof(s_xf_app), CONFIG_DESKPET_XFYUN_APP_ID);
    pet_utf8_copy(s_xf_key, sizeof(s_xf_key), CONFIG_DESKPET_XFYUN_API_KEY);
    pet_utf8_copy(s_xf_secret, sizeof(s_xf_secret), CONFIG_DESKPET_XFYUN_API_SECRET);
    nvs_handle_t xf;
    if (nvs_open("pet_voice_keys", NVS_READWRITE, &xf) == ESP_OK) {
        if (s_xf_app[0] && s_xf_key[0] && s_xf_secret[0]) {
            uint32_t seed = pet_crc32(s_xf_app, strlen(s_xf_app)) ^ pet_crc32(s_xf_key, strlen(s_xf_key)) ^ pet_crc32(s_xf_secret, strlen(s_xf_secret));
            uint32_t old = 0;
            if (nvs_get_u32(xf, "seed", &old) != ESP_OK || old != seed) {
                esp_err_t err = nvs_set_str(xf, "appid", s_xf_app);
                if (err == ESP_OK) err = nvs_set_str(xf, "key", s_xf_key);
                if (err == ESP_OK) err = nvs_set_str(xf, "secret", s_xf_secret);
                if (err == ESP_OK) err = nvs_set_u32(xf, "seed", seed);
                if (err == ESP_OK) nvs_commit(xf);
            }
        }
        const char *keys[] = {"appid", "key", "secret"};
        char *buffers[] = {s_xf_app, s_xf_key, s_xf_secret};
        for (int i = 0; i < 3; i++) { size_t size = 240; nvs_get_str(xf, keys[i], buffers[i], &size); }
        nvs_close(xf);
    }
    pet_utf8_copy(s_deepseek, sizeof(s_deepseek), CONFIG_DESKPET_DEEPSEEK_KEY);
    pet_utf8_copy(s_minimax, sizeof(s_minimax), CONFIG_DESKPET_MINIMAX_KEY);
    nvs_handle_t handle;
    if (s_minimax[0] && nvs_open("pet_keys", NVS_READWRITE, &handle) == ESP_OK) {
        uint32_t seed = pet_crc32(s_deepseek, strlen(s_deepseek)) ^ pet_crc32(s_minimax, strlen(s_minimax));
        uint32_t previous = 0;
        if (nvs_get_u32(handle, "seed", &previous) != ESP_OK || previous != seed) {
            esp_err_t err = nvs_set_str(handle, "deepseek", s_deepseek);
            if (err == ESP_OK) err = nvs_set_str(handle, "minimax", s_minimax);
            if (err == ESP_OK) err = nvs_set_u32(handle, "seed", seed);
            if (err == ESP_OK) nvs_commit(handle);
        }
        nvs_close(handle);
    }
    if (nvs_open("pet_keys", NVS_READONLY, &handle) != ESP_OK) return;
    size_t size = sizeof(s_deepseek);
    if (nvs_get_str(handle, "deepseek", s_deepseek, &size) != ESP_OK) {
        pet_utf8_copy(s_deepseek, sizeof(s_deepseek), CONFIG_DESKPET_DEEPSEEK_KEY);
    }
    size = sizeof(s_minimax);
    if (nvs_get_str(handle, "minimax", s_minimax, &size) != ESP_OK) {
        pet_utf8_copy(s_minimax, sizeof(s_minimax), CONFIG_DESKPET_MINIMAX_KEY);
    }
    nvs_close(handle);
}

const char *pet_secrets_xfyun_appid(void) { return s_xf_app; }
const char *pet_secrets_xfyun_key(void) { return s_xf_key; }
const char *pet_secrets_xfyun_secret(void) { return s_xf_secret; }
int pet_secrets_save_xfyun(const char *appid, const char *key, const char *secret)
{
    if (!appid || !key || !secret || !appid[0] || !key[0] || !secret[0] || strlen(appid) >= 240 || strlen(key) >= 240 || strlen(secret) >= 240) return -1;
    nvs_handle_t nvs;
    if (nvs_open("pet_voice_keys", NVS_READWRITE, &nvs) != ESP_OK) return -1;
    esp_err_t err = nvs_set_str(nvs, "appid", appid);
    if (err == ESP_OK) err = nvs_set_str(nvs, "key", key);
    if (err == ESP_OK) err = nvs_set_str(nvs, "secret", secret);
    if (err == ESP_OK) err = nvs_commit(nvs);
    nvs_close(nvs);
    if (err == ESP_OK) { pet_utf8_copy(s_xf_app, 240, appid); pet_utf8_copy(s_xf_key, 240, key); pet_utf8_copy(s_xf_secret, 240, secret); }
    return err == ESP_OK ? 0 : -1;
}

const char *pet_secrets_deepseek(void) { return s_deepseek; }
const char *pet_secrets_minimax(void) { return s_minimax; }

int pet_secrets_save(const char *deepseek, const char *minimax)
{
    if (!deepseek || !minimax || !minimax[0] ||
        strlen(deepseek) >= sizeof(s_deepseek) || strlen(minimax) >= sizeof(s_minimax)) return -1;
    nvs_handle_t handle;
    if (nvs_open("pet_keys", NVS_READWRITE, &handle) != ESP_OK) return -1;
    esp_err_t err = nvs_set_str(handle, "deepseek", deepseek);
    if (err == ESP_OK) err = nvs_set_str(handle, "minimax", minimax);
    if (err == ESP_OK) err = nvs_commit(handle);
    nvs_close(handle);
    if (err != ESP_OK) return -1;
    pet_utf8_copy(s_deepseek, sizeof(s_deepseek), deepseek);
    pet_utf8_copy(s_minimax, sizeof(s_minimax), minimax);
    return 0;
}
