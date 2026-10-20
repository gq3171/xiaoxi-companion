#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

/* Explicit user controls only. Media bytes stay in bounded RAM, never SPIFFS. */
void pet_media_command(const char *action,int index,uint32_t generation);
void pet_media_tick(uint32_t generation);
void pet_media_context(char *out,size_t n);

bool pet_media_active(void);
bool pet_media_self_test(void);
/* Present the actual requested job, never a different recent catalog entry.
 * Audio/video opens paused; this does not authorize autoplay. */
bool pet_media_present_result(const char *job_id,uint32_t generation);
