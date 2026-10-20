#pragma once
#include <stdint.h>
#include <stddef.h>
#include "pet_scene.h"
#define PET_CHARACTER_WIDTH 208
#define PET_CHARACTER_HEIGHT 264
typedef struct { const uint8_t *palette_bgra; const uint8_t *compressed; size_t compressed_size; bool mirror; } pet_character_frame_t;
extern const pet_character_frame_t pet_character_frames[PET_ART_COUNT];
extern const uint8_t *const pet_room_compressed;
extern const size_t pet_room_compressed_size;

extern const uint8_t *const pet_yard_compressed;
extern const size_t pet_yard_compressed_size;
