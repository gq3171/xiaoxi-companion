"""Exercise motion, state priorities and bounded Flash asset decoding."""
import hashlib
import json
from pathlib import Path
import re
import unittest
import zlib
import test_runtime_core

ROOT = Path(__file__).resolve().parents[1]

class SceneHostTests(unittest.TestCase):
    def test_sleeping_head_stays_on_pillow_during_lie_down_and_initial_wake(self):
        test_runtime_core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include "pet_scene.h"
int main(void){
 pet_scene_t s;pet_scene_init(&s,10000);s.x=122;s.y=240;s.place=PET_PLACE_BED;s.stage_started=10000;
 const int states[]={PET_HOME_GETTING_IN_BED,PET_HOME_SLEEPING,PET_HOME_WAKING};
 const unsigned ages[]={1600,0,100};
 for(unsigned i=0;i<3;i++){
  s.activity=states[i];s.last_step=10000+ages[i];int left,top,scale;
  pet_scene_projection(&s,&left,&top,&scale);
  int head_x=left+64*scale/256,head_y=top+88*scale/256;
  /* Pillow area is measured on the actual room background, not derived from
   * the projection formula: the old cel landed left/below this rectangle. */
  assert(head_x>=118&&head_x<=144&&head_y>=164&&head_y<=183);
  assert(top+136*scale/256<=PET_BED_COVER_Y); /* Chin landmark above the duvet. */
 }
 return 0;
}
''',["pet_scene", "pet_home"])

    def test_cat_gait_renders_intermediate_steps_between_battery_snapshots(self):
        test_runtime_core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include "pet_home_sync.h"
int main(void){
 pet_home_world_t base={.cat_mode=8,.cat_phase_ms=0,.cat_walk_rate=1000,.cat_frame=PET_ART_CAT_WALK_A};
 const int frames[]={PET_ART_CAT_WALK_A,PET_ART_CAT_WALK_B,PET_ART_CAT_WALK_C,PET_ART_CAT_WALK_D};
 for(unsigned i=0;i<4;i++){pet_home_world_t w=base;pet_home_cat_motion(&w,i*240);assert(w.cat_frame==frames[i]);}
 pet_home_world_t w=base;pet_home_cat_motion(&w,9000);assert(w.cat_phase_ms==750);
 w=base;w.cat_walk_rate=0;pet_home_cat_motion(&w,600);assert(w.cat_phase_ms==0&&w.cat_frame==frames[0]);
 w=base;w.cat_walk_rate=0;w.cat_frame=PET_ART_CAT_STAND;pet_home_cat_motion(&w,600);assert(w.cat_frame==PET_ART_CAT_STAND);
 w=base;w.cat_mode=11;w.cat_frame=PET_ART_CAT_TURN;pet_home_cat_motion(&w,600);assert(w.cat_frame==PET_ART_CAT_TURN);
 w=base;w.cat_walk_rate=-1;w.cat_frame=PET_ART_CAT_WALK_D;pet_home_cat_motion(&w,600);assert(w.cat_frame==PET_ART_CAT_WALK_D);
 w=base;w.cat_mode=3;w.cat_frame=PET_ART_CAT_SLEEP;pet_home_cat_motion(&w,600);assert(w.cat_frame==PET_ART_CAT_SLEEP);
 return 0;
}
''',[])

    def test_front_and_side_share_one_paused_four_phase_cycle_and_wire_clock(self):
        test_runtime_core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include <stdlib.h>
