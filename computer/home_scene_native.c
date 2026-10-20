/* Same room engine as the ESP32, built natively; only this bridge is host code. */
#include "pet_scene_wire.h"
#include <stdlib.h>
void *home_new(uint32_t now){pet_scene_t*s=calloc(1,sizeof(*s));if(s)pet_scene_init(s,now);return s;}
void home_free(void*p){free(p);}
int home_load(void*p,const int32_t*w,uint32_t now,uint32_t remote){return pet_scene_import(p,w,PET_SCENE_WIRE_WORDS,now,remote);}
void home_dump(void*p,int32_t*w){pet_scene_export(p,w);}
void home_step(void*p,uint32_t now,uint32_t random,unsigned flags,int computer){
 pet_home_computer_event(computer);
 pet_scene_step(p,(pet_scene_input_t){.now_ms=now,.random=random,.listening=flags&1,.speaking=flags&2,.thinking=flags&4,.blocked=flags&8,.night=flags&16,.tired=flags&32,.clock_valid=true});
}
int home_command(void*p,int action,uint32_t now,int x,int y){
 pet_scene_t*s=p;
 if(action>=1&&action<=PET_HOME_READ)pet_scene_command(s,action,now);
 else if(action==20){pet_scene_press(s,s->x,s->y,now);pet_scene_release(s,now);}
 else if(action==21){pet_home_floor_clamp(&x,&y);s->x=x;s->y=y;s->precise_x=x;s->precise_y=y;s->target_x=x;s->target_y=y;s->activity=PET_HOME_IDLE;s->place=PET_PLACE_FLOOR;s->destination=PET_PLACE_FLOOR;s->route_length=s->route_index=0;s->pressed=s->dragging=false;pet_scene_react(s,PET_POSE_TOUCH,now);s->pose=PET_POSE_TOUCH;}
 else if(action==23)pet_scene_walk_to(s,x,y,now);
 else if(action==22)pet_scene_react(s,x,now);
 else return 0;
 return 1;
}
void home_projection(void*p,int32_t*out){pet_scene_projection(p,out,out+1,out+2);}
unsigned home_completion(void){return pet_home_completion();}

unsigned home_art(void*p,uint32_t now){return pet_scene_art_frame(p,now);}
