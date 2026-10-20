#include "pet_owner_session.h"
#include <math.h>
#include <stdatomic.h>
#include "esp_timer.h"
#include "pet_owner.h"
#include "pet_turn.h"
#include "pet_voice.h"

static atomic_uint s_revision;
static unsigned s_session_revision;
static bool s_open;
static int64_t s_started, s_last_activity;
static enum { NEEDS_SAMPLE, UNCLEAR_REPLY, UNCONFIRMED, UNAVAILABLE, INTERRUPTED } s_hint;

const char *pet_owner_session_hint(void)
{
    switch (s_hint) {
    case UNCLEAR_REPLY: return "刚才没听清，可以再说一遍。";
    case UNCONFIRMED: return "这次还没认准你的声音，请自然地再说一句完整的话。";
    case UNAVAILABLE: return "声音验证暂时未完成，请稍后再试。";
    case INTERRUPTED: return "刚才被打断了，请再说一次。";
    default: return "先说一句稍完整的话让我认出你，接下来就能简短回答。";
    }
}

void pet_owner_session_reset(void) { atomic_fetch_add(&s_revision, 1); }

bool pet_owner_session_active(void)
{
    int64_t now = esp_timer_get_time();
    if (!s_open || s_session_revision != atomic_load(&s_revision) ||
        now < s_last_activity || now < s_started ||
        now - s_last_activity >= PET_OWNER_SESSION_IDLE_US ||
        now - s_started >= PET_OWNER_SESSION_MAX_US) {
        s_open = false; return false;
    }
    return true;
}

void pet_owner_session_begin(void)
{
    s_started = s_last_activity = esp_timer_get_time();
    s_session_revision = atomic_load(&s_revision); s_open = true;
}

void pet_owner_session_activity(void)
{
    if (pet_owner_session_active()) s_last_activity = esp_timer_get_time();
}

bool pet_owner_conversation_accept(const int16_t *pcm, int samples, uint32_t generation)
{
    if (!pet_turn_valid(generation) || !pet_owner_locked()) {
        s_hint = INTERRUPTED; return false;
    }
    /* Registration protects ownership. Ordinary speech is not an identity
     * challenge, including the first short reply after a reboot or outage. */
    s_hint = UNCLEAR_REPLY;
    return pet_voice_reply_usable(pcm, samples) && pet_turn_valid(generation);
}

bool pet_owner_session_authorize(const int16_t *pcm, int samples, uint32_t generation)
{
    if (!pet_turn_valid(generation) || !pet_owner_locked()) {
        s_hint = INTERRUPTED; pet_owner_session_reset(); return false;
    }
    if (pet_owner_session_active()) {
        /* Identity is already established. A short acknowledgement is content,
         * not a second biometric sample; still reject silence and clipping. */
        s_hint = UNCLEAR_REPLY;
        return pet_voice_reply_usable(pcm, samples);
    }
    s_hint = NEEDS_SAMPLE;
    if (!pet_voice_usable(pcm, samples)) return false;
    unsigned revision = atomic_load(&s_revision);
    float score = pet_owner_verify(pcm, samples);
    if (!pet_turn_valid(generation) || revision != atomic_load(&s_revision)) { s_hint = INTERRUPTED; return false; }
    if (!isfinite(score) || score < 0) { s_hint = UNAVAILABLE; return false; }
    if (score < PET_OWNER_CONVERSATION_THRESHOLD) { s_hint = samples < 3 * 16000 ? NEEDS_SAMPLE : UNCONFIRMED; return false; }
    pet_owner_session_begin();
    /* A UI/network reset concurrent with begin must also invalidate this turn. */
    if (revision != atomic_load(&s_revision)) { pet_owner_session_reset(); return false; }
    return true;
}
