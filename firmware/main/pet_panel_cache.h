#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define PET_PANEL_HEADER 4096u
#define PET_PANEL_HEADER_BYTES 64u
typedef struct {uint32_t kind,bytes;uint8_t sha[32];} pet_panel_spec_t;
void pet_panel_sha256(const void *data,size_t n,uint8_t out[32]);
bool pet_panel_cache_header(const uint8_t *p,size_t capacity,uint32_t *kind,uint32_t *bytes,uint32_t *sequence);
bool pet_panel_cache_valid(const uint8_t *p,size_t capacity,const pet_panel_spec_t *spec);
int pet_panel_cache_target(const uint8_t *a,size_t an,const uint8_t *b,size_t bn,uint32_t *sequence);
void pet_panel_cache_commit(uint8_t header[PET_PANEL_HEADER_BYTES],const pet_panel_spec_t *spec,uint32_t sequence);
