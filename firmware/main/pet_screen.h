#pragma once
#include <stdbool.h>
#include <stdint.h>

/* Owned by the LVGL thread. Screen blanking never suspends capture or Wi-Fi. */
typedef struct {
    uint32_t last_activity;
    bool initialized, usb_power, forced_off;
} pet_screen_t;
void pet_screen_activity(pet_screen_t *screen, uint32_t now);
void pet_screen_off(pet_screen_t *screen);
/* Battery: 60s total, last 10s fading. USB: 300s, last 15s fading. */
int pet_screen_brightness(pet_screen_t *screen, uint32_t now, bool usb_power,
                          bool busy, bool low_battery);
