import unittest
import test_runtime_core as core
class SceneWireTests(unittest.TestCase):
    def test_scene_wire_is_portable_bounded_and_preserves_clock_wrap_and_routes(self):
        core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include <string.h>
#include <stdlib.h>
#include "pet_scene_wire.h"
int main(void){
 pet_scene_t s;pet_scene_init(&s,0xfffffff0u);pet_scene_command(&s,PET_HOME_REST,0xfffffff0u);
 int32_t w[PET_SCENE_WIRE_WORDS];pet_scene_export(&s,w);pet_scene_t replica={0};
 assert(pet_scene_import(&replica,w,PET_SCENE_WIRE_WORDS,300,0xfffffff0u));
 assert(replica.x==s.x&&replica.route_length==s.route_length&&replica.stage_started==300&&replica.next_blink==3300);
 pet_scene_t good=replica;int32_t saved=w[14];w[14]=PET_POSE_COUNT;
 assert(!pet_scene_import(&replica,w,PET_SCENE_WIRE_WORDS,300,0));assert(!memcmp(&replica,&good,sizeof(good)));w[14]=saved;
 w[32]=w[33]=3;assert(!pet_scene_import(&replica,w,PET_SCENE_WIRE_WORDS,300,0));
 pet_scene_init(&s,0);s.next_walk=1;
 for(uint32_t t=50;t<30000;t+=50)pet_scene_step(&s,(pet_scene_input_t){.now_ms=t,.random=1,.night=true,.replica=true});
 assert(s.activity==PET_HOME_IDLE); /* Authority owns autonomous roaming/rest. */
 unsigned before=pet_home_completion();pet_scene_init(&s,0);s.activity=PET_HOME_WASHING;s.place=PET_PLACE_WASH;
 for(uint32_t t=50;t<7000;t+=50)pet_scene_step(&s,(pet_scene_input_t){.now_ms=t,.replica=true});
 assert(pet_home_completion()==before); /* Prediction cannot claim life completion. */
 pet_scene_t master,predicted;pet_scene_init(&master,0);pet_scene_command(&master,PET_HOME_REST,0);
 for(uint32_t t=50;t<=1000;t+=50)pet_scene_step(&master,(pet_scene_input_t){.now_ms=t});
 pet_scene_export(&master,w);assert(pet_scene_import(&predicted,w,PET_SCENE_WIRE_WORDS,1100,1000));
 for(uint32_t t=1050;t<=1600;t+=50)pet_scene_step(&master,(pet_scene_input_t){.now_ms=t});
 pet_scene_predict(&predicted,(pet_scene_input_t){.now_ms=1700,.replica=true,.phase_valid=true,.phase_ms=1600});
 assert(abs(master.x-predicted.x)<=1&&abs(master.y-predicted.y)<=1);assert(master.pose==predicted.pose);
 return 0;
}
''',['pet_scene','pet_home','pet_scene_wire'])
