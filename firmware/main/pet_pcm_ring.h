#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdatomic.h>
typedef struct {int16_t *data;unsigned capacity;atomic_uint read,write;} pet_pcm_ring_t;
/* Capacity is a power of two, preserving indices across unsigned rollover. */
void pet_pcm_ring_init(pet_pcm_ring_t *r,int16_t *storage,unsigned capacity);
unsigned pet_pcm_ring_used(const pet_pcm_ring_t *r);
size_t pet_pcm_ring_push(pet_pcm_ring_t *r,const int16_t *data,size_t samples);
size_t pet_pcm_ring_pop(pet_pcm_ring_t *r,int16_t *data,size_t samples);
