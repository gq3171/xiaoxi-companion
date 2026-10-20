#pragma once
#include <stdbool.h>
#include <stddef.h>
#include "cJSON.h"

typedef struct { cJSON *fields; } pet_birth_t;
void pet_birth_init(pet_birth_t *state);
void pet_birth_free(pet_birth_t *state);
const char *pet_birth_prompt(void);
char *pet_birth_request(const pet_birth_t *state, const char *answer, const cJSON *legacy);
/* Atomic model patch; -1 invalid, 0 needs more dialogue, 1 complete. */
int pet_birth_apply(pet_birth_t *state, const char *response, char *question, size_t capacity);
cJSON *pet_birth_identity(const pet_birth_t *state);
bool pet_birth_valid_identity(const cJSON *identity);
void pet_birth_summary(const cJSON *identity, char *out, size_t capacity);
