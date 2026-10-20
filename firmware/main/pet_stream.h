#pragma once
#include <stdbool.h>
#include <stddef.h>

typedef bool (*pet_sse_event_fn)(const char *data, size_t length, void *user);
typedef struct {
    char *line, *data;
    size_t line_used, data_used, capacity;
    bool failed;
    pet_sse_event_fn event;
    void *user;
} pet_sse_t;
/* Caller supplies two capacity-byte buffers; events may span arbitrary HTTP chunks. */
void pet_sse_init(pet_sse_t *s, char *line, char *data, size_t capacity, pet_sse_event_fn event, void *user);
bool pet_sse_feed(pet_sse_t *s, const void *bytes, size_t length);
/* A truncated event is never silently accepted as a successful response. */
bool pet_sse_complete(const pet_sse_t *s);
