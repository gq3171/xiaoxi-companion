#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "character/pet_character_assets.h"
#ifdef ESP_PLATFORM
#include "sdkconfig.h"
#endif
#ifdef CONFIG_DESKPET_PANEL_CACHE
int pet_panel_start(void);
void pet_panel_bind(void); /* Caller owns the LVGL lock. */
void pet_panel_tick(uint32_t now,bool idle);
bool pet_panel_font_bind(const uint8_t *data,size_t bytes);
bool pet_panel_art_bind(const uint8_t *data,size_t bytes);
const pet_character_frame_t *pet_panel_frame(unsigned pose);
const uint8_t *pet_panel_room(size_t *bytes);
const uint8_t *pet_panel_yard(size_t *bytes);
#else
static inline int pet_panel_start(void){return 0;}
static inline void pet_panel_bind(void){}
static inline void pet_panel_tick(uint32_t now,bool idle){(void)now;(void)idle;}
static inline const pet_character_frame_t *pet_panel_frame(unsigned pose){return &pet_character_frames[pose];}
static inline const uint8_t *pet_panel_yard(size_t *bytes){*bytes=pet_yard_compressed_size;return pet_yard_compressed;}
static inline const uint8_t *pet_panel_room(size_t *bytes){*bytes=pet_room_compressed_size;return pet_room_compressed;}
#endif
