"""Host regression checks for actual firmware C code; never accesses hardware.

Run: python3 -m unittest discover -s firmware/tests -v
Requires a host C compiler (Apple Command Line Tools on macOS).
"""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


MAIN = Path(__file__).resolve().parents[1] / "main"

SDK = r"""
#pragma once
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_NOT_FOUND 2
#define ESP_ERROR_CHECK(x) assert((x) == ESP_OK)
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
#define ESP_LOGE(...) ((void)0)
typedef void *esp_codec_dev_handle_t;
typedef struct { int sample_rate, channel, bits_per_sample; } esp_codec_dev_sample_info_t;
#define ESP_CODEC_DEV_OK 0
int esp_codec_dev_set_out_vol(void *, int);
int esp_codec_dev_set_out_mute(void *, bool);
int esp_codec_dev_open(void *, esp_codec_dev_sample_info_t *);
int esp_codec_dev_set_in_gain(void *, float);
int esp_codec_dev_read(void *, void *, int);
int esp_codec_dev_write(void *, void *, int);
esp_codec_dev_handle_t bsp_audio_codec_speaker_init(void);
esp_codec_dev_handle_t bsp_audio_codec_microphone_init(void);
typedef void *SemaphoreHandle_t;
typedef uint32_t TickType_t;
typedef int BaseType_t;
typedef int portMUX_TYPE;
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(x) ((void)0)
#define portEXIT_CRITICAL(x) ((void)0)
#define portMAX_DELAY UINT32_MAX
#define pdPASS 1
#define pdMS_TO_TICKS(ms) (ms)
SemaphoreHandle_t xSemaphoreCreateMutex(void);
int xSemaphoreTake(SemaphoreHandle_t, TickType_t);
int xSemaphoreGive(SemaphoreHandle_t);
TickType_t xTaskGetTickCount(void);
void vTaskDelay(TickType_t);
BaseType_t xTaskCreate(void (*)(void *), const char *, unsigned, void *, unsigned, void *);
typedef int nvs_handle_t;
#define NVS_READONLY 0
#define NVS_READWRITE 1
int nvs_open(const char *, int, nvs_handle_t *);
int nvs_get_u8(nvs_handle_t, const char *, uint8_t *);
int nvs_set_u8(nvs_handle_t, const char *, uint8_t);
int nvs_commit(nvs_handle_t);
void nvs_close(nvs_handle_t);
typedef int gpio_num_t;
#define GPIO_NUM_0 0
#define GPIO_NUM_18 18
#define GPIO_MODE_INPUT 1
#define GPIO_PULLUP_ENABLE 1
#define GPIO_PULLDOWN_DISABLE 0
#define GPIO_INTR_DISABLE 0
typedef struct { uint64_t pin_bit_mask; int mode, pull_up_en, pull_down_en, intr_type; } gpio_config_t;
int gpio_get_level(gpio_num_t);
int gpio_config(const gpio_config_t *);
typedef void *i2c_master_dev_handle_t;
typedef void *i2c_master_bus_handle_t;
#define I2C_ADDR_BIT_LEN_7 0
typedef struct { int dev_addr_length, device_address, scl_speed_hz; } i2c_device_config_t;
int bsp_i2c_init(void);
i2c_master_bus_handle_t bsp_i2c_get_handle(void);
int i2c_master_bus_add_device(void *, const i2c_device_config_t *, void **);
int i2c_master_bus_rm_device(void *);
int i2c_master_transmit_receive(void *, const uint8_t *, size_t, uint8_t *, size_t, int);
int i2c_master_transmit(void *, const uint8_t *, size_t, int);
"""

