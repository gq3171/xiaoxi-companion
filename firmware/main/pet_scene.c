#include "pet_scene.h"
#include <math.h>
#include <stdlib.h>
#define WORK_STEP_IN_MS 1800u
#define WALK_CEL_MS 180u
static unsigned walk_phase(uint32_t age){return age/WALK_CEL_MS%4;}
static unsigned front_walk(unsigned phase){
 static const unsigned frames[]={PET_POSE_WALK_A,PET_ART_FRONT_PASS_A,PET_POSE_WALK_B,PET_ART_FRONT_PASS_B};
 return frames[phase%4];
}
static bool walking_pose(pet_pose_t p){return p==PET_POSE_WALK_A||p==PET_POSE_WALK_B||p==PET_POSE_WALK_BACK_A||p==PET_POSE_WALK_BACK_B;}

static void completed(pet_scene_t*s,pet_home_activity_t a){if(!s->replica)pet_home_complete(a);}
static bool before(uint32_t a,uint32_t b){return (int32_t)(a-b)<0;}
static void position(pet_scene_t*s,int x,int y){s->precise_x=s->x=x;s->precise_y=s->y=y;}
static bool in_bed(pet_scene_t*s){return s->activity==PET_HOME_SLEEPING||s->activity==PET_HOME_GETTING_IN_BED||s->activity==PET_HOME_WAKING;}
void pet_scene_init(pet_scene_t*s,uint32_t now){
 *s=(pet_scene_t){.x=240,.y=390,.precise_x=240,.precise_y=390,.target_x=240,.target_y=390,
 .next_blink=now+3000,.blink_until=now,.reaction_until=now,.next_walk=now+14000,
 .last_engaged=now,.last_step=now,.stage_started=now};pet_home_report(s->activity,s->place,s->destination,s->x,s->y);
}
static void face_route(pet_scene_t*s){
 s->transition_x=s->x;s->transition_y=s->y;
 int dy=s->route_y[s->route_index]-s->y;
 /* Choose once per segment. The remaining dy approaches zero at every
  * waypoint; re-evaluating it each frame briefly flashed the front pose. */
 if(dy<-4)s->walk_backwards=true;
 else if(dy>4)s->walk_backwards=false;
}
static void travel(pet_scene_t*s,pet_place_t place,uint32_t now,int x,int y){
 s->activity=PET_HOME_WALKING;s->destination=place;s->route_index=0;s->route_length=0;
 int a=s->x,b=s->y;pet_home_floor_clamp(&a,&b);position(s,a,b);
 /* A central corridor avoids cutting through beds and tables. */
 if(abs(s->x-240)>20||abs(s->y-338)>30){s->route_x[s->route_length]=240;s->route_y[s->route_length++]=338;}
 if(place!=PET_PLACE_FLOOR&&place!=PET_PLACE_WASH){s->route_x[s->route_length]=240;s->route_y[s->route_length++]=310;}
 s->route_x[s->route_length]=x;s->route_y[s->route_length++]=y;
 s->target_x=x;s->target_y=y;s->stage_started=now;s->reaction=PET_POSE_IDLE;
 face_route(s);
}
void pet_scene_command(pet_scene_t*s,pet_home_action_t action,uint32_t now){
 if(action<=PET_HOME_NONE||action>PET_HOME_READ)return;
 s->reading_requested=action==PET_HOME_READ;
 s->pressed=s->dragging=false;s->last_engaged=now;s->next_walk=now+18000;
 if(action==PET_HOME_WORK&&s->place==PET_PLACE_WORK&&s->activity!=PET_HOME_WALKING)return;
 if(action==PET_HOME_WASH&&s->activity==PET_HOME_WASHING)return;
 if(s->activity==PET_HOME_STANDING){s->after_wake=action;return;}
 if((s->place==PET_PLACE_WORK&&(s->activity==PET_HOME_WAIT_COMPUTER||s->activity==PET_HOME_WORKING||s->activity==PET_HOME_SITTING))||s->activity==PET_HOME_WASHING){
  s->transition_x=s->x;s->transition_y=s->y;
  s->after_wake=action;s->activity=PET_HOME_STANDING;s->stage_started=now;return;
 }
 if(in_bed(s)&&action!=PET_HOME_REST){
  if(s->activity==PET_HOME_SLEEPING)completed(s,PET_HOME_SLEEPING);
  s->after_wake=action==PET_HOME_WAKE?PET_HOME_WASH:action;s->activity=PET_HOME_WAKING;s->stage_started=now;
  position(s,pet_home_spots[PET_PLACE_BED].approach_x,pet_home_spots[PET_PLACE_BED].approach_y);return;
 }
 if(action==PET_HOME_WAKE)action=PET_HOME_WASH;
 if(action==PET_HOME_REST&&s->activity==PET_HOME_SLEEPING)return;
 pet_place_t place=action==PET_HOME_REST?PET_PLACE_BED:action==PET_HOME_WASH?PET_PLACE_WASH:action==PET_HOME_WORK?PET_PLACE_WORK:(action==PET_HOME_WINDOW||action==PET_HOME_READ)?PET_PLACE_WINDOW:PET_PLACE_FLOOR;
 travel(s,place,now,pet_home_spots[place].approach_x,pet_home_spots[place].approach_y);
}
void pet_scene_react(pet_scene_t*s,pet_pose_t pose,uint32_t now){
 if(pose!=PET_POSE_HAPPY&&pose!=PET_POSE_THINK&&pose!=PET_POSE_SLEEP&&pose!=PET_POSE_TOUCH&&pose!=PET_POSE_SURPRISE)return;
 s->reaction=pose;s->reaction_until=now+2200;s->last_engaged=now;s->next_walk=now+12000;
}
void pet_scene_press(pet_scene_t*s,int x,int y,uint32_t now){
 if(in_bed(s))pet_scene_command(s,PET_HOME_ROAM,now);
 s->pressed=true;s->dragging=s->moved=false;s->press_x=x;s->press_y=y;s->anchor_x=s->x;s->anchor_y=s->y;
 pet_scene_react(s,PET_POSE_TOUCH,now);
}
void pet_scene_drag(pet_scene_t*s,int x,int y){
 if(!s->pressed)return;
 int dx=x-s->press_x,dy=y-s->press_y;
 if(abs(dx)>6||abs(dy)>6)s->moved=s->dragging=true;
 if(!s->dragging)return;
 int a=s->anchor_x+dx,b=s->anchor_y+dy;pet_home_floor_clamp(&a,&b);position(s,a,b);
 s->target_x=a;s->target_y=b;s->activity=PET_HOME_IDLE;s->place=PET_PLACE_FLOOR;
}
bool pet_scene_release(pet_scene_t*s,uint32_t now){
 if(!s->pressed)return false;
 bool tap=!s->moved;s->pressed=s->dragging=false;
 pet_scene_react(s,tap?PET_POSE_HAPPY:PET_POSE_TOUCH,now);return tap;
}
static void arrive(pet_scene_t*s,uint32_t now){
 s->place=s->destination;s->stage_started=now;const pet_home_spot_t*p=&pet_home_spots[s->place];
 switch(s->place){
 case PET_PLACE_BED:s->activity=PET_HOME_GETTING_IN_BED;break;
 case PET_PLACE_WASH:s->activity=PET_HOME_WASHING;position(s,p->use_x,p->use_y);break;
 case PET_PLACE_WORK:s->activity=PET_HOME_SITTING;break;
 case PET_PLACE_WINDOW:s->activity=s->reading_requested?PET_HOME_READING:PET_HOME_LOOKING;break;
 default:s->activity=PET_HOME_IDLE;break;}
}
void pet_scene_projection(const pet_scene_t*s,int*left,int*top,int*scale){
 /* Register the sleeping cel's head to the pillow, rather than centering its
  * mostly-transparent canvas above the bed's floor/use anchor. */
 if(s->activity==PET_HOME_SLEEPING||(s->activity==PET_HOME_GETTING_IN_BED&&s->last_step-s->stage_started>=1500)||(s->activity==PET_HOME_WAKING&&s->last_step-s->stage_started<350)){*scale=PET_BED_SLEEP_SCALE;*left=PET_BED_PILLOW_X-PET_BED_HEAD_X*(*scale)/256;*top=PET_BED_PILLOW_Y-PET_BED_HEAD_Y*(*scale)/256;return;}
 *scale=pet_home_scale(s->y);*left=s->x-208*(*scale)/512;*top=s->y-264*(*scale)/256;
}
void pet_scene_step(pet_scene_t*s,pet_scene_input_t in){
 s->replica=in.replica;
 uint32_t now=in.now_ms,elapsed=now-s->last_step,dt=elapsed>150?150:elapsed;
 uint32_t animation=in.phase_valid?in.phase_ms:now;
 bool live=in.listening||in.thinking||in.speaking;
 if(in.blocked){s->stage_started+=elapsed;s->last_engaged=now;s->next_walk=now+12000;s->last_step=now;s->pressed=s->dragging=false;return;}
 pet_home_action_t command=in.replica?PET_HOME_NONE:pet_home_take_request();if(command!=PET_HOME_NONE)pet_scene_command(s,command,now);
 if(s->activity==PET_HOME_WORKING||s->activity==PET_HOME_WAIT_COMPUTER)
  s->activity=pet_home_computer_state()==PET_COMPUTER_RUNNING?PET_HOME_WORKING:PET_HOME_WAIT_COMPUTER;
 if(in.clock_valid&&!in.replica){
  if(s->clock_seen&&s->was_night&&!in.night&&s->activity==PET_HOME_SLEEPING)pet_scene_command(s,PET_HOME_WAKE,now);
  s->clock_seen=true;s->was_night=in.night;
 }
 if(live){
  s->last_engaged=now;s->next_walk=now+12000;
  uint32_t paused=now-s->stage_started;s->stage_started+=paused<elapsed?paused:elapsed;
  /* VAD, ASR and output are not a request to get out of bed. Only an
   * explicit wake/touch or accepted room command may change that activity. */
  s->pose=s->activity==PET_HOME_SLEEPING?PET_POSE_LIE_SLEEP:in_bed(s)?PET_POSE_WAKE:(s->place==PET_PLACE_WORK&&(s->activity==PET_HOME_WAIT_COMPUTER||s->activity==PET_HOME_WORKING))?PET_POSE_WORK_B:
   in.listening?PET_POSE_LISTEN:in.speaking?(animation/180%2?PET_POSE_SPEAK:PET_POSE_IDLE):PET_POSE_THINK;
 }else if(s->pressed)s->pose=PET_POSE_TOUCH;
 else{
  uint32_t age=now-s->stage_started;
  if(s->activity==PET_HOME_WALKING){
   int x=s->route_x[s->route_index],y=s->route_y[s->route_index];float dx=x-s->precise_x,dy=y-s->precise_y,d=sqrtf(dx*dx+dy*dy);
   float step=(24.0f+(s->y-292)*.06f)*dt/1000;bool backwards=s->walk_backwards;
   if(d<=step||d<.5f){position(s,x,y);if(++s->route_index==s->route_length)arrive(s,now);else face_route(s);}
   else{s->precise_x+=dx/d*step;s->precise_y+=dy/d*step;s->x=(int)lroundf(s->precise_x);s->y=(int)lroundf(s->precise_y);}
   s->pose=backwards?(walk_phase(age)<2?PET_POSE_WALK_BACK_A:PET_POSE_WALK_BACK_B):(walk_phase(age)<2?PET_POSE_WALK_A:PET_POSE_WALK_B);
  }else if(s->activity==PET_HOME_GETTING_IN_BED){
   s->pose=PET_POSE_WAKE;if(age>=2600){s->activity=PET_HOME_SLEEPING;s->stage_started=now;position(s,pet_home_spots[PET_PLACE_BED].use_x,pet_home_spots[PET_PLACE_BED].use_y);s->pose=PET_POSE_LIE_SLEEP;}
  }else if(s->activity==PET_HOME_SLEEPING)s->pose=PET_POSE_LIE_SLEEP;
  else if(s->activity==PET_HOME_WAKING){
   s->pose=PET_POSE_WAKE;if(age>=3400){completed(s,PET_HOME_WAKING);pet_home_action_t next=s->after_wake;s->activity=PET_HOME_IDLE;s->place=PET_PLACE_FLOOR;pet_scene_command(s,next?next:PET_HOME_ROAM,now);}
  }else if(s->activity==PET_HOME_WASHING){s->pose=age<3000?PET_POSE_WASH_A:PET_POSE_WASH_B;if(age>=6500){completed(s,PET_HOME_WASHING);pet_scene_command(s,PET_HOME_ROAM,now);}}
  else if(s->activity==PET_HOME_SITTING){
   /* approach is outside the desk; keep walking upright until the seat anchor.
    * A seated sprite must never slide across the floor towards the chair. */
   const pet_home_spot_t*p=&pet_home_spots[PET_PLACE_WORK];unsigned progress=age>WORK_STEP_IN_MS?WORK_STEP_IN_MS:age;
   position(s,p->approach_x+(p->use_x-p->approach_x)*(int)progress/(int)WORK_STEP_IN_MS,p->approach_y+(p->use_y-p->approach_y)*(int)progress/(int)WORK_STEP_IN_MS);
   s->pose=animation/280%2?PET_POSE_WALK_BACK_A:PET_POSE_WALK_BACK_B;
   if(age>=WORK_STEP_IN_MS){s->activity=PET_HOME_WAIT_COMPUTER;s->stage_started=now;s->pose=PET_POSE_WORK_A;}
  }else if(s->activity==PET_HOME_STANDING){
   const pet_home_spot_t*p=&pet_home_spots[s->place];unsigned progress=age>900?900:age;
   position(s,s->transition_x+(p->approach_x-s->transition_x)*(int)progress/900,s->transition_y+(p->approach_y-s->transition_y)*(int)progress/900);
   s->pose=s->place==PET_PLACE_WORK?(animation/280%2?PET_POSE_WALK_A:PET_POSE_WALK_B):PET_POSE_IDLE;
   if(age>=900){pet_home_action_t next=s->after_wake;s->place=PET_PLACE_FLOOR;s->activity=PET_HOME_IDLE;pet_scene_command(s,next,now);}
  }else if(s->activity==PET_HOME_READING){
   s->pose=animation/3100%2?PET_POSE_IDLE:PET_POSE_BLINK;
   if(age>=25000){completed(s,PET_HOME_READING);pet_scene_command(s,PET_HOME_ROAM,now);}
  }else if(s->activity==PET_HOME_WAIT_COMPUTER||s->activity==PET_HOME_WORKING){
   bool running=pet_home_computer_state()==PET_COMPUTER_RUNNING;s->activity=running?PET_HOME_WORKING:PET_HOME_WAIT_COMPUTER;
   s->pose=running?(animation/550%2?PET_POSE_WORK_A:PET_POSE_WORK_B):PET_POSE_WORK_A;
   if(!running&&age>30000)pet_scene_command(s,PET_HOME_ROAM,now);
  }else if(s->activity==PET_HOME_LOOKING){s->pose=PET_POSE_THINK;if(age>7000){completed(s,PET_HOME_LOOKING);pet_scene_command(s,PET_HOME_ROAM,now);}}
  else if(!in.replica&&(in.night||in.tired)&&now-s->last_engaged>=45000)pet_scene_command(s,PET_HOME_REST,now);
  else if(s->reaction!=PET_POSE_IDLE&&before(now,s->reaction_until))s->pose=s->reaction;
  else{
   s->reaction=PET_POSE_IDLE;
   if(!in.replica&&!before(now,s->next_walk)){
    if(in.random%8==0)pet_scene_command(s,PET_HOME_WINDOW,now);
    else{int x=95+(int)(in.random%290),y=292+(int)((in.random/290)%134);pet_home_floor_clamp(&x,&y);travel(s,PET_PLACE_FLOOR,now,x,y);}
    s->next_walk=now+18000+in.random%18000;
   }
   if(!before(now,s->next_blink)){s->blink_until=now+180;s->next_blink=now+2800+in.random%4200;}
   s->pose=before(now,s->blink_until)?PET_POSE_BLINK:PET_POSE_IDLE;
  }
 }
 s->last_step=now;pet_home_report(s->activity,s->place,s->destination,s->x,s->y);
}

