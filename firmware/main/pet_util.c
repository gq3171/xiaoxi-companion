#include "pet_util.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "esp_heap_caps.h"

void *pet_alloc(size_t size)
{
    void *p = heap_caps_malloc(size, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    return p ? p : malloc(size);
}

char *pet_strdup(const char *text)
{
    if (!text) return NULL;
    size_t n = strlen(text) + 1;
    char *p = pet_alloc(n);
    if (p) memcpy(p, text, n);
    return p;
}

size_t pet_utf8_copy(char *dest, size_t size, const char *source)
{
    if (!size) return 0;
    size_t n = strlen(source);
    if (n >= size) {
        n = size - 1;
        while (n && ((unsigned char)source[n] & 0xc0) == 0x80) n--;
    }
    memcpy(dest, source, n);
    dest[n] = 0;
    return n;
}

uint32_t pet_crc32(const void *data, size_t size)
{
    const unsigned char *bytes = data;
    uint32_t crc = UINT32_MAX;
    for (size_t i = 0; i < size; i++) {
        crc ^= bytes[i];
        for (int bit = 0; bit < 8; bit++) crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1u)));
    }
    return ~crc;
}

typedef struct { uint32_t magic, version, sequence, length, crc; } snapshot_header_t;
#define SNAPSHOT_MAGIC 0x50455432u

static char *load_slot(const char *base, int slot, size_t limit, uint32_t *sequence)
{
    char path[96];
    snprintf(path, sizeof(path), "%s.%d", base, slot);
    FILE *file = fopen(path, "rb");
    if (!file) return NULL;
    snapshot_header_t h;
    char *data = NULL;
    if (fread(&h, sizeof(h), 1, file) == 1 && h.magic == SNAPSHOT_MAGIC &&
        h.version == 1 && h.length && h.length <= limit) {
        data = pet_alloc(h.length + 1);
        if (data && (fread(data, 1, h.length, file) != h.length || fgetc(file) != EOF ||
                     pet_crc32(data, h.length) != h.crc)) {
            free(data);
            data = NULL;
        }
        if (data) { data[h.length] = 0; *sequence = h.sequence; }
    }
    fclose(file);
    return data;
}

char *pet_snapshot_load(const char *base, size_t limit, uint32_t *sequence)
{
    uint32_t a_seq = 0, b_seq = 0;
    char *a = load_slot(base, 0, limit, &a_seq);
    char *b = load_slot(base, 1, limit, &b_seq);
    if (a && (!b || (int32_t)(a_seq - b_seq) > 0)) {
        free(b); *sequence = a_seq; return a;
    }
    if (b) { free(a); *sequence = b_seq; return b; }
    *sequence = 0;
    return NULL;
}

bool pet_snapshot_exists(const char *base)
{
    /* SPIFFS implements fopen/stat but not POSIX access(). */
    for (int slot = 0; slot < 2; slot++) {
        char path[96]; snprintf(path, sizeof(path), "%s.%d", base, slot);
        FILE *file = fopen(path, "rb");
        if (file) { fclose(file); return true; }
    }
    return false;
}

int pet_snapshot_save(const char *base, const char *json, size_t limit, uint32_t *sequence)
{
    size_t length = strlen(json);
    if (!length || length > limit) return -1;
    uint32_t next = *sequence + 1;
    snapshot_header_t h = {SNAPSHOT_MAGIC, 1, next, length, pet_crc32(json, length)};
    char path[96];
    snprintf(path, sizeof(path), "%s.%u", base, (unsigned)(next & 1u));
    FILE *file = fopen(path, "wb");
    if (!file) return -1;
    int okay = fwrite(&h, sizeof(h), 1, file) == 1 && fwrite(json, 1, length, file) == length;
    if (fflush(file) != 0) okay = 0;
    if (fsync(fileno(file)) != 0) okay = 0;
    if (fclose(file) != 0) okay = 0;
    if (!okay) return -1;
    uint32_t checked_seq = 0;
    char *checked = load_slot(base, next & 1u, limit, &checked_seq);
    okay = checked && checked_seq == next && strcmp(checked, json) == 0;
    free(checked);
    if (!okay) return -1;
    *sequence = next;
    return 0;
}
