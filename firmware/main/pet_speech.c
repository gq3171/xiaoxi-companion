#include "pet_speech.h"
#ifdef ESP_PLATFORM
#include "sdkconfig.h"
#endif
#include <string.h>
#include "pet_audio.h"
#include "pet_cloud.h"
#include "pet_face.h"
#include "pet_turn.h"

static size_t s_delivered;
static bool s_audible;
size_t pet_speech_delivered_bytes(void) { return s_delivered; }
bool pet_speech_audible(void) { return s_audible; }

size_t pet_speech_chunk(const char *text, size_t max_bytes)
{
    size_t length = strlen(text);
    if (length <= max_bytes) return length;
    size_t n = max_bytes;
    while (n && ((unsigned char)text[n] & 0xc0) == 0x80) n--;
    size_t boundary = 0;
    for (size_t i = 0; i < n; i++) {
        if (text[i] == '.' || text[i] == '!' || text[i] == '?' || text[i] == '\n') boundary = i + 1;
        if (i + 3 <= n && (!memcmp(text + i, "。", 3) || !memcmp(text + i, "！", 3) || !memcmp(text + i, "？", 3) || !memcmp(text + i, "，", 3))) boundary = i + 3;
    }
    return boundary > n / 3 ? boundary : n;
}

typedef struct {uint32_t generation;const char *text;bool started;} speech_sink_t;
static bool play_chunk(const int16_t *pcm,size_t samples,void *user)
{
    speech_sink_t *s=user;
    if(!pet_turn_valid(s->generation)||!pet_audio_output_allowed())return false;
    if(!s->started){pet_face_set("说",s->text);s->started=true;}
    bool accepted=pet_audio_stream_write(pcm,samples,s->generation);
    if(accepted&&samples)s_audible=true;
    return accepted;
}

int pet_speech_say(const char *text, uint32_t generation, int16_t *pcm, int capacity)
{
    (void)pcm;(void)capacity;
    s_delivered = 0;
    s_audible = false;
    if (!pet_turn_valid(generation)) return -1;
    if (!pet_audio_output_allowed() || pet_audio_get_volume() == 0) {
        pet_face_set("在这儿", text); s_delivered = strlen(text); return 0;
    }
#ifdef CONFIG_DESKPET_REMOTE_BRAIN
    /* A bounded batch fits the existing per-request time budget. RK prepares
     * 150-byte subsegments one ahead; longer replies continue in later batches. */
    enum { SPEECH_BATCH_BYTES=450 };
#else
    enum { SPEECH_BATCH_BYTES=150 };
#endif
    while (*text) {
        if (!pet_turn_valid(generation) || !pet_audio_output_allowed()) return -1;
        size_t length = pet_speech_chunk(text, SPEECH_BATCH_BYTES);
        if (!length) return -1;
        char part[SPEECH_BATCH_BYTES+1]; memcpy(part, text, length); part[length] = 0;
        speech_sink_t sink={.generation=generation,.text=part};
        if(!pet_audio_stream_begin(generation))return -1;
        int samples=pet_cloud_speak_stream(part,play_chunk,&sink);
        bool complete=samples>0&&pet_turn_valid(generation);
        pet_audio_stream_end(complete);
        if(!complete||!pet_audio_stream_ok())return -1;
        if (!pet_turn_valid(generation)) return -1;
        s_delivered += length;
        text += length;
    }
    pet_face_set("在这儿", NULL); return 0;
}
