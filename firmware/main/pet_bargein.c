#include "pet_bargein.h"

bool pet_bargein_voice(pet_bargein_t *s, bool playing, bool speech,
                       float raw, float reference, float clean, int64_t now)
{
    if (playing && !s->playing) { s->started = now; s->trusted = false; s->good_frames = 0; }
    if (!playing && s->playing) { s->tail_until = now + 320000; s->trusted = false; }
    s->playing = playing;
    if (!playing) return now >= s->tail_until && speech;
    /* Identify candidate double-talk only after measured echo suppression.
       This is not speaker identity or permission to interrupt playback. */
    if (!s->trusted && reference > 200 && raw > 200) {
        if (clean < raw * 0.25f) s->good_frames++;
        else s->good_frames = 0;
        if (s->good_frames >= 12 && now - s->started >= 600000) s->trusted = true;
    }
    return s->trusted && now - s->started >= 600000 && speech && clean > 600 && clean > raw * 0.35f;
}