unsigned pet_scene_art_frame(const pet_scene_t*s,uint32_t now)
{
 if(!s)return PET_POSE_IDLE;
 uint32_t age=now-s->stage_started;
 if(s->activity==PET_HOME_GETTING_IN_BED){
  if(age<700)return front_walk(walk_phase(age));
  return age<1500?PET_ART_BED_SIT:PET_POSE_LIE_SLEEP;
 }
 if(s->activity==PET_HOME_WAKING){
  if(age<350)return PET_POSE_LIE_SLEEP;
  if(age<1100)return PET_ART_BED_SIT;
  if(age<1900)return PET_ART_BED_STRETCH;
  return age<3000?PET_ART_STAND_STRETCH:PET_ART_STAND_RELAX;
 }
 if(s->activity==PET_HOME_WALKING&&s->route_index<s->route_length&&walking_pose(s->pose)){
  int dx=s->route_x[s->route_index]-s->transition_x,dy=s->route_y[s->route_index]-s->transition_y;
  if(abs(dx)>8&&abs(dx)*4>=abs(dy)*3)return (dx<0?PET_ART_SIDE_LEFT_0:PET_ART_SIDE_RIGHT_0)+walk_phase(age);
  if(dy<0&&dx>3)return walk_phase(age)<2?PET_ART_BACK_RIGHT_A:PET_ART_BACK_RIGHT_B;
  if(!s->walk_backwards)return front_walk(walk_phase(age));
 }
 return (unsigned)s->pose;
}

void pet_scene_walk_to(pet_scene_t*s,int x,int y,uint32_t now){if(!s)return;pet_home_floor_clamp(&x,&y);s->pressed=s->dragging=false;s->last_engaged=now;s->next_walk=now+18000;travel(s,PET_PLACE_FLOOR,now,x,y);}
