#include "pet_controls.h"

#include <assert.h>
#include <stdbool.h>
#include <stdint.h>

#include "bsp/esp-bsp.h"
#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "pet_audio.h"
#include "pet_face.h"

/* User's front-of-screen view, confirmed on the assembled device:
 * BOOT/GPIO0 is left, PWR is middle, GPIO18 is right. */
#define VOLUME_DOWN_GPIO GPIO_NUM_0
#define VOLUME_UP_GPIO GPIO_NUM_18
#define BUTTON_POLL_MS 10
#define BUTTON_DEBOUNCE_MS 30
#define MENU_HOLD_MS 1200

/* AXP2101 register definitions verified against Waveshare's bundled XPowersLib:
 * https://github.com/waveshareteam/ESP32-S3-Touch-AMOLED-2.16/tree/main/examples/esp-idf/01_AXP2101/components/XPowersLib
 * Only PWR-key timing/behavior is changed; supply rails and charging are untouched.
 */
#define AXP2101_ADDRESS 0x34
#define AXP2101_IC_TYPE 0x03
#define AXP2101_CHIP_ID 0x4a
#define AXP2101_PWROFF_EN 0x22
#define AXP2101_KEY_TIMING 0x27

static const char *TAG = "pet_controls";

static esp_err_t read_pmu(i2c_master_dev_handle_t pmu, uint8_t reg, uint8_t *value)
{
    return i2c_master_transmit_receive(pmu, &reg, 1, value, 1, 100);
}

static esp_err_t update_pmu(i2c_master_dev_handle_t pmu, uint8_t reg,
                            uint8_t mask, uint8_t bits)
{
    uint8_t value;
    esp_err_t err = read_pmu(pmu, reg, &value);
    if (err != ESP_OK) return err;
    uint8_t data[] = {reg, (value & (uint8_t)~mask) | bits};
    err = i2c_master_transmit(pmu, data, sizeof(data), 100);
    if (err != ESP_OK) return err;
    err = read_pmu(pmu, reg, &value);
    if (err != ESP_OK) return err;
    return (value & mask) == bits ? ESP_OK : ESP_FAIL;
}

static esp_err_t configure_power_key(void)
{
    esp_err_t err = bsp_i2c_init();
    if (err != ESP_OK) return err;
    i2c_device_config_t config = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = AXP2101_ADDRESS,
        .scl_speed_hz = 100000,
    };
    i2c_master_dev_handle_t pmu;
    err = i2c_master_bus_add_device(bsp_i2c_get_handle(), &config, &pmu);
    if (err != ESP_OK) return err;
    uint8_t id;
    err = read_pmu(pmu, AXP2101_IC_TYPE, &id);
    if (err == ESP_OK && id != AXP2101_CHIP_ID) err = ESP_ERR_NOT_FOUND;
    if (err == ESP_OK) {
        /* OFFLEVEL bits 3:2 = 00: hold PWR for 4 seconds. Keep power-on timing. */
        err = update_pmu(pmu, AXP2101_KEY_TIMING, 0x0c, 0x00);
    }
    if (err == ESP_OK) {
        /* Enable long-press shutdown (bit 1); choose power-off, not reboot (bit 0). */
        err = update_pmu(pmu, AXP2101_PWROFF_EN, 0x03, 0x02);
    }
    i2c_master_bus_rm_device(pmu);
    return err;
}

typedef struct {
    gpio_num_t gpio;
    int delta;
    bool raw_pressed;
    bool pressed;
    bool armed;
    TickType_t changed_at;
    TickType_t hold_started;
    bool pending_short;
} volume_button_t;

static bool button_pressed(volume_button_t *button, TickType_t now)
{
    bool raw = gpio_get_level(button->gpio) == 0;
    if (raw != button->raw_pressed) {
        button->raw_pressed = raw;
        button->changed_at = now;
    }
    if ((TickType_t)(now - button->changed_at) < pdMS_TO_TICKS(BUTTON_DEBOUNCE_MS)) {
        return false;
    }
    if (!raw) button->armed = true;
    if (raw == button->pressed) return false;
    button->pressed = raw;
    return raw && button->armed;
}

static int button_action(volume_button_t *button, TickType_t now, bool *menu)
{
    if (button_pressed(button, now)) {
        if (button->gpio != VOLUME_DOWN_GPIO) return button->delta;
        /* Defer - until release so opening a menu never changes volume. */
        button->hold_started = now; button->pending_short = true;
    }
    if (!button->pending_short) return 0;
    if ((TickType_t)(now - button->hold_started) >= pdMS_TO_TICKS(MENU_HOLD_MS)) {
        button->pending_short = false; *menu = true; return 0;
    }
    if (!button->pressed) { button->pending_short = false; return button->delta; }
    return 0;
}

static void volume_buttons(void *arg)
{
    volume_button_t buttons[] = {
        {.gpio = VOLUME_DOWN_GPIO, .delta = -PET_VOLUME_STEP},
        {.gpio = VOLUME_UP_GPIO, .delta = PET_VOLUME_STEP},
    };
    TickType_t now = xTaskGetTickCount();
    for (size_t i = 0; i < 2; i++) {
        buttons[i].raw_pressed = gpio_get_level(buttons[i].gpio) == 0;
        buttons[i].pressed = buttons[i].raw_pressed;
        buttons[i].changed_at = now;
    }
    while (true) {
        now = xTaskGetTickCount();
        int delta = 0;
        bool menu = false;
        for (size_t i = 0; i < 2; i++) {
            delta += button_action(&buttons[i], now, &menu);
        }
        if (menu) pet_face_toggle_menu();
        if (delta) {
            int volume = pet_audio_adjust_volume(delta);
            if (volume >= 0) pet_face_show_volume(volume);
        }
        /* One action per hold, including boot-held keys and tick rollover. */
        vTaskDelay(pdMS_TO_TICKS(BUTTON_POLL_MS));
    }
}

void pet_controls_start(void)
{
    gpio_config_t buttons = {
        .pin_bit_mask = (1ULL << VOLUME_DOWN_GPIO) | (1ULL << VOLUME_UP_GPIO),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&buttons));
    esp_err_t err = configure_power_key();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "PWR key configuration failed: %s", esp_err_to_name(err));
        pet_face_set("在这儿", "电源键配置失败");
    } else {
        ESP_LOGI(TAG, "PWR key: hardware shutdown after 4 seconds");
    }
    BaseType_t started = xTaskCreate(volume_buttons, "pet_buttons", 4096, NULL, 5, NULL);
    assert(started == pdPASS);
}
