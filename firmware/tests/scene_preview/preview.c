
#include <assert.h>
#include "pet_face.c"
#include "pet_orientation.h"
static const char *output_dir=".";
static uint32_t fake_ms;
static bool listening,playing;
static pet_hardware_state_t hardware={.battery_percent=100,.usb_power=true,.clock_valid=true};
static pet_network_state_t network={.connected=true,.rssi=-52};
pet_network_state_t pet_setup_network_state(void){return network;}
static int local_minute=720;
static uint16_t framebuffer[480*480];
int64_t esp_timer_get_time(void){return (int64_t)fake_ms*1000;}
uint32_t esp_random(void){return 1234567;}
int esp_lv_adapter_lock(int32_t t){return 0;}
void esp_lv_adapter_unlock(void){}
void bsp_display_unlock(void){}
static int actual_brightness=75;
int bsp_display_brightness_set(int n){actual_brightness=n;return 0;}
void *xSemaphoreCreateBinary(void){return (void*)1;}
int xSemaphoreTake(void*p,uint32_t t){return 1;}
int xSemaphoreGive(void*p){return 1;}
bool pet_audio_playing(void){return playing;}
bool pet_wake_ready(void){return true;}
void pet_wake_phrase(char*out,size_t n){snprintf(out,n,"小西小西");}
bool pet_audio_output_allowed(void){return true;}
void pet_audio_stop(void){playing=false;}
bool pet_capture_listening(void){return listening;}
bool pet_capture_pending(void){return false;}
int pet_capture_recorded_ms(void){return 0;}
pet_hardware_state_t pet_hardware_state(void){return hardware;}
int pet_hardware_local_minute(void){return local_minute;}
void pet_runtime_notify(const char*text){}
void pet_runtime_quiet(int m){}
void pet_runtime_voice_override(int m){}
void pet_setup_cancel(void){}
void pet_setup_keyboard(void){}
static void flush(lv_display_t *d,const lv_area_t *a,uint8_t *pixels){
 uint16_t *p=(uint16_t*)pixels;
 for(int y=a->y1;y<=a->y2;y++)for(int x=a->x1;x<=a->x2;x++)framebuffer[y*480+x]=*p++;
 lv_display_flush_ready(d);
}
void pet_display_start(void){
 lv_init();lv_display_t*d=lv_display_create(480,480);
 lv_display_set_color_format(d,LV_COLOR_FORMAT_RGB565);
 lv_display_set_flush_cb(d,flush);
 lv_display_set_buffers(d,malloc(480*480*2),NULL,480*480*2,LV_DISPLAY_RENDER_MODE_FULL);
}
pet_display_profile_t pet_display_profile(void){return (pet_display_profile_t){0};}
unsigned pet_display_rotation(void){return 0;}
static void save(const char *name){
 fake_ms+=100;lv_tick_inc(100);lv_timer_handler();lv_refr_now(NULL);
 char path[256];snprintf(path,sizeof(path),"%s/%s.rgb565",output_dir,name);
 FILE*f=fopen(path,"wb");assert(f);fwrite(framebuffer,2,480*480,f);fclose(f);
}
static lv_point_t test_point;
static bool test_pressed;
static void pointer_read(lv_indev_t *input,lv_indev_data_t *data){
 data->point=test_point;data->state=test_pressed?LV_INDEV_STATE_PRESSED:LV_INDEV_STATE_RELEASED;
}
static void pointer_event(lv_indev_t *input,int x,int y,bool down){
 test_point=(lv_point_t){x,y};test_pressed=down;fake_ms+=30;lv_tick_inc(30);lv_indev_read(input);
}
static void touch_regression(void){
 lv_indev_t *input=lv_indev_create();lv_indev_set_type(input,LV_INDEV_TYPE_POINTER);lv_indev_set_read_cb(input,pointer_read);
 lv_obj_update_layout(lv_screen_active());
 /* These two furniture points were intercepted by transparent sprite pixels. */
 const lv_point_t furniture[]={{170,225},{330,180}};
 const pet_home_action_t actions[]={PET_HOME_REST,PET_HOME_WORK};
 const pet_place_t targets[]={PET_PLACE_BED,PET_PLACE_WORK};
 for(int k=0;k<2;k++){
  lv_point_t pt=furniture[k];assert(lv_indev_search_obj(lv_screen_active(),&pt)!=s_body);
  pointer_event(input,pt.x,pt.y,true);assert(!s_scene.pressed);
  pointer_event(input,pt.x,pt.y,false);assert(pet_home_take_request()==actions[k]);
  /* A real pointer click must be consumed and reach the destination. */
  pointer_event(input,pt.x,pt.y,true);pointer_event(input,pt.x,pt.y,false);
  fake_ms+=33;lv_tick_inc(33);animate(lv_timer_get_next(NULL));
  assert(s_scene.activity==PET_HOME_WALKING&&s_scene.destination==targets[k]);
  for(int j=0;j<1000&&s_scene.activity==PET_HOME_WALKING;j++){
   fake_ms+=100;pet_scene_step(&s_scene,(pet_scene_input_t){.now_ms=fake_ms});
  }
  assert(s_scene.place==targets[k]);
  pet_scene_init(&s_scene,fake_ms);fake_ms+=33;lv_tick_inc(33);animate(lv_timer_get_next(NULL));
 }
 /* Test visible vs transparent pixels with actual LVGL picking at every
  * supported depth and both tilt directions. */
 const int scales[]={144,239,268},angles[]={-100,0,100};
 lv_obj_t *bubble=lv_obj_get_parent(s_caption);lv_obj_set_hidden(bubble,true);
 draw_character(PET_POSE_IDLE);
 for(unsigned a=0;a<3;a++)for(unsigned b=0;b<3;b++){
  lv_obj_set_pos(s_body,135,135);lv_image_set_scale(s_body,scales[a]);lv_image_set_rotation(s_body,angles[b]);lv_obj_update_layout(s_body);
  float rad=angles[b]*.001745329252f;
  /* Central chest is opaque; corner beside the bun is transparent. */
  const lv_point_t source[]={{104,166},{200,37}};
  for(int j=0;j<2;j++){
   float x=source[j].x*scales[a]/256.0f,y=source[j].y*scales[a]/256.0f;
   lv_point_t pt={135+(int)lroundf(cosf(rad)*x-sinf(rad)*y),135+(int)lroundf(sinf(rad)*x+cosf(rad)*y)};
   assert((lv_indev_search_obj(lv_screen_active(),&pt)==s_body)==(j==0));
   for(unsigned r=0;r<360;r+=90){
    /* Coordinates arriving from the rotated glass must select that same target. */
    int x0=pt.x,y0=pt.y;pet_orientation_touch((360-r)%360,480,&x0,&y0);pet_orientation_touch(r,480,&x0,&y0);
    assert(x0==pt.x&&y0==pt.y);
   }
  }
 }
 lv_image_set_rotation(s_body,0);lv_image_set_scale(s_body,239);lv_obj_set_pos(s_body,143,145);lv_obj_update_layout(s_body);
 pointer_event(input,240,300,true);assert(s_scene.pressed);
 pointer_event(input,260,320,true);assert(s_scene.dragging);
 pointer_event(input,260,320,false);assert(!s_scene.pressed&&!s_scene.dragging);
 pet_face_toggle_menu();fake_ms+=100;lv_tick_inc(100);animate(lv_timer_get_next(NULL));lv_obj_update_layout(lv_screen_active());lv_point_t pt={240,300};assert(lv_indev_search_obj(lv_screen_active(),&pt)!=s_body);pet_face_toggle_menu();
 /* Open the real message reader and click its actual back button through
  * the same pointer dispatcher, including each glass orientation. */
 for(unsigned r=0;r<360;r+=90){
  show_reader("完整消息");lv_obj_update_layout(lv_screen_active());assert(s_reader);
  lv_obj_t *back=lv_obj_get_child(s_reader,1);lv_area_t a;lv_obj_get_coords(back,&a);
  int x=(a.x1+a.x2)/2,y=(a.y1+a.y2)/2;
  pet_orientation_touch((360-r)%360,480,&x,&y);pet_orientation_touch(r,480,&x,&y);
  pointer_event(input,x,y,true);pointer_event(input,x,y,false);assert(!s_reader);
  fake_ms+=100;lv_tick_inc(100);lv_timer_handler();
 }
 puts("Native pointer regression passed: transparent furniture clicks, real travel, visible touch/drag, depths, tilts, four coordinate mappings menu priority and message return.");
}
static void dropdown_font_regression(void){
 char selected[256]={0};
 pet_face_choose("媒体结果","1. 可爱小鸡\n2. 温馨小屋",selected,sizeof(selected));
 assert(s_form&&s_dropdown);lv_dropdown_open(s_dropdown);lv_obj_update_layout(lv_screen_active());
 lv_obj_t *list=lv_dropdown_get_list(s_dropdown);
 assert(lv_obj_get_style_text_font(s_dropdown,LV_PART_MAIN)==&pet_font_cn_16);
 assert(lv_obj_get_style_text_font(list,LV_PART_MAIN)==&pet_font_cn_16);
 assert(lv_obj_get_style_text_font(list,LV_PART_SELECTED)==&pet_font_cn_16);
 const uint32_t glyphs[]={0x53ef,0x7231,0x5c0f,0x9e21,0x6e29,0x99a8,0x5c4b};
 lv_font_glyph_dsc_t glyph;
 for(unsigned i=0;i<sizeof(glyphs)/sizeof(glyphs[0]);i++){
  assert(lv_font_get_glyph_dsc(lv_obj_get_style_text_font(list,LV_PART_SELECTED),&glyph,glyphs[i],0)&&!glyph.is_placeholder);
 }
 save("media_choice_open");lv_dropdown_set_selected(s_dropdown,1);save("media_choice_second");
 lv_dropdown_close(s_dropdown);
 lv_obj_t *finished=s_form;lv_obj_delete(finished);s_form=s_dropdown=s_field=NULL;
 puts("Real media-choice popup and selected-row CJK font/glyph regression passed.");
}
static void life_world_preview(void){
 /* Stop autonomous timers so captures inspect the real renderer at exact stages. */
 for(lv_timer_t*t=lv_timer_get_next(NULL);t;t=lv_timer_get_next(t))lv_timer_pause(t);
 pet_home_world_t world={.valid=true,.online=true,.cat_x=320,.cat_y=360,.cat_frame=PET_ART_CAT_IDLE};
 pet_face_set("在这儿","");
 for(int i=0;i<4;i++){
  pet_scene_init(&s_scene,fake_ms);s_scene.x=300;s_scene.y=370;s_scene.precise_x=300;s_scene.precise_y=370;
  pet_scene_walk_to(&s_scene,170,370,fake_ms);fake_ms+=i*180;animate(lv_timer_get_next(NULL));draw_world(&world,fake_ms);
  char name[40];snprintf(name,sizeof(name),"side_%d",i);save(name);
 }
 const unsigned stages[]={PET_HOME_GETTING_IN_BED,PET_HOME_GETTING_IN_BED,PET_HOME_GETTING_IN_BED,PET_HOME_SLEEPING,PET_HOME_WAKING,PET_HOME_WAKING,PET_HOME_WAKING,PET_HOME_WAKING,PET_HOME_WAKING};
 const unsigned ages[]={100,900,1850,0,100,500,1400,2400,3150};
 const char*names[]={"bed_approach","bed_sit","bed_lie_transition","bed_sleep","wake_lie","wake_sit","wake_stretch","wake_stand","wake_relax"};
 for(unsigned i=0;i<9;i++){
  const pet_home_spot_t*bed=&pet_home_spots[PET_PLACE_BED];bool asleep=stages[i]==PET_HOME_SLEEPING;
  pet_scene_init(&s_scene,fake_ms);s_scene.x=s_scene.precise_x=asleep?bed->use_x:bed->approach_x;s_scene.y=s_scene.precise_y=asleep?bed->use_y:bed->approach_y;s_scene.place=PET_PLACE_BED;s_scene.activity=stages[i];s_scene.stage_started=fake_ms-ages[i];s_scene.last_step=fake_ms;
  animate(lv_timer_get_next(NULL));world.cat_frame=PET_ART_CAT_SLEEP;world.cat_x=220;world.cat_y=330;draw_world(&world,fake_ms);save(names[i]);
  if(s_drawn_pose==PET_POSE_LIE_SLEEP)assert(!lv_obj_is_hidden(s_occlusion[PET_PLACE_BED]));
 }
 pet_scene_init(&s_scene,fake_ms);animate(lv_timer_get_next(NULL));world.location=1;world.cat_frame=PET_ART_CAT_IDLE;draw_world(&world,fake_ms);save("yard");
 for(int i=1;i<PET_PLACE_COUNT;i++)assert(lv_obj_is_hidden(s_home_hits[i]));
 world.location=0;draw_world(&world,fake_ms);save("home_cat");for(int i=1;i<PET_PLACE_COUNT;i++)assert(!lv_obj_is_hidden(s_home_hits[i]));
 /* The new four-step gait and two cat steps must stop decoding after warmup. */
 for(int i=0;i<4;i++)draw_character(PET_ART_SIDE_LEFT_0+i);
 uint32_t warm=s_decode_count;
 for(int i=0;i<24;i++)draw_character(PET_ART_SIDE_LEFT_0+i%4);
 assert(s_decode_count==warm);
 const unsigned front_walk[]={PET_POSE_WALK_A,PET_ART_FRONT_PASS_A,PET_POSE_WALK_B,PET_ART_FRONT_PASS_B};
 for(int i=0;i<4;i++)draw_character(front_walk[i]);
 warm=s_decode_count;for(int i=0;i<24;i++)draw_character(front_walk[i%4]);assert(s_decode_count==warm);
 const unsigned cat_walk[]={PET_ART_CAT_WALK_A,PET_ART_CAT_WALK_B,PET_ART_CAT_WALK_C,PET_ART_CAT_WALK_D};
 for(int i=0;i<4;i++){world.cat_frame=cat_walk[i];draw_world(&world,fake_ms);}
 warm=s_decode_count;for(int i=0;i<24;i++){world.cat_frame=cat_walk[i%4];draw_world(&world,fake_ms);}
 assert(s_decode_count==warm);
 lv_obj_set_hidden(s_body,true);
 for(unsigned i=PET_ART_CAT_IDLE;i<=PET_ART_CAT_TURN;i++){
  world.cat_frame=i;world.cat_x=240;world.cat_y=400;world.cat_face=-1;world.cat_mode=i==PET_ART_CAT_SLEEP?3:0;s_cat_known=false;draw_world(&world,fake_ms);
  char name[40];snprintf(name,sizeof(name),"cat_art_%u",i);save(name);
 }
 /* Turning uses a front standing drawing, never a reflected side sprite. */
 world.cat_frame=PET_ART_CAT_TURN;world.cat_mode=11;world.cat_face=-1;draw_world(&world,fake_ms);
 uint32_t turn_crc=pet_crc32(s_cat_pixels,CAT_WIDTH*CAT_HEIGHT*3);save("cat_turn");
 world.cat_face=1;draw_world(&world,fake_ms);assert(pet_crc32(s_cat_pixels,CAT_WIDTH*CAT_HEIGHT*3)==turn_crc);
 world.cat_frame=PET_ART_CAT_STAND;world.cat_mode=10;draw_world(&world,fake_ms);save("cat_standing");
 world.cat_frame=PET_ART_CAT_IDLE;draw_world(&world,fake_ms);lv_obj_update_layout(lv_screen_active());
 assert(s_cat_image.header.w==160&&s_cat_image.header.h==144);
 lv_area_t a;lv_obj_get_coords(s_cat,&a);int opaque=-1;
 for(int y=3;y<CAT_HEIGHT-3&&opaque<0;y++)for(int x=3;x<CAT_WIDTH-3;x++){
  bool solid=true;for(int dy=-2;dy<=2;dy++)for(int dx=-2;dx<=2;dx++)if(s_cat_pixels[CAT_WIDTH*CAT_HEIGHT*2+(y+dy)*CAT_WIDTH+x+dx]<240)solid=false;
  if(solid){opaque=y*CAT_WIDTH+x;break;}
 }
 assert(opaque>=0);lv_point_t visible={a.x1+(opaque%CAT_WIDTH)*s_cat_scale/256,a.y1+(opaque/CAT_WIDTH)*s_cat_scale/256};
 assert(lv_indev_search_obj(lv_screen_active(),&visible)==s_cat);
 lv_point_t blank={a.x1,a.y1};assert(lv_indev_search_obj(lv_screen_active(),&blank)!=s_cat);
 puts("Life-world renderer: side cycle, bed occlusion, four wake stages, cat and reversible map hit targets passed.");
}
int main(int argc,char **argv){
 if(argc>1)output_dir=argv[1];
#ifdef CONFIG_DESKPET_PANEL_CACHE
 bool recovery=argc>3&&!strcmp(argv[2],"--fallback-recovery");
 if(recovery)unsetenv("PET_PANEL_TEST_ROOT");
#endif
 lv_font_glyph_dsc_t glyph;
 const uint32_t symbols[]={0x00b7,0x2013,0x2014,0x2018,0x2019,0x201c,0x201d,0x2026,0x00b0,0x00d7,0x00f7,0x2192,0x221a,0x2264,0x2265};
 for(unsigned i=0;i<sizeof(symbols)/sizeof(symbols[0]);i++){
  assert(lv_font_get_glyph_dsc(&pet_font_cn_16,&glyph,symbols[i],0) && !glyph.is_placeholder);
  assert(lv_font_get_glyph_dsc(&pet_font_owner_28,&glyph,symbols[i],0) && !glyph.is_placeholder);
 }
 pet_panel_start();pet_face_start();pet_face_set("在这儿","我在这里，慢慢说，我听着呢。");
 if(argc>2&&!strcmp(argv[2],"--life-world")){life_world_preview();return 0;}
#ifdef CONFIG_DESKPET_PANEL_CACHE
 if(recovery){
  assert(pet_panel_frame(PET_POSE_IDLE)->compressed==pet_panel_frame(PET_POSE_WALK_A)->compressed);
  uint32_t missing=0;
  for(uint32_t c=0x4e00;c<0x9fff;c++)if(!lv_font_get_glyph_dsc(&pet_font_cn_16,&glyph,c,0)||glyph.is_placeholder){missing=c;break;}
  assert(missing);save("fallback");pet_face_toggle_menu();save("fallback_menu");pet_face_toggle_menu();
  assert(setenv("PET_PANEL_TEST_ROOT",argv[3],1)==0&&pet_panel_start()==2);pet_face_panel_refresh();
  assert(lv_font_get_glyph_dsc(&pet_font_cn_16,&glyph,missing,0)&&!glyph.is_placeholder);
  assert(pet_panel_frame(PET_POSE_IDLE)->compressed!=pet_panel_frame(PET_POSE_WALK_A)->compressed);
  draw_character(PET_POSE_WALK_A);uint32_t a=pet_crc32(s_sprite_pixels,PET_CHARACTER_WIDTH*PET_CHARACTER_HEIGHT*3);
  draw_character(PET_POSE_WALK_B);assert(a!=pet_crc32(s_sprite_pixels,PET_CHARACTER_WIDTH*PET_CHARACTER_HEIGHT*3));
  save("recovered");touch_regression();dropdown_font_regression();puts("Fallback, live font/art recovery and actual pointer routing passed.");return 0;
 }
#endif
 assert(s_room_scale==256&&s_room_image.header.w==480);
 uint32_t decodes=s_decode_count;draw_character(PET_POSE_WALK_A);uint32_t walk_crc=pet_crc32(s_sprite_pixels,PET_CHARACTER_WIDTH*PET_CHARACTER_HEIGHT*3);
 draw_character(PET_POSE_WALK_B);
 for(int i=0;i<20;i++){draw_character(PET_POSE_WALK_A);draw_character(PET_POSE_WALK_B);}
 assert(s_decode_count-decodes==2);
 draw_character(PET_POSE_IDLE);draw_character(PET_POSE_WALK_A);
 assert(pet_crc32(s_sprite_pixels,PET_CHARACTER_WIDTH*PET_CHARACTER_HEIGHT*3)==walk_crc);
 draw_character(PET_POSE_IDLE);
 for(int i=0;i<10;i++){fake_ms+=100;lv_tick_inc(100);lv_timer_handler();}
 save("idle");
 pet_face_result_pending(true);save("result_pending");assert(!lv_obj_is_hidden(s_result_badge));pet_face_result_pending(false);
 if(argc>2&&!strcmp(argv[2],"--touch-regression")){touch_regression();dropdown_font_regression();return 0;}
 hardware.battery_percent=55;hardware.usb_power=false;refresh_battery(hardware);save("battery_mid");
 hardware.battery_percent=8;refresh_battery(hardware);save("battery_low");
 hardware.battery_percent=-1;refresh_battery(hardware);save("battery_unknown");
 hardware.battery_percent=100;hardware.usb_power=true;refresh_battery(hardware);save("battery_power");
 network=(pet_network_state_t){.connected=true,.rssi=-82};refresh_network();save("wifi_weak");assert(s_network_level==1&&s_network_mode==2);
 network=(pet_network_state_t){.connected=true,.rssi=-67};refresh_network();save("wifi_medium");assert(s_network_level==2);
 network=(pet_network_state_t){.connecting=true,.rssi=-127};refresh_network();save("wifi_connecting");assert(s_network_mode==1&&s_network_level==0);
 network=(pet_network_state_t){.rssi=-127};refresh_network();save("wifi_offline");assert(s_network_mode==0&&s_network_level==0);
 network=(pet_network_state_t){.connected=true,.rssi=-52};refresh_network();
 listening=true;save("listen");assert(s_scene.pose==PET_POSE_LISTEN);
 listening=false;playing=true;save("speak");
 playing=false;pet_face_set("想","让我想一想，怎么帮你更合适。");save("think");
 pet_face_set("在这儿","");pet_scene_press(&s_scene,240,150,fake_ms);pet_scene_drag(&s_scene,-1000,150);save("drag");
 pet_scene_release(&s_scene,fake_ms);local_minute=1380;fake_ms+=50000;save("night");
 assert(s_scene.activity==PET_HOME_WALKING || s_scene.activity==PET_HOME_GETTING_IN_BED || s_scene.activity==PET_HOME_SLEEPING);
 pet_face_toggle_menu();save("menu");assert(s_menu);
 assert(lv_obj_get_child_count(s_menu)==3); /* heading, scrolling content, fixed navigation */
 lv_obj_t *menu_list=lv_obj_get_child(s_menu,1);assert(lv_obj_get_child_count(menu_list)==5);
 lv_obj_send_event(lv_obj_get_child(menu_list,3),LV_EVENT_CLICKED,NULL);
 assert(!strcmp(lv_label_get_text(lv_obj_get_child(s_menu,0)),"网页与网络"));
 assert(lv_obj_get_child_count(lv_obj_get_child(s_menu,1))==2);save("menu_network");
 lv_obj_send_event(lv_obj_get_child(s_menu,2),LV_EVENT_CLICKED,NULL);
 assert(!strcmp(lv_label_get_text(lv_obj_get_child(s_menu,0)),"家里菜单"));
 lv_obj_send_event(lv_obj_get_child(lv_obj_get_child(s_menu,1),0),LV_EVENT_CLICKED,NULL);
 assert(lv_obj_get_child_count(lv_obj_get_child(s_menu,1))==4);
 lv_obj_send_event(lv_obj_get_child(s_menu,2),LV_EVENT_CLICKED,NULL);
 pet_face_toggle_menu();assert(!s_menu);save("menu_closed");
 assert(pet_face_voice_open());save("voices");
 lv_dropdown_open(s_voice_dropdown);save("voice_options");
 lv_dropdown_set_selected(s_voice_dropdown,18);lv_obj_send_event(s_voice_dropdown,LV_EVENT_VALUE_CHANGED,NULL);
 lv_dropdown_close(s_voice_dropdown);
 assert(pet_tts_current()==4);
 lv_obj_send_event(lv_obj_get_child(s_voice_panel,5),LV_EVENT_CLICKED,NULL);
 int vi=-1;uint32_t vg=0;assert(pet_face_voice_wait(&vi,&vg)==PET_VOICE_PREVIEW&&vi==18&&pet_turn_valid(vg));
 lv_obj_send_event(lv_obj_get_child(s_voice_panel,6),LV_EVENT_CLICKED,NULL);
 assert(pet_face_voice_wait(&vi,&vg)==PET_VOICE_SAVE&&vi==18&&pet_turn_valid(vg));
 pet_face_voice_status("试听结束，喜欢的话点保存使用。");save("voice_selected");
 pet_face_toggle_menu();assert(pet_face_voice_wait(&vi,&vg)==PET_VOICE_CLOSE);
 pet_face_voice_close();save("voice_closed");assert(!s_voice_panel&&pet_tts_current()==4);
 pet_face_toggle_menu();assert(s_menu);
 lv_obj_delete(s_menu);s_menu=NULL;local_minute=720;
 pet_face_message("我在这里，慢慢说，我听着呢。");read_message(NULL);save("reader");assert(s_reader);
 assert(s_sprite_pixels && s_drawn_pose<PET_ART_COUNT);
 lv_obj_delete(s_reader);s_reader=NULL;
 pet_face_set("常用符号", "第1/4段·等你开口；3–5秒；“你好”…\n温度25°C，方向→，± × ÷ √ ≤ ≥");save("symbols");
 pet_face_set("在这儿","");local_minute=720;
 pet_scene_init(&s_scene,fake_ms);s_scene.x=s_scene.precise_x=240;s_scene.y=s_scene.precise_y=420;save("near");
 s_scene.y=s_scene.precise_y=292;save("far");
 pet_home_action_t actions[]={PET_HOME_REST,PET_HOME_WAKE,PET_HOME_WORK};
 pet_home_activity_t states[]={PET_HOME_SLEEPING,PET_HOME_WASHING,PET_HOME_WAIT_COMPUTER};
 const char *names[]={"bed","wash","work"};
 for(int j=0;j<3;j++){
  pet_scene_command(&s_scene,actions[j],fake_ms);
  int chair_frame=0;
  for(int i=0;i<1000&&s_scene.activity!=states[j];i++){
   fake_ms+=100;lv_tick_inc(100);lv_timer_handler();
   if(j==2&&s_scene.activity==PET_HOME_SITTING&&chair_frame<5&&fake_ms-s_scene.stage_started>=(unsigned)chair_frame*400){
    char name[32];snprintf(name,sizeof(name),"chair_approach_%d",chair_frame++);save(name);
   }
  }
  assert(s_scene.activity==states[j]);save(names[j]);
  pet_face_set("说",j==0?"我先躺一会儿，等你叫我再起来。":j==2?"我在工作台等着，任务进度会看实际结果。":"洗好脸，再慢慢开始今天。");
  playing=true;save(j==0?"bubble_bed":j==2?"bubble_work":"bubble_wash");playing=false;
  if(j==0){pet_home_description((char[2000]){0},2000);}
 }
 pet_face_set("在这儿","");pet_scene_command(&s_scene,PET_HOME_ROAM,fake_ms);
 for(int i=0;i<3;i++){save(i==0?"chair_depart_0":i==1?"chair_depart_1":"chair_depart_2");}
 pet_wake_require(true);pet_wake_sleep();
 for(int i=0;i<12;i++){fake_ms+=100;lv_tick_inc(100);lv_timer_handler();}
 save("wake_hint");assert(strstr(lv_label_get_text(s_status),"小西小西"));
 pet_wake_open(fake_ms);
 for(int i=0;i<12;i++){fake_ms+=100;lv_tick_inc(100);lv_timer_handler();}
 save("awake");assert(strstr(lv_label_get_text(s_status),"可以说话"));
 pet_wake_heard(fake_ms);
 for(int i=0;i<12;i++){fake_ms+=100;lv_tick_inc(100);lv_timer_handler();}
 save("wake_reply");assert(!strcmp(lv_label_get_text(s_phase),"我在，听你说"));
 /* Real timer and touch shield, without waiting five wall-clock minutes. */
 pet_wake_sleep();pet_face_set("在这儿","");playing=listening=false;
 s_screen.last_activity=fake_ms-300001;
 animate(lv_timer_get_next(NULL));
 assert(actual_brightness==0&&!lv_obj_is_hidden(s_screen_shield));
 unsigned completed=pet_home_completion();
 lv_obj_send_event(s_screen_shield,LV_EVENT_PRESSED,NULL);
 animate(lv_timer_get_next(NULL));
 assert(actual_brightness==75&&s_screen_touch&&pet_home_completion()==completed);
 lv_obj_send_event(s_screen_shield,LV_EVENT_RELEASED,NULL);
 assert(!s_screen_touch&&lv_obj_is_hidden(s_screen_shield));
 s_screen.last_activity=fake_ms-300001;animate(lv_timer_get_next(NULL));assert(actual_brightness==0);
 pet_wake_heard(fake_ms);animate(lv_timer_get_next(NULL));assert(actual_brightness==75);
 save("screen_awake");
 /* Bubble follows both sides, fits the glass safe area, and opens the actual
  * unabridged caption when its three-line viewport has overflowed. */
 pet_wake_sleep();playing=true;s_scene.activity=PET_HOME_IDLE;s_scene.place=PET_PLACE_FLOOR;
 pet_face_set("说","我想先到窗边看看，再回来陪你聊一会儿。");
 s_scene.x=s_scene.precise_x=120;s_scene.y=s_scene.precise_y=420;position_caption();
 lv_obj_t *bubble=lv_obj_get_parent(s_caption);lv_obj_update_layout(bubble);
 assert(lv_obj_get_x(bubble)>=24&&lv_obj_get_y(bubble)>=82);
 assert(lv_obj_get_y(bubble)+lv_obj_get_height(bubble)<=320);save("bubble_left_character");
 s_scene.x=s_scene.precise_x=360;position_caption();save("bubble_right_character");
 assert(lv_obj_get_x(bubble)+lv_obj_get_width(bubble)<s_scene.x);
 const char *long_reply="我想先去窗边看看外面的光，再回来整理一下自己的小想法。我们刚才说过的事情，我会分清哪些已经做到，哪些还只是计划。等你有空，我们再慢慢聊，不用着急。";
 pet_face_set("说",long_reply);save("bubble_long");
 s_scene.x=s_scene.precise_x=240;s_scene.y=s_scene.precise_y=292;
 position_caption();save("bubble_far_center");
 int bl,bt,bs;pet_scene_projection(&s_scene,&bl,&bt,&bs);
 assert(lv_obj_get_y(bubble)+lv_obj_get_height(bubble)<=bt+55*bs/256);
 lv_obj_send_event(bubble,LV_EVENT_CLICKED,NULL);assert(s_reader);save("bubble_full_reader");
 lv_obj_t *scroll=lv_obj_get_child(s_reader,0);assert(!strcmp(lv_label_get_text(lv_obj_get_child(scroll,0)),long_reply));
 lv_obj_send_event(lv_obj_get_child(s_reader,1),LV_EVENT_CLICKED,NULL);assert(!s_reader);playing=false;
 /* Retry hints expire, but their old timeout cannot erase a newer answer. */
 fake_ms+=3000;lv_tick_inc(3000);pet_wake_open(fake_ms);
 pet_face_hint("再说一句","刚才没听清，可以再说一遍。");assert(s_hint_until);
 fake_ms+=5100;lv_tick_inc(5100);animate(lv_timer_get_next(NULL));
 assert(!s_hint_until&&!strcmp(s_requested_phase,"在这儿")&&lv_obj_is_hidden(lv_obj_get_parent(s_caption)));
 pet_face_hint("再说一句","重试");pet_face_set("说","新的正常回答");
 fake_ms+=5100;lv_tick_inc(5100);animate(lv_timer_get_next(NULL));
 assert(!strcmp(lv_label_get_text(s_caption),"新的正常回答"));
 /* An accepted rest+off waits for the actual bed transition, then remains
  * dark despite raw VAD. A fresh explicit name wake brightens and gets up. */
 pet_face_set("在这儿","");pet_wake_rest();listening=playing=false;
 pet_scene_command(&s_scene,PET_HOME_REST,fake_ms);pet_face_screen_off(true);
 animate(lv_timer_get_next(NULL));assert(actual_brightness>0);
 for(int i=0;i<1000&&s_scene.activity!=PET_HOME_SLEEPING;i++){
  fake_ms+=100;lv_tick_inc(100);animate(lv_timer_get_next(NULL));
 }
 assert(s_scene.activity==PET_HOME_SLEEPING);
 fake_ms+=100;animate(lv_timer_get_next(NULL));assert(actual_brightness==0);
 listening=true;fake_ms+=100;animate(lv_timer_get_next(NULL));
 assert(actual_brightness==0&&s_scene.activity==PET_HOME_SLEEPING);
 listening=false;pet_wake_heard(fake_ms);animate(lv_timer_get_next(NULL));
 assert(actual_brightness==75&&s_scene.activity==PET_HOME_WAKING);
 pet_wake_open(fake_ms);pet_wake_media_begin();pet_face_media_open("媒体查看",true);
 uint16_t *media_pixels=malloc(320*240*2);
 for(int y=0;y<240;y++)for(int x=0;x<320;x++)media_pixels[y*320+x]=((x/40+y/40)%2)?0xe79c:0x8b11;
 assert(pet_face_media_frame(media_pixels,320,240));pet_face_media_status("播放中",true);save("media_playing");
 lv_obj_send_event(lv_obj_get_child(s_media_panel,3),LV_EVENT_CLICKED,NULL);assert(pet_face_media_control()==2);
 pet_face_media_status("已暂停",false);save("media_paused");
 lv_obj_send_event(lv_obj_get_child(s_media_panel,3),LV_EVENT_CLICKED,NULL);assert(pet_face_media_control()==1);
 fake_ms+=120001;lv_tick_inc(120001);assert(!pet_wake_active(fake_ms));
 lv_obj_send_event(lv_obj_get_child(s_media_panel,4),LV_EVENT_CLICKED,NULL);assert(pet_face_media_control()==3);
 assert(pet_wake_active(fake_ms));
 pet_face_media_close();assert(!s_media_panel&&!s_media_pixels);free(media_pixels);save("media_closed");
 pet_scene_init(&s_scene,scene_time());pet_face_set("在这儿","");
 hardware.imu_ready=true;hardware.tilt_x=6;hardware.tilt_y=0;
 hardware.motion_event=PET_MOTION_TILTED;hardware.motion_sequence++;
 save("motion_tilt");assert(s_scene.pose==PET_POSE_THINK&&pet_face_motion_allowed());
 hardware.motion_event=PET_MOTION_TURNED;hardware.motion_sequence++;
 save("motion_surprise");assert(s_scene.pose==PET_POSE_SURPRISE&&!lv_obj_is_hidden(s_startle));
 playing=true;hardware.motion_sequence++;save("motion_speech_priority");assert(!pet_face_motion_allowed());
 playing=false;hardware.tilt_x=0;fake_ms+=2500;lv_tick_inc(2500);save("motion_settled");
 puts("Actual LVGL home and media rendered: perspective, chair transitions, controls, menu, glyphs.");return 0;
}
