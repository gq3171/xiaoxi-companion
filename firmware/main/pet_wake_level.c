#include "pet_wake_level.h"
#include <math.h>
#include <stdlib.h>
void pet_wake_level(pet_wake_level_t *state,int16_t *pcm,size_t samples)
{
    if(!state||!pcm||!samples)return;
    double sum=0;int peak=0;
    for(size_t i=0;i<samples;i++){
        int value=abs((int)pcm[i]);if(value>peak)peak=value;
        sum+=(double)pcm[i]*pcm[i];
    }
    float rms=sqrt(sum/samples),gain=state->gain>=1?state->gain:1;
    if(rms>=40){
        state->quiet_frames=0;
        float target=fminf(8,fmaxf(1,1400/rms));
        gain+=(target-gain)*0.35f;
    }else if(++state->quiet_frames>=25){
        state->quiet_frames=25;gain+=(1-gain)*0.1f;
    }
    /* Back off in this very frame before multiplying a sudden loud onset. */
    if(peak>0)gain=fminf(gain,fmaxf(1,24000.0f/peak));
    state->gain=gain;
    for(size_t i=0;i<samples;i++)pcm[i]=(int16_t)lroundf(pcm[i]*gain);
}
