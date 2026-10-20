"""Session expiry/cancellation with controlled scores; not biometric accuracy."""
import unittest
import test_runtime_core

class OwnerSessionHostTests(unittest.TestCase):
    def test_companion_mode_accepts_first_short_reply_without_biometric_challenge(self):
        code=r'''
#include <assert.h>
#include <string.h>
#include "pet_owner_session.h"
#include "pet_voice.h"
#include "pet_turn.h"
static int64_t now;
static bool locked=true;
int64_t esp_timer_get_time(void){return now;}
bool pet_owner_locked(void){return locked;}
/* Any accidental model invocation, even on the first turn, fails this test. */
float pet_owner_verify(const int16_t *p,int n){assert(0);return -1;}
int main(void){
 int16_t pcm[8000]={0};
 for(int i=3000;i<4600;i++)pcm[i]=(i%2)?1200:-1200;
 uint32_t g=pet_turn_current();
 assert(!pet_voice_usable(pcm,8000));
 assert(pet_owner_conversation_accept(pcm,8000,g));
 now=3600000000LL;pet_owner_session_reset();
 assert(pet_owner_conversation_accept(pcm,8000,g));
 pet_turn_next();assert(!pet_owner_conversation_accept(pcm,8000,g));
 g=pet_turn_current();locked=false;assert(!pet_owner_conversation_accept(pcm,8000,g));
 locked=true;memset(pcm,0,sizeof(pcm));assert(!pet_owner_conversation_accept(pcm,8000,g));
 assert(strstr(pet_owner_session_hint(),"没听清"));
 for(int i=0;i<8000;i++)pcm[i]=32767;
 assert(!pet_owner_conversation_accept(pcm,8000,g));return 0;
}
'''
        test_runtime_core.RuntimeCoreTests.run_c(self,code,['pet_owner_session','pet_turn','pet_voice','pet_util'],
            {'esp_timer.h':'#pragma once\n#include <stdint.h>\nint64_t esp_timer_get_time(void);\n'},
            ['-DCONFIG_DESKPET_LOCAL_OWNER=1'])

    def test_tolerant_conversation_bounded_continuity_and_reset(self):
        code = r'''
#include <assert.h>
#include <math.h>
#include "pet_owner.h"
#include "pet_owner_session.h"
#include "pet_turn.h"
static int64_t now;
static int checks, during;
static bool locked=true, usable=true;
static float score=.57f;
int64_t esp_timer_get_time(void){return now;}
bool pet_owner_locked(void){return locked;}
bool pet_voice_reply_usable(const int16_t *p,int n){return usable && p && n>=4000;}
bool pet_voice_usable(const int16_t *p,int n){return usable && p && n>=12000;}
float pet_owner_verify(const int16_t *p,int n){
    checks++;
    if(during==1)pet_turn_next();
    if(during==2)pet_owner_session_reset();
    return score;
}
int main(void){
    int16_t pcm[1]={0};uint32_t g=pet_turn_current();
    assert(PET_OWNER_THRESHOLD==.60f && PET_OWNER_CONVERSATION_THRESHOLD==.55f);
    assert(!pet_owner_session_active());
    assert(pet_owner_session_authorize(pcm,16000,g));assert(checks==1);
    /* A short answer with changed inflection does not run another biometric test. */
    score=.2f;now=10000000;
    assert(pet_owner_session_authorize(pcm,8000,g));assert(checks==1);
    pet_owner_session_activity();
    now+=PET_OWNER_SESSION_IDLE_US-1;assert(pet_owner_session_active());
    now++;assert(!pet_owner_session_active());
    assert(!pet_owner_session_authorize(pcm,16000,g) && checks==2);
    score=.55f;assert(pet_owner_session_authorize(pcm,16000,g));
    int64_t began=now;
    for(int i=1;i<5;i++){now=began+i*60000000LL;pet_owner_session_activity();assert(pet_owner_session_active());}
    now=began+PET_OWNER_SESSION_MAX_US;assert(!pet_owner_session_active());
    score=.549f;assert(!pet_owner_session_authorize(pcm,16000,g));
    score=NAN;assert(!pet_owner_session_authorize(pcm,16000,g));
    score=.7f;during=1;assert(!pet_owner_session_authorize(pcm,16000,g));
    during=0;g=pet_turn_current();during=2;assert(!pet_owner_session_authorize(pcm,16000,g));
    during=0;assert(pet_owner_session_authorize(pcm,16000,g));
    locked=false;assert(!pet_owner_session_authorize(pcm,16000,g));assert(!pet_owner_session_active());
    locked=true;assert(pet_owner_session_authorize(pcm,16000,g));
    usable=false;int before=checks;assert(!pet_owner_session_authorize(pcm,16000,g) && checks==before);
    usable=true;pet_owner_session_reset();assert(!pet_owner_session_active());
    assert(pet_owner_session_authorize(pcm,16000,g));now--;assert(!pet_owner_session_active());
    return 0;
}
'''
        test_runtime_core.RuntimeCoreTests.run_c(self, code, ['pet_owner_session','pet_turn'],
            {'esp_timer.h':'#pragma once\n#include <stdint.h>\nint64_t esp_timer_get_time(void);\n'},
            ['-DCONFIG_DESKPET_LOCAL_OWNER=1'])

    def test_real_short_reply_audio_is_content_only_after_owner_verification(self):
        code=r'''
#include <assert.h>
#include <string.h>
#include "pet_owner.h"
#include "pet_owner_session.h"
#include "pet_voice.h"
#include "pet_turn.h"
static int checks;
int64_t esp_timer_get_time(void){return 1000000;}
bool pet_owner_locked(void){return true;}
float pet_owner_verify(const int16_t *p,int n){checks++;return .7f;}
int main(void){
 int16_t pcm[16000]={0};
 /* Half-second capture with 100ms voice plus real pre-roll/tail silence. */
 for(int i=3000;i<4600;i++)pcm[i]=(i%2) ? 1200 : -1200;
 assert(!pet_voice_usable(pcm,8000) && pet_voice_reply_usable(pcm,8000));
 uint32_t g=pet_turn_current();
 assert(!pet_owner_session_authorize(pcm,8000,g) && checks==0);
 pet_owner_session_begin();
 assert(pet_owner_session_authorize(pcm,8000,g) && checks==0);
 memset(pcm,0,sizeof(pcm));assert(!pet_owner_session_authorize(pcm,8000,g));
 assert(strstr(pet_owner_session_hint(),"没听清"));
 for(int i=0;i<8000;i++)pcm[i]=32767;
 assert(!pet_owner_session_authorize(pcm,8000,g));
 pet_owner_session_reset();
 assert(!pet_owner_session_authorize(pcm,8000,g));return 0;
}
'''
        test_runtime_core.RuntimeCoreTests.run_c(self,code,['pet_owner_session','pet_turn','pet_voice','pet_util'],
            {'esp_timer.h':'#pragma once\n#include <stdint.h>\nint64_t esp_timer_get_time(void);\n'},
            ['-DCONFIG_DESKPET_LOCAL_OWNER=1'])
