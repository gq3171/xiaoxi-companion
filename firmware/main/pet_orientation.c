#include "pet_orientation.h"
#include <math.h>
#include <string.h>
unsigned pet_orientation_step(pet_orientation_t *s,const float a[3],const float gyro[3],uint32_t now)
{
    float norm=0,spin=0;
    for(int i=0;i<3;i++){
        if(!isfinite(a[i])||!isfinite(gyro[i])){s->pending=false;return 0;}
        norm+=a[i]*a[i];spin+=gyro[i]*gyro[i];
    }
    if(norm<.65f||norm>1.45f||spin>3025){s->pending=false;s->initialized=false;return 0;}
    if(!s->initialized||(uint32_t)(now-s->last_ms)>300){memcpy(s->gravity,a,sizeof(s->gravity));s->pending=false;}
    else for(int i=0;i<3;i++)s->gravity[i]=.8f*s->gravity[i]+.2f*a[i];
    s->initialized=true;s->last_ms=now;
    float x=s->gravity[0],y=s->gravity[1],horizontal=x*x+y*y;
    /* Flat on desk, near a diagonal or shaking: keep the last readable view. */
    if(horizontal<.36f){s->pending=false;s->leaning=false;return 0;}
    unsigned wanted;
    if(fabsf(y)>fabsf(x)*1.35f)wanted=y>0?0:180;
    else if(fabsf(x)>fabsf(y)*1.35f)wanted=x>0?270:90;
    else {s->pending=false;return 0;}
    unsigned event=0;
    if(wanted!=s->rotation){
        if(!s->pending||wanted!=s->candidate){s->candidate=wanted;s->candidate_since=now;s->pending=true;}
        else if((uint32_t)(now-s->candidate_since)>=650){
            s->rotation=wanted;s->pending=false;
            if(!s->reacted||(uint32_t)(now-s->last_reaction)>=8000){event=PET_ORIENT_TURNED;s->last_reaction=now;s->reacted=true;}
        }
    }else s->pending=false;
    /* Tilt is measured in the currently upright canvas, rather than boot pose. */
    pet_orientation_vector(s->rotation,&x,&y);
    bool tilted=fabsf(x)>.32f&&y>.55f;
    if(!tilted&&fabsf(x)<.18f)s->leaning=false;
    if(tilted&&!s->leaning){
        s->leaning=true;
        if(!s->reacted||(uint32_t)(now-s->last_reaction)>=8000){event|=PET_ORIENT_TILTED;s->last_reaction=now;s->reacted=true;}
    }
    return event;
}
void pet_orientation_vector(unsigned r,float *x,float *y)
{
    float a=*x,b=*y;
    if(r==90){*x=b;*y=-a;}
    else if(r==180){*x=-a;*y=-b;}
    else if(r==270){*x=-b;*y=a;}
}
void pet_orientation_touch(unsigned r,int edge,int *x,int *y)
{
    int a=*x<0?0:*x>=edge?edge-1:*x,b=*y<0?0:*y>=edge?edge-1:*y;
    if(r==90){*x=b;*y=edge-1-a;}
    else if(r==180){*x=edge-1-a;*y=edge-1-b;}
    else if(r==270){*x=edge-1-b;*y=a;}
    else {*x=a;*y=b;}
}

void pet_orientation_from_qmi(const float a[3],float screen[3])
{
    /* USB down, screen toward owner: +ay; face-up: +az. The screen
     * gravity X opposes the accelerometer's proper-acceleration X. */
    float x=-a[0],y=a[1],z=a[2];
    screen[0]=x;screen[1]=y;screen[2]=z;
}
