#include "pet_wake_gate.h"
#include <stdatomic.h>
static atomic_bool s_required,s_open,s_hold;
static atomic_uint s_until,s_feedback_until;
static atomic_uint s_interactions;
static atomic_uint s_activations;
static atomic_bool s_resting;
static atomic_uint s_end_epoch,s_media_epoch;
static atomic_bool s_media_return;
unsigned pet_wake_interactions(void){return atomic_load(&s_interactions);}
unsigned pet_wake_activations(void){return atomic_load(&s_activations);}
bool pet_wake_resting(void){return atomic_load(&s_resting);}
void pet_wake_rest(void){atomic_store(&s_resting,true);pet_wake_end_conversation();}
void pet_wake_require(bool required)
{
    if(atomic_exchange(&s_required,required)!=required){atomic_store(&s_open,false);atomic_store(&s_hold,false);}
}
bool pet_wake_required(void){return atomic_load(&s_required);}
bool pet_wake_active(uint32_t now)
{
    if(!pet_wake_required())return true;
    if(!atomic_load(&s_open))return false;
    return atomic_load(&s_hold)||(int32_t)(atomic_load(&s_until)-now)>0;
}
void pet_wake_open(uint32_t now){atomic_store(&s_until,now+20000);atomic_store(&s_open,true);atomic_store(&s_resting,false);atomic_fetch_add(&s_interactions,1);atomic_fetch_add(&s_activations,1);}
void pet_wake_hold(bool holding,uint32_t now)
{
    if(holding&&atomic_load(&s_open))atomic_store(&s_hold,true);
    else atomic_store(&s_hold,false);
    (void)now; /* Processing is not evidence that somebody addressed the pet. */
}
void pet_wake_activity(uint32_t now){if(atomic_load(&s_open))atomic_store(&s_until,now+20000);atomic_fetch_add(&s_interactions,1);}
void pet_wake_sleep(void){atomic_store(&s_open,false);atomic_store(&s_hold,false);}
void pet_wake_end_conversation(void){atomic_fetch_add(&s_end_epoch,1);pet_wake_sleep();}
void pet_wake_media_begin(void){atomic_store(&s_media_epoch,atomic_load(&s_end_epoch));atomic_store(&s_media_return,!pet_wake_resting());}
bool pet_wake_media_return(uint32_t now){
    bool resume=atomic_exchange(&s_media_return,false)&&atomic_load(&s_media_epoch)==atomic_load(&s_end_epoch)&&!pet_wake_resting();
    if(resume)pet_wake_open(now);
    return resume;
}

void pet_wake_heard(uint32_t now){pet_wake_open(now);atomic_store(&s_feedback_until,now+2500);}
bool pet_wake_feedback(uint32_t now){unsigned until=atomic_load(&s_feedback_until);return until&&(int32_t)(until-now)>0;}