#include "pet_scene_wire.h"
int main(void){
 pet_scene_t s;pet_scene_init(&s,17000);s.x=s.precise_x=240;s.y=s.precise_y=340;s.activity=PET_HOME_WALKING;s.pose=PET_POSE_WALK_A;s.route_length=1;s.route_x[0]=240;s.route_y[0]=420;s.transition_x=240;s.transition_y=340;s.stage_started=s.last_step=17000;
 const unsigned front[]={PET_POSE_WALK_A,PET_ART_FRONT_PASS_A,PET_POSE_WALK_B,PET_ART_FRONT_PASS_B};
 for(unsigned i=0;i<8;i++)assert(pet_scene_art_frame(&s,17000+i*180)==front[i%4]);
 /* The profile uses the same phase at the same trip age, regardless of wall clock. */
 s.route_x[0]=400;s.route_y[0]=340;
 for(unsigned i=0;i<8;i++)assert(pet_scene_art_frame(&s,17000+i*180)==PET_ART_SIDE_RIGHT_0+i%4);
 s.route_x[0]=240;s.route_y[0]=420;
 for(unsigned t=17020;t<=17360;t+=20)pet_scene_step(&s,(pet_scene_input_t){.now_ms=t});
 int x=s.x,y=s.y;unsigned phase=pet_scene_art_frame(&s,17360);
 for(unsigned t=17380;t<=18360;t+=20){pet_scene_step(&s,(pet_scene_input_t){.now_ms=t,.listening=true});assert(s.x==x&&s.y==y);assert(pet_scene_art_frame(&s,t)==PET_POSE_LISTEN);}
 pet_scene_step(&s,(pet_scene_input_t){.now_ms=18380});assert(pet_scene_art_frame(&s,18380)==phase);
 unsigned paused=pet_scene_art_frame(&s,18380);
 for(unsigned t=18400;t<=19380;t+=20){pet_scene_step(&s,(pet_scene_input_t){.now_ms=t,.blocked=true});assert(pet_scene_art_frame(&s,t)==paused);}
 int32_t wire[PET_SCENE_WIRE_WORDS];pet_scene_export(&s,wire);pet_scene_t replica;
 assert(PET_SCENE_WIRE_WORDS==34&&PET_POSE_COUNT==18);
 assert(pet_scene_import(&replica,wire,34,40380,19380));
 assert(pet_scene_art_frame(&replica,40380)==pet_scene_art_frame(&s,19380));
 return 0;
}
''',['pet_scene','pet_home','pet_scene_wire'])

    def test_side_cycle_and_multistage_wake_preserve_core_pose_protocol(self):
        test_runtime_core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include "pet_scene.h"
int main(void){
 assert(PET_POSE_COUNT==18&&PET_ART_COUNT==52);
 pet_scene_t s;pet_scene_init(&s,0);s.activity=PET_HOME_WALKING;s.pose=PET_POSE_WALK_A;s.route_length=1;s.route_index=0;s.transition_x=300;s.transition_y=350;s.route_x[0]=150;s.route_y[0]=350;
 for(unsigned i=0;i<4;i++)assert(pet_scene_art_frame(&s,i*180)==PET_ART_SIDE_LEFT_0+i);
 s.x=151;assert(pet_scene_art_frame(&s,720)==PET_ART_SIDE_LEFT_0);
 s.transition_x=150;s.route_x[0]=320;assert(pet_scene_art_frame(&s,180)==PET_ART_SIDE_RIGHT_1);
 s.activity=PET_HOME_GETTING_IN_BED;assert(pet_scene_art_frame(&s,1000)==PET_ART_BED_SIT);assert(pet_scene_art_frame(&s,1600)==PET_POSE_LIE_SLEEP);
 s.activity=PET_HOME_WAKING;assert(pet_scene_art_frame(&s,100)==PET_POSE_LIE_SLEEP);assert(pet_scene_art_frame(&s,600)==PET_ART_BED_SIT);assert(pet_scene_art_frame(&s,1500)==PET_ART_BED_STRETCH);assert(pet_scene_art_frame(&s,2500)==PET_ART_STAND_STRETCH);assert(pet_scene_art_frame(&s,3200)==PET_ART_STAND_RELAX);
 return 0;
}
''',['pet_scene','pet_home'])

    def test_walk_facing_does_not_flash_front_at_waypoints_or_near_horizontal_arrival(self):
        test_runtime_core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include "pet_scene.h"
