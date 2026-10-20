#pragma once
#include <stdbool.h>
#include <stdint.h>

/* Conversation continuity is temporary trust, not a new biometric measurement.
 * Protected owner changes still call pet_owner_verify directly. */
#define PET_OWNER_SESSION_IDLE_US (90LL * 1000000)
#define PET_OWNER_SESSION_MAX_US (5LL * 60 * 1000000)
bool pet_owner_session_active(void);
bool pet_owner_session_authorize(const int16_t *pcm, int samples, uint32_t generation);
/* Everyday companion mode: content quality only, never biometric identity.
 * Other nearby speakers can converse too; this never replaces the owner. */
bool pet_owner_conversation_accept(const int16_t *pcm, int samples, uint32_t generation);
const char *pet_owner_session_hint(void);
void pet_owner_session_begin(void);
void pet_owner_session_activity(void);
/* Safe from UI/network tasks; other session operations belong to the worker. */
void pet_owner_session_reset(void);
