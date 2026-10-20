"""New body paths: prepared for daytime execution, not executed at night."""
import unittest
import test_runtime_core as core


class ImprovementsHostTests(unittest.TestCase):
    def test_read_page_pauses_for_dialogue_and_finishes_only_after_actual_dwell(self):
        core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include "pet_scene.h"
int main(void){
 pet_scene_t scene;pet_scene_init(&scene,0);unsigned now=0;
 assert(pet_home_request_text("read"));
 for(int i=0;i<900&&scene.activity!=PET_HOME_READING;i++){
  now+=100;pet_scene_step(&scene,(pet_scene_input_t){.now_ms=now,.clock_valid=true});
 }
 assert(scene.activity==PET_HOME_READING&&scene.place==PET_PLACE_WINDOW);
 unsigned before=pet_home_completion();
 for(int i=0;i<300;i++){
  now+=100;pet_scene_step(&scene,(pet_scene_input_t){.now_ms=now,.clock_valid=true,.listening=true});
 }
 assert(scene.activity==PET_HOME_READING&&pet_home_completion()==before);
 for(int i=0;i<270&&pet_home_completion()==before;i++){
  now+=100;pet_scene_step(&scene,(pet_scene_input_t){.now_ms=now,.clock_valid=true});
 }
 assert((pet_home_completion()&15)==PET_HOME_READING);
 assert(scene.activity==PET_HOME_WALKING);
 pet_scene_command(&scene,PET_HOME_REST,now);
 for(int i=0;i<900&&scene.activity!=PET_HOME_SLEEPING;i++){
  now+=100;pet_scene_step(&scene,(pet_scene_input_t){.now_ms=now,.clock_valid=true});
 }
 assert(scene.activity==PET_HOME_SLEEPING);
 return 0;
}
''',['pet_scene','pet_home'])

    def test_remote_speech_uses_one_stream_and_incomplete_output_is_not_complete(self):
        core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include "pet_speech.h"
#include "pet_turn.h"
static int requests;static bool fail,allowed=true;
bool pet_audio_output_allowed(void){return allowed;}
int pet_audio_get_volume(void){return 5;}
void pet_face_set(const char *phase,const char *text){}
bool pet_audio_stream_begin(uint32_t generation){return true;}
bool pet_audio_stream_ok(void){return true;}
void pet_audio_stream_end(bool complete){}
bool pet_audio_stream_write(const int16_t *pcm,size_t samples,uint32_t generation){return pet_turn_valid(generation);}
int pet_cloud_speak_stream(const char *text,bool(*sink)(const int16_t*,size_t,void*),void *user){
 requests++;assert(strlen(text)>150);int16_t pcm[16]={0};
 assert(sink(pcm,16,user));return fail?-1:16;
}
int main(void){
 const char *reply="窗前的小星星翻开绘本，读到了远处的山和云。她把这一页仔细看完，等你叫她时就先放下绘本听你说。我们留着下一页，之后有空再慢慢接着读。";
 uint32_t generation=pet_turn_current();
 assert(!pet_speech_say(reply,generation,0,0));
 assert(requests==1&&pet_speech_delivered_bytes()==strlen(reply)&&pet_speech_audible());
 fail=true;assert(pet_speech_say(reply,generation,0,0)==-1);
 assert(requests==2&&pet_speech_delivered_bytes()==0&&pet_speech_audible());
 allowed=false;assert(!pet_speech_say(reply,generation,0,0)&&requests==2&&!pet_speech_audible());
 return 0;
}
''',['pet_speech','pet_turn'],compiler_flags=['-DCONFIG_DESKPET_REMOTE_BRAIN=1'])


if __name__=='__main__':unittest.main()
