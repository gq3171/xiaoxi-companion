#include <stdlib.h>
#include "cJSON.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "pet_audio.h"
#include "pet_capture.h"
#include "pet_controls.h"
#include "pet_face.h"
#include "pet_hardware.h"
#include "pet_runtime.h"
#include "pet_secrets.h"
#include "pet_setup.h"
#include "pet_store.h"
#include "pet_util.h"
#include "pet_tts.h"
#include "pet_panel.h"

static void halt(const char *message)
{
    pet_face_set("在这儿", message);
    while (true) vTaskDelay(pdMS_TO_TICKS(1000));
}

void app_main(void)
{
    cJSON_Hooks hooks = {.malloc_fn = pet_alloc, .free_fn = free}; cJSON_InitHooks(&hooks);
    esp_err_t nvs = nvs_flash_init();
    /* Never erase Wi-Fi, credentials, or identity automatically on an NVS error. */
    pet_panel_start();pet_face_start();
    if (nvs != ESP_OK) halt("设置存储出了问题，我没有清除你的资料。");
    if (pet_store_start() != 0) halt("记忆存储出了问题，我没有清除它。");
    pet_tts_start(); pet_secrets_start(); pet_audio_start(); pet_controls_start(); pet_hardware_start(); pet_runtime_prepare();
    pet_store_seed_wifi();
    pet_setup_wifi();
    if (pet_capture_start() != 0) halt("耳朵这次没准备好，先保持安静。");
    pet_runtime_start();
}
