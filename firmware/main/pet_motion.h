#pragma once
#include <stdbool.h>
#include <stdint.h>
enum {PET_MOTION_MOVED=1,PET_MOTION_SETTLED=2,PET_MOTION_SHAKEN=4,PET_MOTION_TILTED=8,PET_MOTION_TURNED=16};
typedef struct {
    bool ready,moving,have_time,have_event;
    unsigned warmup,active,still,impulses;
    uint32_t last_ms,shake_window,last_shake,last_event;
    float previous[3],gravity[3],baseline[3];
    int tilt_x,tilt_y,rotation_dps;
} pet_motion_t;
/* Acceleration in g, gyro in degrees/sec; 20Hz fresh sensor samples. */
unsigned pet_motion_step(pet_motion_t *s,const float acceleration[3],const float gyro[3],uint32_t now);
