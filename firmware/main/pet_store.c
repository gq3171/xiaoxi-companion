#include "pet_store.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "cJSON.h"
#include "esp_log.h"
#include "esp_spiffs.h"
#include "nvs.h"
#include "pet_memory.h"
#include "pet_birth.h"
#include "pet_util.h"
#include "sdkconfig.h"

#ifndef PET_STORAGE_ROOT
#define PET_STORAGE_ROOT "/spiffs"
#endif

static const char *TAG = "pet_store";
static cJSON *s_birth;
static uint32_t s_birth_sequence;
static const char *birth_value(const char *name)
{
    cJSON *value = cJSON_GetObjectItem(s_birth, name);
    return cJSON_IsString(value) ? value->valuestring : "";
}

int pet_store_start(void)
{
    nvs_handle_t nvs;
    uint8_t initialized = 0;
    if (nvs_open("pet", NVS_READONLY, &nvs) == ESP_OK) { nvs_get_u8(nvs, "storage_init", &initialized); nvs_close(nvs); }
    esp_vfs_spiffs_conf_t config = {
        .base_path = PET_STORAGE_ROOT, .partition_label = "storage", .max_files = 8,
        .format_if_mount_failed = !initialized,
    };
    if (esp_vfs_spiffs_register(&config) != ESP_OK) {
        ESP_LOGE(TAG, "storage mount failed; refusing to erase existing memories"); return -1;
    }
    if (!initialized && nvs_open("pet", NVS_READWRITE, &nvs) == ESP_OK) {
        nvs_set_u8(nvs, "storage_init", 1); nvs_commit(nvs); nvs_close(nvs);
    }
    cJSON_Delete(s_birth); s_birth = NULL;
    char *birth = pet_snapshot_load(PET_STORAGE_ROOT "/birth", 8192, &s_birth_sequence);
    if (!birth && pet_snapshot_exists(PET_STORAGE_ROOT "/birth")) return -1;
    if (birth) {
        s_birth = cJSON_Parse(birth); free(birth);
        if (!cJSON_IsObject(s_birth) || !birth_value("soul")[0]) return -1;
    }
    return pet_memory_start();
}

static int load_str(const char *key, char *out, int capacity)
{
    nvs_handle_t nvs;
    if (nvs_open("pet", NVS_READONLY, &nvs) != ESP_OK) return -1;
    size_t size = capacity;
    esp_err_t err = nvs_get_str(nvs, key, out, &size); nvs_close(nvs);
    return err == ESP_OK ? 0 : -1;
}

int pet_store_load_wifi(char *ssid, int ssid_capacity, char *password, int password_capacity)
{
    if (load_str("ssid", ssid, ssid_capacity) != 0 || !ssid[0]) return -1;
    if (load_str("pass", password, password_capacity) != 0) password[0] = 0;
    return 0;
}

void pet_store_save_wifi(const char *ssid, const char *password)
{
    nvs_handle_t nvs;
    if (nvs_open("pet", NVS_READWRITE, &nvs) != ESP_OK) return;
    nvs_set_str(nvs, "ssid", ssid); nvs_set_str(nvs, "pass", password ? password : "");
    nvs_commit(nvs); nvs_close(nvs);
}

void pet_store_seed_wifi(void)
{
    const char *ssid = CONFIG_DESKPET_WIFI_SSID, *password = CONFIG_DESKPET_WIFI_PASSWORD;
    if (!ssid[0] || strlen(ssid) > 32 || strlen(password) > 64) return;
    uint32_t fingerprint = pet_crc32(ssid, strlen(ssid)) ^ pet_crc32(password, strlen(password));
    nvs_handle_t nvs;
    if (nvs_open("pet_bootstrap", NVS_READWRITE, &nvs) != ESP_OK) return;
    uint32_t previous = 0;
    if (nvs_get_u32(nvs, "wifi_seed", &previous) != ESP_OK || previous != fingerprint) {
        pet_store_save_wifi(ssid, password);
        char actual_ssid[33] = {0}, actual_password[65] = {0};
        if (pet_store_load_wifi(actual_ssid, sizeof(actual_ssid), actual_password, sizeof(actual_password)) == 0 &&
            !strcmp(ssid, actual_ssid) && !strcmp(password, actual_password)) {
            nvs_set_u32(nvs, "wifi_seed", fingerprint); nvs_commit(nvs);
        }
        memset(actual_password, 0, sizeof(actual_password));
    }
    nvs_close(nvs);
}

static int file_size(const char *path)
{
    FILE *file = fopen(path, "rb"); if (!file) return 0;
    fseek(file, 0, SEEK_END); long size = ftell(file); fclose(file); return size;
}

int pet_store_has_soul(void) { return (s_birth && birth_value("soul")[0]) || file_size(PET_STORAGE_ROOT "/SOUL.md") > 8; }

bool pet_store_identity_needs_review(void) { return s_birth && !pet_birth_valid_identity(s_birth); }
cJSON *pet_store_identity_legacy(void) { return pet_store_identity_needs_review() ? cJSON_Duplicate(s_birth, true) : NULL; }
cJSON *pet_store_identity_export(void) { return s_birth?cJSON_Duplicate(s_birth,true):NULL; }
int pet_store_write_identity(const cJSON *identity)
{
    if (!pet_birth_valid_identity(identity)) return -1;
    if (s_birth && pet_birth_valid_identity(s_birth)) return 0;
    cJSON *next = cJSON_Duplicate(identity, true);
    char *json = next ? cJSON_PrintUnformatted(next) : NULL;
    int result = json ? pet_snapshot_save(PET_STORAGE_ROOT "/birth", json, 8192, &s_birth_sequence) : -1;
    free(json);
    if (result == 0) { cJSON_Delete(s_birth); s_birth = next; } else cJSON_Delete(next);
    return result;
}

static void append_file(char *out, int capacity, const char *path)
{
    size_t used = strlen(out);
    if (used + 2 >= (size_t)capacity) return;
    FILE *file = fopen(path, "rb"); if (!file) return;
    out[used++] = '\n';
    size_t got = fread(out + used, 1, capacity - used - 1, file); out[used + got] = 0;
    fclose(file);
    /* Legacy files are only a fallback; a full new birth snapshot fits the budget. */
}

int pet_store_system(char *out, int capacity)
{
    if (capacity < 2) return -1;
    out[0] = 0;
    if (s_birth) {
        int n = snprintf(out, capacity, "你的名字：%s。形态：%s。说话感觉：%s。怎么称呼主人：%s。\n"
                          "最初的约定（保留主人明确边界；兴趣和表达允许随相处成长）：\n%s\n",
                         birth_value("name"), birth_value("creature"), birth_value("vibe"), birth_value("user_name"), birth_value("soul"));
        return n >= capacity ? -1 : 0;
    }
    append_file(out, capacity, PET_STORAGE_ROOT "/SOUL.md"); append_file(out, capacity, PET_STORAGE_ROOT "/IDENTITY.md"); append_file(out, capacity, PET_STORAGE_ROOT "/USER.md");
    return out[0] ? 0 : -1;
}

void pet_store_creature(char *out, int capacity)
{
    pet_utf8_copy(out, capacity, birth_value("creature"));
}

void pet_store_remember(const char *text) { pet_memory_add("user", text, true); }
void pet_store_recent(char *out, int capacity) { pet_memory_context("", out, capacity); }

void pet_store_name(char *out,int capacity)
{
    pet_utf8_copy(out,capacity,birth_value("name"));
}
