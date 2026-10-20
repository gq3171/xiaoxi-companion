#pragma once
#include "pet_scene_wire.h"
#ifdef ESP_PLATFORM
#include "sdkconfig.h"
#endif
typedef struct {bool valid,online;int location,cat_x,cat_y,cat_frame,cat_face,cat_mode,cat_hunger,cat_affection,cat_phase_ms,cat_walk_rate;} pet_home_world_t;
/* Advance only a moving gait; bound prediction during a connection stall. */
static inline void pet_home_cat_motion(pet_home_world_t*w,uint32_t elapsed){
 if(w->cat_walk_rate<=0||(w->cat_mode!=1&&w->cat_mode!=8&&w->cat_mode!=9))return;
 if(elapsed>750)elapsed=750;
 unsigned phase=((unsigned)w->cat_phase_ms+elapsed*(unsigned)w->cat_walk_rate/1000)%960;
 const int frames[]={PET_ART_CAT_WALK_A,PET_ART_CAT_WALK_B,PET_ART_CAT_WALK_C,PET_ART_CAT_WALK_D};
 w->cat_phase_ms=(int)phase;w->cat_frame=frames[phase/240];
}
#ifdef CONFIG_DESKPET_HOME_SYNC
void pet_home_sync_start(void);
void pet_home_sync_world(pet_home_world_t*out);
int pet_home_sync_world_request(const char*action);
bool pet_home_sync_step(pet_scene_t*s,pet_scene_input_t in,const char*phase,const char*caption);
void pet_home_sync_event(const char*action,int x,int y,uint32_t now);
int pet_home_sync_pair(char*out,size_t capacity);
int pet_home_sync_pair_code(char*out,size_t capacity);
bool pet_home_sync_take_reminder(char*out,size_t capacity);
void pet_home_sync_finish_reminder(bool played);
#else
static inline void pet_home_sync_start(void){}
static inline void pet_home_sync_world(pet_home_world_t*out){if(out)*out=(pet_home_world_t){0};}
static inline int pet_home_sync_world_request(const char*action){(void)action;return -1;}
static inline bool pet_home_sync_step(pet_scene_t*s,pet_scene_input_t in,const char*p,const char*c){(void)s;(void)in;(void)p;(void)c;return false;}
static inline void pet_home_sync_event(const char*a,int x,int y,uint32_t n){(void)a;(void)x;(void)y;(void)n;}
static inline bool pet_home_sync_take_reminder(char*out,size_t n){(void)out;(void)n;return false;}
static inline void pet_home_sync_finish_reminder(bool p){(void)p;}
static inline int pet_home_sync_pair_code(char*out,size_t n){(void)out;(void)n;return -1;}
static inline int pet_home_sync_pair(char*out,size_t n){(void)out;(void)n;return -1;}
#endif
