#pragma once
#include <stdbool.h>
#include <stdint.h>
typedef struct {
    float gravity[3];
    uint32_t last_ms,candidate_since,last_reaction;
    unsigned rotation,candidate;
    bool initialized,pending,reacted,leaning;
} pet_orientation_t;
enum {PET_ORIENT_TILTED=8,PET_ORIENT_TURNED=16};
/* Native screen gravity axes: +x right, +y down, +z towards viewer; units g.
 * The board mounting transform belongs in pet_hardware, not boot calibration. */
unsigned pet_orientation_step(pet_orientation_t *s,const float gravity[3],const float gyro[3],uint32_t now);
/* LCD rotates content clockwise. Touch uses the exact inverse transform. */
void pet_orientation_touch(unsigned rotation,int edge,int *x,int *y);
void pet_orientation_vector(unsigned rotation,float *x,float *y);

/* Assembled 2.16-inch board: sensor +X points to the screen top, +Y left. */
void pet_orientation_from_qmi(const float acceleration[3],float screen_gravity[3]);
