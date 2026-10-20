#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
/* UI-thread-only: bounded lossless decoding, exact length and checksum required. */
bool pet_asset_inflate(const uint8_t *input, size_t size, uint8_t *output, size_t expected);
/* One-time bilinear 320x320 -> 480x480 RGB565 expansion, no allocations. */
bool pet_asset_expand_room(const uint16_t *source, uint16_t *target);
