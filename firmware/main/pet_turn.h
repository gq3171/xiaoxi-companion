#pragma once
#include <stdbool.h>
#include <stdint.h>

uint32_t pet_turn_current(void);
uint32_t pet_turn_next(void);
bool pet_turn_valid(uint32_t generation);

/* Advance only if no newer voice/UI turn has already superseded this one. */
uint32_t pet_turn_claim(uint32_t expected);
