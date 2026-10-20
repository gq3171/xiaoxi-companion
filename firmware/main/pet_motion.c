#include "pet_motion.h"
#include <math.h>
#include <string.h>
static int bounded(float n){int v=(int)lroundf(n);return v< -7?-7:v>7?7:v;}
unsigned pet_motion_step(pet_motion_t*s,const float a[3],const float g[3],uint32_t now)
{
    for(int i=0;i<3;i++)if(!isfinite(a[i])||!isfinite(g[i])||fabsf(a[i])>8.1f||fabsf(g[i])>520)return 0;
    if(s->have_time && (uint32_t)(now-s->last_ms)>500){
        /* Never classify a stale sample gap as a sudden shake. */
        s->ready=false;s->warmup=s->active=s->still=s->impulses=0;s->moving=false;
    }
    s->last_ms=now;
    float delta=0,rotation=0,norm=0;
    for(int i=0;i<3;i++){float d=a[i]-s->previous[i];delta+=d*d;rotation+=g[i]*g[i];norm+=a[i]*a[i];}
    if(!s->have_time){memcpy(s->gravity,a,sizeof(s->gravity));memcpy(s->previous,a,sizeof(s->previous));s->have_time=true;return 0;}
    memcpy(s->previous,a,sizeof(s->previous));s->rotation_dps=(int)sqrtf(rotation);
    for(int i=0;i<3;i++)s->gravity[i]=s->gravity[i]*.9f+a[i]*.1f;
    bool energetic=delta>.035f||rotation>225;
    if(!s->ready){
        if(!energetic&&norm>.72f&&norm<1.32f)s->warmup++;else s->warmup=0;
        if(s->warmup>=20){memcpy(s->baseline,s->gravity,sizeof(s->baseline));s->ready=true;}
        return 0;
    }
    s->tilt_x=bounded((s->gravity[0]-s->baseline[0])*9);
    s->tilt_y=bounded((s->gravity[1]-s->baseline[1])*6);
    unsigned event=0;
    if(energetic){s->still=0;if(s->active<3)s->active++;
        if(s->active>=3&&!s->moving){s->moving=true;
            if(!s->have_event||(uint32_t)(now-s->last_event)>=8000){event|=PET_MOTION_MOVED;s->last_event=now;s->have_event=true;}
        }
    }else{s->active=0;if(s->still<24)s->still++;
        if(s->moving&&s->still>=24){s->moving=false;event|=PET_MOTION_SETTLED;}
    }
    if((uint32_t)(now-s->shake_window)>800){s->shake_window=now;s->impulses=0;}
    /* Multiple strong changes, never a single impact or constant rotation. */
    if(delta>.25f)s->impulses++;
    if(s->impulses>=3&&(s->last_shake==0||(uint32_t)(now-s->last_shake)>=15000)){
        event|=PET_MOTION_SHAKEN;s->last_shake=now;s->impulses=0;
    }
    return event;
}
