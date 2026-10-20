#include "pet_turn.h"
#include <stdatomic.h>

static atomic_uint s_generation = 1;
uint32_t pet_turn_current(void) { return atomic_load(&s_generation); }
uint32_t pet_turn_next(void) { return atomic_fetch_add(&s_generation, 1) + 1; }
bool pet_turn_valid(uint32_t generation) { return generation == pet_turn_current(); }

uint32_t pet_turn_claim(uint32_t expected)
{
    uint32_t next=expected+1;
    return atomic_compare_exchange_strong(&s_generation,&expected,next)?next:0;
}