static bool back(pet_scene_t*s){return s->pose==PET_POSE_WALK_BACK_A||s->pose==PET_POSE_WALK_BACK_B;}
int main(void){
 for(unsigned interval=20;interval<=100;interval+=20){
  pet_scene_t s;pet_scene_init(&s,0);pet_scene_command(&s,PET_HOME_REST,0);
  unsigned t=0,waypoints=0;int previous=0;
  while(s.activity==PET_HOME_WALKING&&t<60000){
   t+=interval;pet_scene_step(&s,(pet_scene_input_t){.now_ms=t});
   assert(back(&s));
   if(s.route_index!=previous){waypoints++;previous=s.route_index;}
  }
  assert(s.activity==PET_HOME_GETTING_IN_BED&&waypoints==3);
 }
 /* On a shallow diagonal, dy shrinks below .5 while several pixels remain;
  * on a horizontal leg, keep the established heading. */
 pet_scene_t s;pet_scene_init(&s,0);
 s.activity=PET_HOME_WALKING;s.walk_backwards=true;s.route_length=2;
 s.x=s.precise_x=300;s.y=s.precise_y=330;
 s.route_x[0]=230;s.route_y[0]=325;s.route_x[1]=180;s.route_y[1]=325;
 s.destination=PET_PLACE_FLOOR;
 for(unsigned t=20;t<15000&&s.activity==PET_HOME_WALKING;t+=20){
  pet_scene_step(&s,(pet_scene_input_t){.now_ms=t});assert(back(&s));
 }
 assert(s.activity==PET_HOME_IDLE);
 return 0;
}
''',['pet_scene','pet_home'])

    def test_seated_pose_only_at_chair_even_when_speech_pauses_arrival_or_departure(self):
        test_runtime_core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include "pet_scene.h"
static unsigned now;
static void step(pet_scene_t*s,bool live){now+=100;pet_scene_step(s,(pet_scene_input_t){.now_ms=now,.speaking=live});}
static bool seated(pet_scene_t*s){return s->pose==PET_POSE_WORK_A||s->pose==PET_POSE_WORK_B;}
int main(void){
 pet_scene_t s;pet_scene_init(&s,0);pet_scene_command(&s,PET_HOME_WORK,0);
 for(int i=0;i<1000&&s.activity!=PET_HOME_SITTING;i++){step(&s,false);assert(!seated(&s));}
 assert(s.activity==PET_HOME_SITTING);
 step(&s,false);assert(!seated(&s));int x=s.x,y=s.y;
 for(int i=0;i<20;i++){step(&s,true);assert(!seated(&s)&&s.x==x&&s.y==y);}
 for(int i=0;i<100&&s.activity==PET_HOME_SITTING;i++){
  step(&s,false);
  if(seated(&s))assert(s.x==pet_home_spots[PET_PLACE_WORK].use_x&&s.y==pet_home_spots[PET_PLACE_WORK].use_y);
 }
 assert(s.activity==PET_HOME_WAIT_COMPUTER&&seated(&s));
 step(&s,true);assert(seated(&s));
 pet_scene_command(&s,PET_HOME_ROAM,now);assert(s.activity==PET_HOME_STANDING);
 for(int i=0;i<20;i++){step(&s,true);assert(!seated(&s));}
 for(int i=0;i<100&&s.activity==PET_HOME_STANDING;i++){step(&s,false);assert(!seated(&s));}
 assert(s.activity==PET_HOME_WALKING&&s.place==PET_PLACE_FLOOR);
 return 0;
}
''',['pet_scene','pet_home'])

    def test_faster_ui_cadence_preserves_real_time_walking_speed(self):
        test_runtime_core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include <stdlib.h>
