#pragma once
#include "pet_scene.h"
#define PET_SCENE_WIRE_VERSION 1
#define PET_SCENE_WIRE_WORDS 34
/* Fixed signed int32 fields; no raw struct/ABI/pointer data crosses platforms. */
void pet_scene_export(const pet_scene_t *s,int32_t out[PET_SCENE_WIRE_WORDS]);
bool pet_scene_import(pet_scene_t *s,const int32_t *wire,size_t words,uint32_t now,uint32_t remote_now);

void pet_scene_predict(pet_scene_t*s,pet_scene_input_t input);
