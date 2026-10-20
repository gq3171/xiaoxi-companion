#include "pet_policy.h"

bool pet_policy_quiet(const pet_policy_t *p, int minute)
{
    if (minute < 0 || minute >= 1440) return true;
    if (p->quiet_start == p->quiet_end) return false;
    if (p->quiet_start < p->quiet_end) return minute >= p->quiet_start && minute < p->quiet_end;
    return minute >= p->quiet_start || minute < p->quiet_end;
}

bool pet_policy_audio(const pet_policy_t *p, bool clock_valid, int minute,
                      int64_t now, int64_t quiet_until, int64_t voice_until)
{
    if (voice_until > now) return true;
    if (quiet_until > now) return false;
    return clock_valid && !pet_policy_quiet(p, minute);
}

int pet_policy_backoff_minutes(int ignored, int base)
{
    if (base < 1) base = 1;
    if (base > 120) base = 120;
    while (ignored-- > 0 && base < 120) base = base > 60 ? 120 : base * 2;
    return base;
}