#include "pet_scene.h"
int main(void){
 pet_scene_t slow,fast;pet_scene_init(&slow,0);pet_scene_init(&fast,0);
 pet_scene_command(&slow,PET_HOME_REST,0);pet_scene_command(&fast,PET_HOME_REST,0);
 for(unsigned t=100;t<=1000;t+=100)pet_scene_step(&slow,(pet_scene_input_t){.now_ms=t,.clock_valid=true});
 for(unsigned t=20;t<=1000;t+=20)pet_scene_step(&fast,(pet_scene_input_t){.now_ms=t,.clock_valid=true});
 assert(slow.activity==PET_HOME_WALKING&&fast.activity==PET_HOME_WALKING);
 assert(abs(slow.x-fast.x)<=1&&abs(slow.y-fast.y)<=1);
 return 0;
}
''',['pet_scene','pet_home'])

    def test_native_room_scaling_keeps_colors_edges_and_buffer_bounds(self):
        test_runtime_core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include <stdlib.h>
#include "pet_asset_codec.h"
int main(void){
 uint16_t *src=calloc(320*320,sizeof(*src)),*allocation=malloc((480*480+2)*sizeof(*src));
 uint16_t *dst=allocation+1;allocation[0]=0x1234;allocation[480*480+1]=0x5678;
 assert(!pet_asset_expand_room(NULL,dst)&&!pet_asset_expand_room(src,src));
 for(int i=0;i<320*320;i++)src[i]=0xffff;
 assert(pet_asset_expand_room(src,dst));for(int i=0;i<480*480;i++)assert(dst[i]==0xffff);
 for(int i=0;i<320*320;i++)src[i]=0;
 src[0]=0xf800;src[319*320+319]=0x001f;
 assert(pet_asset_expand_room(src,dst));assert(dst[0]==0xf800&&dst[1]==0x5000&&dst[2]==0);
 assert(dst[479*480+479]==0x001f);
 assert(allocation[0]==0x1234&&allocation[480*480+1]==0x5678);
 free(src);free(allocation);return 0;
}
''',['pet_asset_codec'],compiler_flags=['-lz'])

    def test_live_speech_priority_drag_limits_modal_pause_night_and_rollover(self):
        code=r'''
#include <assert.h>
#include <string.h>
#include "pet_scene.h"
static uint32_t now;
static void step(pet_scene_t*s,bool night,bool live){now+=100;pet_scene_step(s,(pet_scene_input_t){.now_ms=now,.random=now*7919,.night=night,.clock_valid=true,.listening=live});}
static void until(pet_scene_t*s,pet_home_activity_t goal,bool night){
 for(int i=0;i<1000&&s->activity!=goal;i++){
  step(s,night,false);
  if(s->activity==PET_HOME_WALKING)assert(pet_home_floor_contains(s->x,s->y));
 }
 assert(s->activity==goal);
}
int main(void){
 pet_scene_t s;pet_scene_init(&s,0);int a,b,near,far;
 pet_scene_projection(&s,&a,&b,&near);assert(a>=0&&b>=0&&a+208*near/256<=480);
 pet_scene_command(&s,PET_HOME_REST,now);until(&s,PET_HOME_SLEEPING,false);
 assert(s.place==PET_PLACE_BED&&s.pose==PET_POSE_LIE_SLEEP);
 for(int i=0;i<30;i++)step(&s,false,true);
 assert(s.activity==PET_HOME_SLEEPING&&s.place==PET_PLACE_BED&&s.pose==PET_POSE_LIE_SLEEP);
 pet_scene_command(&s,PET_HOME_WAKE,now);until(&s,PET_HOME_WASHING,false);
 step(&s,false,false);assert(s.pose==PET_POSE_WASH_A);
 int x=s.x,y=s.y;uint32_t started=s.stage_started;
 for(int i=0;i<40;i++)step(&s,false,true);
 assert(s.x==x&&s.y==y&&now-s.stage_started==100&&s.stage_started>started);
 until(&s,PET_HOME_IDLE,false);
 pet_scene_command(&s,PET_HOME_WORK,now);until(&s,PET_HOME_WAIT_COMPUTER,false);step(&s,false,false);
 assert(s.pose==PET_POSE_WORK_A&&pet_home_computer_state()==PET_COMPUTER_DISCONNECTED);
 char desc[2000];pet_home_description(desc,sizeof(desc));assert(strstr(desc,"未连接")&&strstr(desc,"等电脑连接"));
 pet_home_computer_event(PET_COMPUTER_RUNNING);step(&s,false,false);assert(s.activity==PET_HOME_WORKING);
 pet_home_computer_event(PET_COMPUTER_DISCONNECTED);step(&s,false,true);assert(s.activity==PET_HOME_WAIT_COMPUTER);
 pet_scene_command(&s,PET_HOME_ROAM,now);until(&s,PET_HOME_IDLE,false);
 pet_scene_press(&s,240,180,now);pet_scene_drag(&s,9999,9999);assert(pet_home_floor_contains(s.x,s.y));
 pet_scene_projection(&s,&a,&b,&near);assert(!pet_scene_release(&s,now));
 assert(a>=12&&a+208*near/256<=468);
 pet_scene_press(&s,240,180,now);pet_scene_drag(&s,-9999,-9999);assert(pet_home_floor_contains(s.x,s.y));
 pet_scene_projection(&s,&a,&b,&far);assert(near>far);pet_scene_release(&s,now);
 pet_scene_command(&s,PET_HOME_REST,now);x=s.x;y=s.y;
 for(int i=0;i<80;i++){now+=100;pet_scene_step(&s,(pet_scene_input_t){.now_ms=now,.blocked=true});}
 assert(s.x==x&&s.y==y);until(&s,PET_HOME_SLEEPING,true);
 step(&s,false,false);assert(s.activity==PET_HOME_WAKING);until(&s,PET_HOME_WASHING,false);
 pet_scene_init(&s,UINT32_MAX-1000);now=UINT32_MAX-1000;
 for(int i=0;i<5000;i++){step(&s,false,false);assert(s.pose<PET_POSE_COUNT);if(s.activity==PET_HOME_WALKING)assert(pet_home_floor_contains(s.x,s.y));}
 assert(!pet_home_request_text("run_shell")&&!pet_home_request_text(""));assert(pet_home_request_text("work"));
 assert(pet_home_take_request()==PET_HOME_WORK&&pet_home_take_request()==PET_HOME_NONE);
 return 0;
}
'''
        test_runtime_core.RuntimeCoreTests.run_c(self,code,['pet_scene','pet_home'])

    def test_asset_decoder_checks_checksum_exact_size_and_bounds(self):
        code=r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "pet_asset_codec.h"
