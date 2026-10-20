#include "pet_scene_wire.h"
#include <math.h>
#include <string.h>
void pet_scene_export(const pet_scene_t*s,int32_t w[PET_SCENE_WIRE_WORDS]){
 int32_t a[]={s->x,s->y,s->target_x,s->target_y,(int32_t)lroundf(s->precise_x*1000),(int32_t)lroundf(s->precise_y*1000),
 s->next_blink,s->blink_until,s->next_walk,s->reaction_until,s->last_engaged,s->last_step,s->stage_started,
 s->dragging|s->pressed<<1|s->moved<<2|s->clock_seen<<3|s->was_night<<4|s->wake_wash<<5|s->reading_requested<<6|s->walk_backwards<<7,
 s->pose,s->reaction,s->activity,s->place,s->destination,s->after_wake,
 s->press_x,s->press_y,s->anchor_x,s->anchor_y,s->transition_x,s->transition_y,
 s->route_x[0],s->route_x[1],s->route_x[2],s->route_y[0],s->route_y[1],s->route_y[2],s->route_length,s->route_index};
 _Static_assert(sizeof(a)==PET_SCENE_WIRE_WORDS*sizeof(int32_t),"wire schema");memcpy(w,a,sizeof(a));
}
bool pet_scene_import(pet_scene_t*s,const int32_t*w,size_t n,uint32_t now,uint32_t remote){
 if(!s||!w||n!=PET_SCENE_WIRE_WORDS)return false;
 for(int i=0;i<6;i++)if(w[i]<0||w[i]>(i<4?479:479000))return false;
 if(w[13]<0||w[13]>255||w[14]<0||w[14]>=PET_POSE_COUNT||w[15]<0||w[15]>=PET_POSE_COUNT||w[16]<0||w[16]>PET_HOME_READING||w[17]<0||w[17]>=PET_PLACE_COUNT||w[18]<0||w[18]>=PET_PLACE_COUNT||w[19]<0||w[19]>PET_HOME_READ||w[32]<0||w[32]>3||w[33]<0||w[33]>w[32]||(w[16]==PET_HOME_WALKING&&w[33]>=w[32]))return false;
 for(int i=20;i<32;i++)if(w[i]<0||w[i]>479)return false;
 pet_scene_t t={0};t.x=w[0];t.y=w[1];t.target_x=w[2];t.target_y=w[3];t.precise_x=w[4]/1000.f;t.precise_y=w[5]/1000.f;
 uint32_t delta=now-remote;t.next_blink=(uint32_t)w[6]+delta;t.blink_until=(uint32_t)w[7]+delta;t.next_walk=(uint32_t)w[8]+delta;t.reaction_until=(uint32_t)w[9]+delta;t.last_engaged=(uint32_t)w[10]+delta;t.last_step=(uint32_t)w[11]+delta;t.stage_started=(uint32_t)w[12]+delta;
 unsigned f=w[13];t.dragging=f&1;t.pressed=f&2;t.moved=f&4;t.clock_seen=f&8;t.was_night=f&16;t.wake_wash=f&32;t.reading_requested=f&64;t.walk_backwards=f&128;
 t.pose=w[14];t.reaction=w[15];t.activity=w[16];t.place=w[17];t.destination=w[18];t.after_wake=w[19];
 t.press_x=w[20];t.press_y=w[21];t.anchor_x=w[22];t.anchor_y=w[23];t.transition_x=w[24];t.transition_y=w[25];
 for(int i=0;i<3;i++){t.route_x[i]=w[26+i];t.route_y[i]=w[29+i];}t.route_length=w[32];t.route_index=w[33];*s=t;return true;
}

void pet_scene_predict(pet_scene_t*s,pet_scene_input_t input){
 uint32_t now=input.now_ms,phase=input.phase_ms;
 /* Import may already be several network ticks old. Replay bounded small
  * physics steps, rather than dropping elapsed time at the 150ms guard. */
 while(now-s->last_step>100&&now-s->last_step<=3000){
  input.now_ms=s->last_step+100;input.phase_ms=phase-(now-input.now_ms);pet_scene_step(s,input);
 }
 input.now_ms=now;input.phase_ms=phase;pet_scene_step(s,input);
}
