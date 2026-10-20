#pragma once
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

void *pet_alloc(size_t size);
char *pet_strdup(const char *text);
/* A terminated copy that never splits a UTF-8 character. Returns bytes copied. */
size_t pet_utf8_copy(char *dest, size_t size, const char *source);
uint32_t pet_crc32(const void *data, size_t size);
/* Two independently checked slots; a torn write leaves the preceding slot intact. */
char *pet_snapshot_load(const char *base, size_t limit, uint32_t *sequence);
bool pet_snapshot_exists(const char *base);
int pet_snapshot_save(const char *base, const char *json, size_t limit, uint32_t *sequence);
