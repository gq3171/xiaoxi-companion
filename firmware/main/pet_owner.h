#pragma once
#include <stdbool.h>
#include <stdint.h>
#ifdef ESP_PLATFORM
#include "sdkconfig.h"
#endif
bool pet_owner_configured(void);
bool pet_owner_locked(void);
int pet_owner_stage(const int16_t *pcm, int samples);
int pet_owner_add_sample(const int16_t *pcm, int samples);
bool pet_owner_storage_ok(void);
int pet_owner_error_code(void);
float pet_owner_verify_candidate(const int16_t *pcm, int samples);
int pet_owner_commit(void);
void pet_owner_abort(void);
/* Negative means unavailable/invalid, never an authentication pass. */
float pet_owner_verify(const int16_t *pcm, int samples);
#ifdef CONFIG_DESKPET_LOCAL_OWNER
/* Preliminary threshold for this specific local embedding model, not a
 * probability or a calibrated accuracy claim. Cloud scoring is unchanged. */
#define PET_OWNER_THRESHOLD 0.60f
/* More tolerant daily conversation; enrollment/owner changes stay at .60. */
#define PET_OWNER_CONVERSATION_THRESHOLD 0.55f
#else
#define PET_OWNER_THRESHOLD 0.75f
#define PET_OWNER_CONVERSATION_THRESHOLD PET_OWNER_THRESHOLD
#endif
