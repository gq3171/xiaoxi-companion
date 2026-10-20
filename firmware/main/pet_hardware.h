#pragma once
#include <stdbool.h>
#include <stddef.h>

typedef struct {
    int battery_percent; /* -1 when absent or unreadable. */
    int battery_mv;
    bool usb_power;
    bool moving;
    bool clock_valid;
    bool imu_ready;
    int tilt_x,tilt_y,rotation_dps;
    unsigned motion_event,motion_sequence;
} pet_hardware_state_t;

void pet_hardware_start(void);
void pet_hardware_network_ready(void);
pet_hardware_state_t pet_hardware_state(void);
int pet_hardware_local_minute(void);
void pet_hardware_description(char *out, size_t capacity);