AUDIO = r"""
#include "pet_audio.c"
static int saved = -1, commits, output_volume, loudest;
static bool muted;
void *bsp_audio_codec_speaker_init(void) { return (void *)1; }
void *bsp_audio_codec_microphone_init(void) { return (void *)2; }
int esp_codec_dev_open(void *h, esp_codec_dev_sample_info_t *f) { return 0; }
int esp_codec_dev_set_out_vol(void *h, int v) {
    output_volume = v; if (v > loudest) loudest = v; return 0;
}
int esp_codec_dev_set_out_mute(void *h, bool m) { muted = m; return 0; }
int esp_codec_dev_set_in_gain(void *h, float v) { return 0; }
int esp_codec_dev_read(void *h, void *p, int n) { return -1; }
int esp_codec_dev_write(void *h, void *p, int n) { return 0; }
void *xSemaphoreCreateMutex(void) { return (void *)1; }
int xSemaphoreTake(void *s, TickType_t t) { return 1; }
int xSemaphoreGive(void *s) { return 1; }
int nvs_open(const char *ns, int mode, nvs_handle_t *h) {
    assert(strcmp(ns, "pet") == 0); *h = 1; return 0;
}
int nvs_get_u8(nvs_handle_t h, const char *key, uint8_t *v) {
    assert(strcmp(key, "volume") == 0);
    if (saved < 0) return ESP_ERR_NOT_FOUND;
    *v = saved; return 0;
}
int nvs_set_u8(nvs_handle_t h, const char *key, uint8_t v) {
    assert(strcmp(key, "volume") == 0); saved = v; return 0;
}
int nvs_commit(nvs_handle_t h) { commits++; return 0; }
void nvs_close(nvs_handle_t h) {}
int main(void) {
    /* Brand-new firmware must never apply the old 75% startup volume. */
    pet_audio_start();
    assert(pet_audio_get_volume() == 5 && output_volume == 5 && loudest == 5);
    assert(!muted && commits == 0);
    assert(pet_audio_adjust_volume(-5) == 0 && muted && saved == 0);
    int before = commits;
    assert(pet_audio_adjust_volume(-5) == 0 && commits == before);
    /* Reboot preserves real zero/mute instead of converting it to a minimum. */
    pet_audio_start();
    assert(pet_audio_get_volume() == 0 && output_volume == 0 && muted);
    assert(pet_audio_adjust_volume(5) == 5 && !muted && saved == 5);
    for (int i = 0; i < 30; i++) pet_audio_adjust_volume(5);
    assert(pet_audio_get_volume() == 100 && saved == 100);
    before = commits;
    assert(pet_audio_adjust_volume(5) == 100 && commits == before);
    for (int i = 0; i < 30; i++) pet_audio_adjust_volume(-5);
    assert(pet_audio_get_volume() == 0 && muted && saved == 0);
    /* Invalid stored data falls back quietly. */
    saved = 255; loudest = 0; pet_audio_start();
    assert(pet_audio_get_volume() == 5 && output_volume == 5 && loudest == 5);
    return 0;
}
"""

