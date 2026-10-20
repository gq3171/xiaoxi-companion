#pragma once
#include <stdbool.h>
#include <stddef.h>
/* Pure, bounded conversion. Chinese names of 1–4 Han characters only.
 * Name polyphones use the generated default reading; no guessed truncation. */
bool pet_wake_name_build(const char *name,char *phrase,size_t phrase_size,char *pinyin,size_t pinyin_size);
