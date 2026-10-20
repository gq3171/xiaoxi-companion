#include "pet_screen.h"

void pet_screen_activity(pet_screen_t *screen, uint32_t now)
{
    screen->initialized = true;
    screen->last_activity = now;
    screen->forced_off = false;
}
void pet_screen_off(pet_screen_t *screen){screen->forced_off=true;}

int pet_screen_brightness(pet_screen_t *screen, uint32_t now, bool usb,
                          bool busy, bool low)
{
    if (!screen->initialized || screen->usb_power != usb || (busy&&!screen->forced_off))
        pet_screen_activity(screen, now);
    screen->usb_power = usb;
    if(screen->forced_off)return 0;
    uint32_t idle = now - screen->last_activity;
    uint32_t timeout = usb ? 300000 : 60000, fade = usb ? 15000 : 10000;
    int full = low && !usb ? 50 : 75;
    if (idle >= timeout) return 0;
    if (idle <= timeout - fade) return full;
    /* Monotonic and nonzero throughout fading; zero only at the deadline. */
    return 1 + (int)((uint64_t)(full - 1) * (timeout - idle) / fade);
}