BUTTONS = r"""
#include "pet_controls.c"
static int level = 1, writes;
static uint8_t registers[256];
int gpio_get_level(gpio_num_t g) { return level; }
int gpio_config(const gpio_config_t *c) { return 0; }
TickType_t xTaskGetTickCount(void) { return 0; }
void vTaskDelay(TickType_t t) {}
BaseType_t xTaskCreate(void (*f)(void *), const char *n, unsigned s, void *a, unsigned p, void *h) { return pdPASS; }
int pet_audio_adjust_volume(int d) { return 5; }
void pet_face_show_volume(int v) {}
void pet_face_toggle_menu(void) {}
void pet_face_set(const char *p, const char *t) {}
int bsp_i2c_init(void) { return 0; }
void *bsp_i2c_get_handle(void) { return (void *)1; }
int i2c_master_bus_add_device(void *b, const i2c_device_config_t *c, void **d) {
    assert(c->device_address == 0x34); *d = (void *)1; return 0;
}
int i2c_master_bus_rm_device(void *d) { return 0; }
int i2c_master_transmit_receive(void *d, const uint8_t *tx, size_t tn, uint8_t *rx, size_t rn, int t) {
    assert(tn == 1 && rn == 1); *rx = registers[*tx]; return 0;
}
int i2c_master_transmit(void *d, const uint8_t *tx, size_t n, int t) {
    assert(n == 2 && (tx[0] == 0x22 || tx[0] == 0x27));
    registers[tx[0]] = tx[1]; writes++; return 0;
}
int main(void) {
    /* No volume change from a held key at startup. Require a stable release. */
    volume_button_t b = {.gpio = GPIO_NUM_0, .raw_pressed = true, .pressed = true};
    level = 0; assert(!button_pressed(&b, 1000));
    level = 1; assert(!button_pressed(&b, 1010));
    assert(!button_pressed(&b, 1040));
    /* Contact bounce must yield exactly one press; holding never repeats. */
    level = 0; assert(!button_pressed(&b, 1100));
    level = 1; assert(!button_pressed(&b, 1110));
    level = 0; assert(!button_pressed(&b, 1120));
    assert(!button_pressed(&b, 1149));
    assert(button_pressed(&b, 1150));
    assert(!button_pressed(&b, 5000));
    /* Tick counter rollover must not break debounce. */
    b = (volume_button_t){.gpio = GPIO_NUM_18, .armed = true};
    level = 0; assert(!button_pressed(&b, UINT32_MAX - 10));
    assert(!button_pressed(&b, 18));
    assert(button_pressed(&b, 19));
    assert(VOLUME_DOWN_GPIO==GPIO_NUM_0 && VOLUME_UP_GPIO==GPIO_NUM_18);
    /* Left short press: one volume step on release, zero on initial press. */
    bool menu=false;
    b=(volume_button_t){.gpio=VOLUME_DOWN_GPIO,.delta=-5,.armed=true};
    level=0;assert(button_action(&b,100,&menu)==0);
    assert(button_action(&b,130,&menu)==0 && !menu);
    level=1;assert(button_action(&b,200,&menu)==0);
    assert(button_action(&b,230,&menu)==-5 && !menu);
    assert(button_action(&b,240,&menu)==0);
    /* Long hold opens menu once, with no volume change even on release. */
    level=0;assert(button_action(&b,300,&menu)==0);
    assert(button_action(&b,330,&menu)==0 && !menu);
    assert(button_action(&b,1529,&menu)==0 && !menu);
    assert(button_action(&b,1530,&menu)==0 && menu);
    menu=false;assert(button_action(&b,9999,&menu)==0 && !menu);
    level=1;button_action(&b,10000,&menu);assert(button_action(&b,10030,&menu)==0 && !menu);
    /* Hold across tick wrap behaves identically. Boot-held left is ignored. */
    b=(volume_button_t){.gpio=VOLUME_DOWN_GPIO,.delta=-5,.armed=true};
    level=0;button_action(&b,UINT32_MAX-100,&menu);button_action(&b,UINT32_MAX-70,&menu);
    assert(button_action(&b,1129,&menu)==0 && menu);
    menu=false;b=(volume_button_t){.gpio=VOLUME_DOWN_GPIO,.delta=-5,.raw_pressed=true,.pressed=true};
    assert(button_action(&b,9999,&menu)==0 && !menu);
    /* Preserve every unrelated PMU register/bit, including power-on timing. */
    memset(registers, 0xa5, sizeof(registers));
    registers[0x03] = 0x4a; registers[0x27] = 0xff;
    assert(configure_power_key() == ESP_OK && writes == 2);
    assert(registers[0x22] == 0xa6 && registers[0x27] == 0xf3);
    for (int i = 0; i < 256; i++) {
        if (i != 0x03 && i != 0x22 && i != 0x27) assert(registers[i] == 0xa5);
    }
    /* Never write a device that fails the AXP2101 identity check. */
    registers[0x03] = 0; writes = 0;
    assert(configure_power_key() == ESP_ERR_NOT_FOUND && writes == 0);
    return 0;
}
"""


class ControlsTests(unittest.TestCase):
    def run_firmware(self, code):
        compiler = shutil.which("cc")
        self.assertIsNotNone(compiler, "Install a host C compiler first")
        with tempfile.TemporaryDirectory(prefix="deskpet-controls-") as folder:
            root = Path(folder)
            (root / "host_sdk.h").write_text(SDK)
            for name in [
                "bsp/esp-bsp.h", "esp_codec_dev.h", "esp_log.h", "nvs.h",
                "freertos/FreeRTOS.h", "freertos/semphr.h", "freertos/task.h",
                "driver/gpio.h", "driver/i2c_master.h",
            ]:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('#include "host_sdk.h"\n')
            source = root / "check.c"
            source.write_text(code)
            executable = root / "check"
            subprocess.run([
                compiler, "-std=c17", "-DPET_AUDIO_HOST_VOLUME_ONLY", "-I", str(root), "-I", str(MAIN),
                str(source), "-lm", "-o", str(executable),
            ], check=True, capture_output=True, text=True)
            subprocess.run([str(executable)], check=True, capture_output=True, text=True)

    def test_quiet_first_boot_persisted_mute_and_volume_limits(self):
        self.run_firmware(AUDIO)

    def test_button_bounce_hold_rollover_and_power_register_isolation(self):
        self.run_firmware(BUTTONS)


if __name__ == "__main__":
    unittest.main()
