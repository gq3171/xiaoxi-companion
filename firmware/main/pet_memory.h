#pragma once
#include <stdbool.h>
#include <stddef.h>
#include "cJSON.h"

/* The complete rotating store is bounded to two 64 KiB slots. */
int pet_memory_start(void);
int pet_memory_observe(const char *kind, const char *detail);
int pet_memory_add(const char *role, const char *text, bool owner);
cJSON *pet_memory_history(void);
void pet_memory_context(const char *query, char *out, size_t capacity);
bool pet_memory_needs_reflection(void);
char *pet_memory_reflection_request(void);
int pet_memory_apply_reflection(const char *json);
int pet_memory_clear_pending(void);
int pet_memory_ignore_message(int id);
/* Migration uses an authoritative server state and a local recovery mirror. */
char *pet_memory_export(void);
int pet_memory_install_remote(const cJSON *snapshot);

#include <stdint.h>
typedef struct { int id; uint32_t content_crc; } pet_memory_rejection_t;
/* Trusted correction only: IDs must also match the exact content fingerprint.
 * Removes dependent cards/growth and invalidates the lossy summary atomically. */
int pet_memory_reject_sources(const pet_memory_rejection_t *sources, size_t count);