static unsigned char input[]={120,218,237,207,83,150,16,0,0,0,192,205,182,185,217,182,109,219,182,109,215,102,219,182,109,219,182,109,91,95,221,163,55,115,131,9,8,22,60,68,200,80,161,195,132,13,23,62,66,196,72,145,163,68,141,22,61,70,204,88,177,227,196,141,23,63,65,194,68,137,3,147,36,77,150,60,69,202,84,169,211,164,77,151,62,67,198,76,153,179,100,205,150,61,71,206,92,185,243,228,205,151,191,64,193,66,133,139,20,45,86,188,68,201,82,165,203,148,45,87,190,66,197,74,149,171,84,173,86,189,70,205,90,181,235,212,173,87,191,65,195,70,141,155,52,109,214,188,69,203,86,173,219,180,109,215,190,67,199,78,157,187,116,237,214,189,71,207,94,189,251,244,237,215,127,192,192,65,131,135,12,29,22,52,124,196,200,81,163,199,140,29,55,126,194,196,73,147,167,76,157,54,125,198,204,89,179,231,204,157,55,127,193,194,69,139,151,44,93,182,124,197,202,85,171,215,172,93,183,126,195,198,77,155,183,108,221,182,125,199,206,93,187,247,236,221,183,255,192,193,67,135,143,28,61,118,252,196,201,83,167,207,156,61,119,254,194,197,75,151,175,92,189,118,253,198,205,91,183,239,220,189,119,255,193,195,71,143,159,60,125,246,252,197,203,87,175,223,188,125,247,254,195,199,79,159,191,124,253,246,253,199,207,95,191,255,252,13,80,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,87,255,31,235,255,0,157,133,79,182};
int main(void){
 unsigned char *p=malloc(50002);memset(p,0xa5,50002);
 assert(pet_asset_inflate(input,sizeof(input),p+1,50000));
 for(int i=0;i<50000;i++)assert(p[i+1]==i%251);
 assert(p[0]==0xa5&&p[50001]==0xa5);
 assert(!pet_asset_inflate(input,sizeof(input)-1,p+1,50000));
 input[sizeof(input)-1]^=1;assert(!pet_asset_inflate(input,sizeof(input),p+1,50000));input[sizeof(input)-1]^=1;
 assert(!pet_asset_inflate(input,sizeof(input),p+1,49999));
 assert(!pet_asset_inflate(NULL,sizeof(input),p+1,50000));
 assert(!pet_asset_inflate(input,sizeof(input),p+1,300000));
 assert(p[0]==0xa5&&p[50001]==0xa5);free(p);return 0;
}
'''
        test_runtime_core.RuntimeCoreTests.run_c(self,code,['pet_asset_codec'],compiler_flags=['-lz'])

    def test_generated_assets_hash_alpha_format_and_storage_budget(self):
        manifest=json.loads((ROOT/'assets/character/manifest.json').read_text())
        code=(ROOT/'main/character/pet_character_assets.c').read_text()
        arrays={name:bytes(int(n,16) for n in re.findall(r'0x([0-9a-f]{2})',body))
                for name,body in re.findall(r'static const uint8_t (\w+)\[\d+\] = \{(.*?)\};',code,re.S)}
        self.assertEqual(len(manifest['frames']),52)
        self.assertEqual(len(zlib.decompress(arrays['yard_pixels'])),320*320*2)
        self.assertLessEqual(manifest['total_bytes']+4096+4*len(manifest['frames']),0xc0000)
        self.assertEqual(len(zlib.decompress(arrays['room_pixels'])),320*320*2)
        self.assertEqual(hashlib.sha256(zlib.decompress(arrays['room_pixels'])).hexdigest(),manifest['room_sha256'])
        cat_scales={f['pixel_scale'] for f in manifest['frames'] if f['name'].startswith('cat_')};self.assertEqual(len(cat_scales),1)
        for frame in manifest['frames']:
            name=frame.get('alias',frame['name']);palette=arrays[name+'_palette'];pixels=zlib.decompress(arrays[name+'_pixels'])
            self.assertEqual(len(pixels),208*264)
            self.assertEqual(hashlib.sha256(palette+pixels).hexdigest(),frame['packed_sha256'])
            alpha=bytes(palette[i*4+3] for i in pixels)
            self.assertTrue(any(a>240 for a in alpha))
            if frame['name'].startswith('cat_'):
                self.assertFalse(any(alpha[y*208+x]>=32 for y in range(264) for x in range(208) if not (24<=x<184 and 116<=y<260)))
            self.assertTrue(all(a==0 for a in alpha[:208]+alpha[-208:]))
            self.assertTrue(all(alpha[y*208]==0 and alpha[y*208+207]==0 for y in range(264)))

    def test_optional_source_provenance_requires_an_explicit_source_directory(self):
        import os
        directory=os.environ.get('DESKPET_ART_SOURCE_DIR')
        if not directory:return # Public packed assets above are always checked.
        manifest=json.loads((ROOT/'assets/character/manifest.json').read_text())
        for frame in manifest['frames']:
            path=Path(directory)/Path(frame['source_path']).name
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),frame['source_sha256'])
