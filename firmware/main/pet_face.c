#include "pet_face.h"

#include <string.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdatomic.h>
#include "esp_random.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "pet_audio.h"
#include "pet_capture.h"
#include "pet_hardware.h"
#include "pet_motion.h"
#include "pet_wake_gate.h"
#include "pet_wake.h"
#include "pet_runtime.h"
#include "pet_turn.h"
#include "pet_setup.h"
#include "pet_util.h"
#include "pet_display.h"
#include "pet_scene.h"
#include "pet_asset_codec.h"
#include "pet_tts.h"
#include "pet_screen.h"
#include "character/pet_character_assets.h"
#include "esp_heap_caps.h"
#include "fonts/pet_font_cn_16.h"
#include "fonts/pet_font_owner_28.h"
#include "pet_panel.h"
#include "pet_home_sync.h"

#include "bsp/esp-bsp.h"
#include "lvgl.h"
#include "src/core/lv_obj_event_private.h"
#include "src/misc/cache/instance/lv_image_cache.h"
#include "esp_lv_adapter.h"

static atomic_bool s_motion_allowed;
static atomic_bool s_presentation_allowed,s_result_pending;
static lv_obj_t *s_result_badge;
bool pet_face_motion_allowed(void){return atomic_load(&s_motion_allowed);}
bool pet_face_presentation_allowed(void){return atomic_load(&s_presentation_allowed);}
void pet_face_result_pending(bool pending){atomic_store(&s_result_pending,pending);}

static bool lock_display(int32_t timeout_ms)
{
    /* BSP 2.0.1 returns esp_err_t through bool, reversing success and failure. */
    return esp_lv_adapter_lock(timeout_ms) == ESP_OK;
}

static lv_obj_t *s_body;
static lv_obj_t *s_caption;
static lv_obj_t *s_phase;
static lv_obj_t *s_volume;
static lv_timer_t *s_volume_timer;
static lv_obj_t *s_status, *s_shadow, *s_shade, *s_reader, *s_header;
static int s_mode;
static pet_scene_t s_scene;
static lv_obj_t *s_book,*s_startle;
static uint8_t *s_sprite_pixels, *s_index_pixels, *s_room_pixels;
enum {POSE_CACHE_SLOTS=4};
static uint8_t *s_pose_pixels[POSE_CACHE_SLOTS];
static unsigned s_cached_pose[POSE_CACHE_SLOTS]={PET_ART_COUNT,PET_ART_COUNT,PET_ART_COUNT,PET_ART_COUNT};
static int s_pose_slot;
static lv_obj_t *s_room_obj,*s_cat,*s_cat_shadow,*s_home_hits[PET_PLACE_COUNT];
enum {CAT_CACHE_SLOTS=4,CAT_LEFT=24,CAT_TOP=116,CAT_WIDTH=160,CAT_HEIGHT=144};
static lv_image_dsc_t s_cat_image;static uint8_t*s_cat_pixels,*s_cat_buffers[CAT_CACHE_SLOTS];
static int s_cat_cached_frame[CAT_CACHE_SLOTS]={-1,-1,-1,-1},s_cat_cached_flip[CAT_CACHE_SLOTS],s_cat_slot;
static int s_room_location,s_cat_frame=-1,s_cat_face,s_cat_scale=112;static bool s_cat_front=true;
static float s_cat_x,s_cat_y;static bool s_cat_known;

static lv_image_dsc_t s_room_image;
static unsigned s_room_scale=384;
static lv_obj_t *s_occlusion[PET_PLACE_COUNT];
static uint32_t s_caption_at;
static lv_image_dsc_t s_sprite_image;
static unsigned s_drawn_pose = PET_ART_COUNT;
static char s_requested_phase[64] = "在这儿", s_visible_phase[64];
static lv_obj_t *s_form, *s_field, *s_dropdown;
static SemaphoreHandle_t s_form_done;
static char *s_form_out;
static int s_form_capacity, s_form_result;
static bool s_form_allow_empty, s_form_confirm;
static char *s_last_message;
static char *s_caption_full;
static int s_bubble_tail_x=120;
static int s_caption_text_height=64;
static lv_obj_t *s_menu, *s_birth_input;
static lv_obj_t *s_owner_progress;
static int s_owner_sample;
static int s_owner_target;
static lv_obj_t *s_owner_panel, *s_owner_phrase, *s_owner_hint, *s_owner_title;
static lv_obj_t *s_voice_panel,*s_voice_dropdown,*s_voice_status,*s_voice_current;
static lv_obj_t *s_network_badge;
static lv_obj_t *s_battery_badge,*s_battery_label;
static int s_battery_percent=-2,s_battery_power=-1;
static int s_network_level=-1,s_network_mode=-1;
static SemaphoreHandle_t s_voice_done;
static int s_voice_action,s_voice_index;
static uint32_t s_voice_generation;
static bool s_voice_closing;
static void voice_signal(int action);
static uint32_t s_decode_count,s_decode_us;
static pet_screen_t s_screen;
static lv_obj_t *s_screen_shield;
static bool s_screen_touch;
static int s_screen_brightness=75;
static unsigned s_wake_interactions;
static unsigned s_wake_activations;
static atomic_uint s_screen_request,s_screen_request_sequence;
static lv_obj_t *s_media_panel,*s_media_picture,*s_media_status,*s_media_button_label;
static lv_image_dsc_t s_media_image;
static uint16_t *s_media_pixels;
static bool s_media_playable,s_media_playing;
static atomic_int s_media_control;
static uint32_t s_hint_until;

static void style_panel(lv_obj_t *panel)
{
    lv_obj_set_style_bg_color(panel, lv_color_hex(0x1c1a22), 0);
    lv_obj_set_style_bg_opa(panel, LV_OPA_COVER, 0);
    lv_obj_set_style_text_color(panel, lv_color_hex(0xf6efe4), 0);
    lv_obj_set_style_text_font(panel, &pet_font_cn_16, 0);
    lv_obj_set_style_border_width(panel, 0, 0);
}

static void close_reader(lv_event_t *event)
{
    lv_obj_delete_async(lv_obj_get_parent(lv_event_get_target(event))); s_reader = NULL;
}

static void show_reader(const char *text)
{
    if (!text || !text[0] || s_reader) return;
    lv_obj_t *panel = s_reader = lv_obj_create(lv_screen_active()); lv_obj_set_size(panel, 480, 480); lv_obj_center(panel);
    style_panel(panel);
    lv_obj_t *scroll = lv_obj_create(panel); lv_obj_set_size(scroll, 430, 350); lv_obj_align(scroll, LV_ALIGN_TOP_MID, 0, 0);
    lv_obj_set_scroll_dir(scroll, LV_DIR_VER);
    lv_obj_t *body = lv_label_create(scroll); lv_obj_set_width(body, 395); lv_label_set_text(body, text);
    lv_obj_set_style_text_font(body, &pet_font_cn_16, 0);
    lv_obj_t *back = lv_button_create(panel); lv_obj_set_size(back, 160, 44); lv_obj_align(back, LV_ALIGN_BOTTOM_MID, 0, 0);
    lv_obj_t *label = lv_label_create(back); lv_label_set_text(label, "回去");
    lv_obj_set_style_text_font(label, &pet_font_cn_16, 0); lv_obj_center(label);
    lv_obj_add_event_cb(back, close_reader, LV_EVENT_CLICKED, NULL);
}
static void read_message(lv_event_t *event){show_reader(s_last_message);}
static void read_caption(lv_event_t *event){show_reader(s_caption_full);}

static void draw_caption(lv_event_t *event)
{
    lv_obj_t *card=lv_event_get_target(event);lv_area_t a;lv_obj_get_coords(card,&a);
    lv_layer_t *layer=lv_event_get_layer(event);a.y2-=12;
    lv_draw_rect_dsc_t box;lv_draw_rect_dsc_init(&box);
    box.bg_color=lv_color_hex(0xfff4e8);box.bg_opa=LV_OPA_COVER;box.radius=14;
    box.border_color=lv_color_hex(0xb98083);box.border_width=1;box.border_opa=LV_OPA_COVER;
    lv_draw_rect(layer,&box,&a);
    lv_draw_triangle_dsc_t tail;lv_draw_triangle_dsc_init(&tail);
    int x=a.x1+s_bubble_tail_x;
    tail.p[0]=(lv_point_precise_t){x-8,a.y2-1};tail.p[1]=(lv_point_precise_t){x+8,a.y2-1};
    tail.p[2]=(lv_point_precise_t){x,a.y2+11};tail.color=box.bg_color;tail.opa=LV_OPA_COVER;
    lv_draw_triangle(layer,&tail);
}

static void position_caption(void)
{
    if(!s_caption)return;
    lv_obj_t *card=lv_obj_get_parent(s_caption);if(lv_obj_is_hidden(card))return;
    int left,top,scale;pet_scene_projection(&s_scene,&left,&top,&scale);
    int width=240,line=pet_font_cn_16.line_height+2;
    /* The room is small: put the bubble above the head, towards the side with
     * more space. Its bounded top avoids the header and rounded glass corners. */
    int face_left=left+42*scale/256,face_right=left+166*scale/256;
    int x=s_scene.x<240?face_right+12:face_left-width-12;
    if(x<24)x=24;
    if(x>456-width)x=456-width;
    int lines=3;
    if(x<face_right+6&&x+width>face_left-6){
        lines=(top+45*scale/256-82-36)/line;
        if(lines<1)lines=1;
        if(lines>3)lines=3;
    }
    int text_height=s_caption_text_height;
    if(text_height>lines*line)text_height=lines*line;
    int height=text_height+36;
    if(lv_obj_get_height(s_caption)!=text_height)lv_obj_set_height(s_caption,text_height);
    if(lv_obj_get_height(card)!=height)lv_obj_set_height(card,height);
    int y=top+45*scale/256-height-8;if(y<82)y=82;if(y>320-height)y=320-height;
    int tail=s_scene.x-x;if(tail<22)tail=22;if(tail>width-22)tail=width-22;
    if(tail!=s_bubble_tail_x){s_bubble_tail_x=tail;lv_obj_invalidate(card);}
    if(lv_obj_get_x(card)!=x||lv_obj_get_y(card)!=y)lv_obj_set_pos(card,x,y);
}

static uint32_t scene_time(void) { return (uint32_t)(esp_timer_get_time() / 1000); }

static void screen_activity(void)
{
    pet_screen_activity(&s_screen,scene_time());
    atomic_store(&s_screen_request,0);
}
void pet_face_screen_off(bool after_rest)
{
    atomic_store(&s_screen_request_sequence,pet_wake_interactions());
    atomic_store(&s_screen_request,after_rest?2:1);
}
static void screen_touch(lv_event_t *event)
{
    lv_event_code_t code=lv_event_get_code(event);
    if(code==LV_EVENT_PRESSED){s_screen_touch=true;screen_activity();}
    if(code==LV_EVENT_RELEASED||code==LV_EVENT_PRESS_LOST){
        s_screen_touch=false;lv_obj_set_hidden(s_screen_shield,true);
    }
}
static void screen_input(lv_event_t *event)
{
    /* Runs for touches on every page, including keyboard and menus. */
    if(lv_event_get_code(event)==LV_EVENT_PRESSED)screen_activity();
}

static void draw_network(lv_event_t *event)
{
    lv_obj_t *obj=lv_event_get_target(event);lv_area_t a;lv_obj_get_coords(obj,&a);
    lv_layer_t *layer=lv_event_get_layer(event);
    uint32_t active=s_network_mode==2?0xbad0b3:s_network_mode==1?0xe3ba87:0xbb9698;
    for(int i=0;i<3;i++){
        lv_draw_arc_dsc_t arc;lv_draw_arc_dsc_init(&arc);
        arc.center=(lv_point_t){a.x1+20,a.y1+27};arc.radius=8+i*5;arc.width=2;arc.rounded=1;
        arc.start_angle=225;arc.end_angle=315;
        arc.color=lv_color_hex(s_network_mode==2&&i<s_network_level?active:0x756370);
        arc.opa=LV_OPA_COVER;lv_draw_arc(layer,&arc);
    }
    lv_draw_rect_dsc_t dot;lv_draw_rect_dsc_init(&dot);
    dot.bg_color=lv_color_hex(active);dot.bg_opa=LV_OPA_COVER;dot.radius=LV_RADIUS_CIRCLE;
    lv_area_t point={a.x1+18,a.y1+25,a.x1+22,a.y1+29};lv_draw_rect(layer,&dot,&point);
    if(s_network_mode==0){
        lv_draw_line_dsc_t slash;lv_draw_line_dsc_init(&slash);
        slash.p1=(lv_point_precise_t){a.x1+9,a.y1+8};slash.p2=(lv_point_precise_t){a.x1+30,a.y1+29};
        slash.width=2;slash.color=lv_color_hex(active);slash.round_start=slash.round_end=1;lv_draw_line(layer,&slash);
    }else if(s_network_mode==1){
        /* One warm dot indicates reconnecting, rather than fake signal bars. */
        dot.bg_color=lv_color_hex(active);point=(lv_area_t){a.x1+28,a.y1+23,a.x1+31,a.y1+26};lv_draw_rect(layer,&dot,&point);
    }
}
static void refresh_network(void)
{
    pet_network_state_t state=pet_setup_network_state();
    int mode=state.connected?2:state.connecting?1:0;
    int level=!state.connected||state.rssi<=-127?0:state.rssi>=-60?3:state.rssi>=-75?2:1;
    if(mode!=s_network_mode||level!=s_network_level){
        s_network_mode=mode;s_network_level=level;lv_obj_invalidate(s_network_badge);
    }
}

static void draw_battery(lv_event_t *event)
{
    lv_obj_t *obj=lv_event_get_target(event);lv_area_t a;lv_obj_get_coords(obj,&a);
    lv_layer_t *layer=lv_event_get_layer(event);
    uint32_t color=s_battery_percent<0?0xbb9698:s_battery_percent<=15?0xe79a9b:0xbad0b3;
    lv_draw_rect_dsc_t frame;lv_draw_rect_dsc_init(&frame);
    frame.radius=3;frame.bg_opa=LV_OPA_TRANSP;frame.border_width=1;frame.border_color=lv_color_hex(color);frame.border_opa=LV_OPA_COVER;
    lv_area_t area={a.x1+8,a.y1+5,a.x1+29,a.y1+16};lv_draw_rect(layer,&frame,&area);
    frame.bg_color=lv_color_hex(color);frame.bg_opa=LV_OPA_COVER;frame.border_width=0;frame.radius=1;
    area=(lv_area_t){a.x1+30,a.y1+8,a.x1+32,a.y1+13};lv_draw_rect(layer,&frame,&area);
    if(s_battery_percent>0){
        int width=(18*s_battery_percent+99)/100;
        area=(lv_area_t){a.x1+10,a.y1+7,a.x1+9+width,a.y1+14};lv_draw_rect(layer,&frame,&area);
    }
    if(s_battery_power){
        lv_draw_line_dsc_t bolt;lv_draw_line_dsc_init(&bolt);bolt.width=2;
        bolt.color=lv_color_hex(0xe3ba87);bolt.round_start=bolt.round_end=1;
        const lv_point_precise_t points[]={{a.x1+23,a.y1+3},{a.x1+18,a.y1+10},{a.x1+23,a.y1+10},{a.x1+18,a.y1+18}};
        for(int i=0;i<3;i++){bolt.p1=points[i];bolt.p2=points[i+1];lv_draw_line(layer,&bolt);}
    }
}
static void refresh_battery(pet_hardware_state_t state)
{
    int percent=state.battery_percent<0?-1:state.battery_percent>100?100:state.battery_percent;
    int power=state.usb_power;
    if(percent==s_battery_percent&&power==s_battery_power)return;
    s_battery_percent=percent;s_battery_power=power;
    if(percent<0)lv_label_set_text(s_battery_label,"--");
    else lv_label_set_text_fmt(s_battery_label,"%d%%",percent);
    lv_obj_invalidate(s_battery_badge);
}

static lv_obj_t *status_badge(lv_obj_t *screen,int x,lv_event_cb_t draw)
{
    lv_obj_t *badge=lv_obj_create(screen);lv_obj_remove_style_all(badge);
    lv_obj_set_size(badge,40,36);lv_obj_set_pos(badge,x,26);
    lv_obj_set_style_radius(badge,12,0);lv_obj_set_style_bg_color(badge,lv_color_hex(0x332333),0);
    lv_obj_set_style_bg_opa(badge,205,0);lv_obj_set_clickable(badge,false);lv_obj_set_scrollable(badge,false);
    lv_obj_add_event_cb(badge,draw,LV_EVENT_DRAW_MAIN,NULL);return badge;
}

static void media_close_locked(void)
{
    if(s_media_panel){lv_obj_delete(s_media_panel);s_media_panel=NULL;}
    lv_image_cache_drop(&s_media_image);free(s_media_pixels);s_media_pixels=NULL;
    s_media_picture=s_media_status=s_media_button_label=NULL;s_media_playing=false;
}
static void result_touched(lv_event_t *event){screen_activity();pet_runtime_notify("查看媒体");}
static void media_control(lv_event_t *event)
{
    int control=(int)(intptr_t)lv_event_get_user_data(event);
    if(control==1)control=!s_media_playable?4:s_media_playing?2:1;
    if(control==3)pet_wake_media_return(scene_time());
    atomic_store(&s_media_control,control);screen_activity();
    if(control!=1){pet_audio_stop();pet_turn_next();}
}
void pet_face_media_open(const char *title,bool playable)
{
    if(!lock_display(200))return;
    media_close_locked();screen_activity();atomic_store(&s_media_control,0);
    s_media_pixels=pet_alloc(320*240*2);
    if(!s_media_pixels){bsp_display_unlock();return;}
    memset(s_media_pixels,0,320*240*2);s_media_playable=playable;
    s_media_image=(lv_image_dsc_t){.header={.magic=LV_IMAGE_HEADER_MAGIC,.cf=LV_COLOR_FORMAT_RGB565,.w=320,.h=240,.stride=640},.data_size=320*240*2,.data=(const uint8_t*)s_media_pixels};
    s_media_panel=lv_obj_create(lv_screen_active());lv_obj_set_size(s_media_panel,480,480);lv_obj_center(s_media_panel);style_panel(s_media_panel);
    lv_obj_set_style_pad_all(s_media_panel,0,0);lv_obj_set_scrollable(s_media_panel,false);
    lv_obj_t *label=lv_label_create(s_media_panel);lv_obj_set_width(label,400);lv_label_set_text(label,title);lv_obj_align(label,LV_ALIGN_TOP_MID,0,30);
    lv_label_set_long_mode(label,LV_LABEL_LONG_DOT);lv_obj_set_style_text_align(label,LV_TEXT_ALIGN_CENTER,0);
    s_media_picture=lv_image_create(s_media_panel);lv_image_set_src(s_media_picture,&s_media_image);lv_image_set_scale(s_media_picture,320);
    lv_obj_align(s_media_picture,LV_ALIGN_CENTER,0,-24);
    s_media_status=lv_label_create(s_media_panel);lv_label_set_text(s_media_status,playable?"准备播放":"正在读取图片");lv_obj_align(s_media_status,LV_ALIGN_BOTTOM_MID,0,-72);
    for(int i=0;i<2;i++){
        lv_obj_t *button=lv_button_create(s_media_panel);lv_obj_set_size(button,178,46);lv_obj_set_pos(button,i?252:50,410);
        lv_obj_set_style_bg_color(button,lv_color_hex(i?0x604454:0xb37783),0);lv_obj_set_style_radius(button,12,0);
        lv_obj_t *text=lv_label_create(button);lv_label_set_text(text,i?"回到家里":playable?"播放":"返回列表");lv_obj_center(text);
        if(!i)s_media_button_label=text;
        lv_obj_add_event_cb(button,media_control,LV_EVENT_CLICKED,(void*)(intptr_t)(i?3:1));
    }
    bsp_display_unlock();
}
bool pet_face_media_frame(const uint16_t *pixels,int width,int height)
{
    if(!pixels||width!=320||height!=240||!lock_display(200))return false;
    bool ok=s_media_panel&&s_media_pixels;
    if(ok){lv_image_cache_drop(&s_media_image);memcpy(s_media_pixels,pixels,320*240*2);lv_obj_invalidate(s_media_picture);}
    bsp_display_unlock();return ok;
}
void pet_face_media_status(const char *text,bool playing)
{
    if(!lock_display(200))return;
    if(s_media_panel){
        s_media_playing=playing;lv_label_set_text(s_media_status,text);lv_obj_align(s_media_status,LV_ALIGN_BOTTOM_MID,0,-72);
        lv_label_set_text(s_media_button_label,s_media_playable?(playing?"暂停":"播放"):"返回列表");lv_obj_center(s_media_button_label);
    }
    bsp_display_unlock();
}
int pet_face_media_control(void){return atomic_exchange(&s_media_control,0);}
void pet_face_media_close(void){if(lock_display(200)){media_close_locked();bsp_display_unlock();}}

static void character_hit_test(lv_event_t *event)
{
    lv_hit_test_info_t *hit=lv_event_get_param(event);
    hit->res=false;
    if(!s_sprite_pixels)return;
    /* Image hit testing normally includes its transparent rectangle. Undo
     * the image's scale/rotation about its (0,0) pivot before reading alpha,
     * so furniture behind empty sprite pixels remains reachable. */
    lv_area_t area;lv_obj_get_coords(s_body,&area);
    float angle=lv_image_get_rotation(s_body)*(.001745329252f);
    float dx=hit->point->x-area.x1,dy=hit->point->y-area.y1;
    int scale_x=lv_image_get_scale_x(s_body),scale_y=lv_image_get_scale_y(s_body);
    if(scale_x<=0||scale_y<=0)return;
    int x=(int)floorf((cosf(angle)*dx+sinf(angle)*dy)*256/scale_x);
    int y=(int)floorf((-sinf(angle)*dx+cosf(angle)*dy)*256/scale_y);
    if(x<0||y<0||x>=PET_CHARACTER_WIDTH||y>=PET_CHARACTER_HEIGHT)return;
    hit->res=s_sprite_pixels[PET_CHARACTER_WIDTH*PET_CHARACTER_HEIGHT*2+y*PET_CHARACTER_WIDTH+x]>=32;
}

static void touched(lv_event_t *event)
{
    lv_indev_t *input = lv_indev_active(); lv_point_t point = {0};
    if (input) lv_indev_get_point(input, &point);
    lv_event_code_t code = lv_event_get_code(event);
    if (code == LV_EVENT_PRESSED) {
        ESP_LOGI("pet_touch","target=character point=(%d,%d) rotation=%u",point.x,point.y,pet_display_rotation());
        pet_scene_press(&s_scene, point.x, point.y, scene_time());
        if (pet_audio_playing()) { pet_audio_stop(); pet_turn_next(); }
    } else if (code == LV_EVENT_PRESSING && input) {
        pet_scene_drag(&s_scene, point.x, point.y);
    } else if (code == LV_EVENT_RELEASED) {
        bool tap = pet_scene_release(&s_scene, scene_time());
        pet_home_sync_event(tap?"touch":"move",tap?0:s_scene.x,tap?0:s_scene.y,scene_time());
        if(tap)pet_wake_open(scene_time());
        pet_runtime_notify(tap ? "轻轻摸了一下" : "轻轻挪了个位置");
    } else if (code == LV_EVENT_PRESS_LOST) {
        pet_scene_release(&s_scene, scene_time());
    }
}

/* Only the LVGL thread writes this PSRAM buffer. Flash holds compact indexed
 * frames; LVGL receives a native RGB565 plane followed by the alpha plane. */
static void draw_character(unsigned pose)
{
    if (!s_sprite_pixels || !s_index_pixels || pose >= PET_ART_COUNT || pose == s_drawn_pose) return;
    for(int i=0;i<POSE_CACHE_SLOTS;i++)if(s_pose_pixels[i]&&s_cached_pose[i]==pose){
        s_pose_slot=i;s_sprite_pixels=s_pose_pixels[i];s_sprite_image.data=s_sprite_pixels;
        lv_image_cache_drop(&s_sprite_image);s_drawn_pose=pose;lv_obj_invalidate(s_body);return;
    }
    int slot=0;
    for(int n=1;n<=POSE_CACHE_SLOTS;n++){int candidate=(s_pose_slot+n)%POSE_CACHE_SLOTS;if(s_pose_pixels[candidate]){slot=candidate;break;}}
    for(int n=0;n<POSE_CACHE_SLOTS;n++)if(s_pose_pixels[n]&&s_cached_pose[n]==PET_ART_COUNT){slot=n;break;}
    uint8_t *pixels=s_pose_pixels[slot];
    int64_t started=esp_timer_get_time();
    const pet_character_frame_t *frame = pet_panel_frame(pose);
    const int count = PET_CHARACTER_WIDTH * PET_CHARACTER_HEIGHT;
    if (!frame||!pet_asset_inflate(frame->compressed, frame->compressed_size, s_index_pixels, count)) {
        ESP_LOGE("pet_face", "character decode failed: %d", pose); return;
    }
    for (int i = 0; i < count; i++) {
        const uint8_t *color = frame->palette_bgra + s_index_pixels[i] * 4;
        uint16_t rgb = (uint16_t)((color[2] >> 3) << 11 | (color[1] >> 2) << 5 | (color[0] >> 3));
        int at=frame->mirror?(i/PET_CHARACTER_WIDTH)*PET_CHARACTER_WIDTH+PET_CHARACTER_WIDTH-1-i%PET_CHARACTER_WIDTH:i;
        pixels[at * 2] = rgb & 255; pixels[at * 2 + 1] = rgb >> 8;
        pixels[count * 2 + at] = color[3];
    }
    s_pose_slot=slot;s_cached_pose[slot]=pose;s_sprite_pixels=pixels;s_sprite_image.data=pixels;
    lv_image_cache_drop(&s_sprite_image);
    s_drawn_pose = pose; lv_obj_invalidate(s_body);
    s_decode_count++;s_decode_us+=(uint32_t)(esp_timer_get_time()-started);
}

static void floor_touch(lv_event_t*event){(void)event;lv_indev_t*input=lv_indev_active();if(!input)return;lv_point_t p;lv_indev_get_point(input,&p);if(!pet_home_floor_contains(p.x,p.y))return;pet_home_world_t w;pet_home_sync_world(&w);if(w.online)pet_home_sync_event("walkto",p.x,p.y,scene_time());else if(!w.location)pet_scene_walk_to(&s_scene,p.x,p.y,scene_time());}
static void cat_touch(lv_event_t*event){(void)event;pet_runtime_notify("world:catpet");}
static void cat_hit(lv_event_t*event){
 lv_hit_test_info_t*hit=lv_event_get_param(event);if(!hit||!s_cat_pixels)return;
 lv_area_t area;lv_obj_get_coords(s_cat,&area);int x=(hit->point->x-area.x1)*256/s_cat_scale,y=(hit->point->y-area.y1)*256/s_cat_scale;
 hit->res=x>=0&&x<CAT_WIDTH&&y>=0&&y<CAT_HEIGHT&&s_cat_pixels[CAT_WIDTH*CAT_HEIGHT*2+y*CAT_WIDTH+x]>=32;
}
static bool world_room(int location){
 if(location==s_room_location)return true;
 size_t bytes=0;const uint8_t*source=location?pet_panel_yard(&bytes):pet_panel_room(&bytes);
 if(!source||!s_room_pixels)return false;
 uint8_t*small=heap_caps_malloc(320*320*2,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);if(!small)return false;
 bool ok=pet_asset_inflate(source,bytes,small,320*320*2);
 if(ok){if(s_room_scale==256)ok=pet_asset_expand_room((const uint16_t*)small,(uint16_t*)s_room_pixels);else memcpy(s_room_pixels,small,320*320*2);}
 free(small);if(!ok)return false;s_room_location=location;lv_image_cache_drop(&s_room_image);lv_obj_invalidate(s_room_obj);
 for(int i=1;i<PET_PLACE_COUNT;i++)if(s_home_hits[i])lv_obj_set_hidden(s_home_hits[i],location!=0);
 return true;
}
static void draw_world(const pet_home_world_t*w,uint32_t now){
 if(w->valid)world_room(w->location);
 if(!s_cat||!s_cat_pixels||!s_index_pixels||!w->valid){if(s_cat)lv_obj_set_hidden(s_cat,true);if(s_cat_shadow)lv_obj_set_hidden(s_cat_shadow,true);return;}
 const pet_character_frame_t*f=pet_panel_frame((unsigned)w->cat_frame);if(!f){lv_obj_set_hidden(s_cat,true);lv_obj_set_hidden(s_cat_shadow,true);return;}
 bool flip=f->mirror^(w->cat_frame!=PET_ART_CAT_TURN&&w->cat_face>0);int count=PET_CHARACTER_WIDTH*PET_CHARACTER_HEIGHT;
 if(s_cat_frame!=w->cat_frame||s_cat_face!=(int)flip){
  int slot=-1;for(int i=0;i<CAT_CACHE_SLOTS;i++)if(s_cat_buffers[i]&&s_cat_cached_frame[i]==w->cat_frame&&s_cat_cached_flip[i]==(int)flip){slot=i;break;}
  if(slot<0){
   slot=0;for(int i=1;i<=CAT_CACHE_SLOTS;i++){int candidate=(s_cat_slot+i)%CAT_CACHE_SLOTS;if(s_cat_buffers[candidate]){slot=candidate;break;}}
   for(int i=0;i<CAT_CACHE_SLOTS;i++)if(s_cat_buffers[i]&&s_cat_cached_frame[i]<0){slot=i;break;}
   int64_t started=esp_timer_get_time();
   if(!pet_asset_inflate(f->compressed,f->compressed_size,s_index_pixels,count))return;
   uint8_t*pixels=s_cat_buffers[slot];
   for(int y=0;y<CAT_HEIGHT;y++)for(int x=0;x<CAT_WIDTH;x++){
    int source=(y+CAT_TOP)*PET_CHARACTER_WIDTH+x+CAT_LEFT,at=y*CAT_WIDTH+(flip?CAT_WIDTH-1-x:x);
    const uint8_t*c=f->palette_bgra+s_index_pixels[source]*4;uint16_t rgb=(c[2]>>3)<<11|(c[1]>>2)<<5|c[0]>>3;
    pixels[at*2]=rgb&255;pixels[at*2+1]=rgb>>8;pixels[CAT_WIDTH*CAT_HEIGHT*2+at]=c[3];
   }
   s_cat_cached_frame[slot]=w->cat_frame;s_cat_cached_flip[slot]=flip;s_decode_count++;s_decode_us+=(uint32_t)(esp_timer_get_time()-started);
  }
  s_cat_slot=slot;s_cat_pixels=s_cat_buffers[slot];s_cat_image.data=s_cat_pixels;
  s_cat_frame=w->cat_frame;s_cat_face=flip;lv_image_cache_drop(&s_cat_image);lv_obj_invalidate(s_cat);
 }
 if(!s_cat_known){s_cat_x=w->cat_x;s_cat_y=w->cat_y;s_cat_known=true;}else{s_cat_x+=(w->cat_x-s_cat_x)*.35f;s_cat_y+=(w->cat_y-s_cat_y)*.35f;}
 s_cat_scale=pet_home_scale((int)s_cat_y)*112/224;lv_image_set_scale(s_cat,s_cat_scale);
 int bob=w->cat_mode==3?(w->cat_phase_ms/1700)%2:0;(void)now;
 lv_obj_set_pos(s_cat,(int)s_cat_x-CAT_WIDTH*s_cat_scale/512,(int)s_cat_y-(PET_CHARACTER_HEIGHT-CAT_TOP)*s_cat_scale/256+bob);lv_obj_set_hidden(s_cat,false);
 lv_obj_set_pos(s_cat_shadow,(int)s_cat_x-19,(int)s_cat_y-3);lv_obj_set_hidden(s_cat_shadow,false);
 bool front=s_cat_y>=s_scene.y;
 if(front!=s_cat_front){int at=lv_obj_get_index(s_body);lv_obj_move_to_index(s_cat,front?at+1:at);s_cat_front=front;}
}
static void home_touched(lv_event_t *event)
{
    const pet_home_spot_t *p=lv_event_get_user_data(event);
    lv_indev_t *input=lv_indev_active();lv_point_t point={0};
    if(input)lv_indev_get_point(input,&point);
    ESP_LOGI("pet_touch","target=furniture place=%d point=(%d,%d) rotation=%u",p->place,point.x,point.y,pet_display_rotation());
    pet_home_action_t action=p->place==PET_PLACE_BED?PET_HOME_REST:p->place==PET_PLACE_WASH?PET_HOME_WASH:
        p->place==PET_PLACE_WORK?PET_HOME_WORK:PET_HOME_WINDOW;
    pet_home_request(action);
}

static void menu_page(const char *page);

static void menu_action(lv_event_t *event)
{
    const char *action = lv_event_get_user_data(event);
    if (!strncmp(action, "page:", 5)) { menu_page(action + 5); return; }
    /* Worker-owned settings must be able to leave the indefinite enrollment
     * wait before their queued action can run. Merely closing stays put. */
    if (!strcmp(action, "hours") || !strcmp(action, "write") || !strcmp(action, "wifi") ||
        !strcmp(action, "keys") || !strcmp(action, "ownerkeys") || !strcmp(action, "voiceprint") ||
        !strcmp(action, "activity") || !strcmp(action, "reminders") || !strcmp(action, "birth") || !strcmp(action,"tts") || !strcmp(action,"media")) pet_setup_cancel();
    if (!strncmp(action, "home:", 5)) pet_home_request_text(action + 5);
    else if (!strcmp(action, "quiet")) pet_runtime_quiet(120);
    else if (!strcmp(action, "reader")) read_message(NULL);
    else if (!strcmp(action, "resume")) pet_runtime_quiet(0);
    else if (!strcmp(action, "voice")) pet_runtime_voice_override(30);
    else if (!strcmp(action, "hours")) pet_runtime_notify("设置安静时段");
    else if (!strcmp(action, "write")) pet_runtime_notify("输入一句话");
    else if (!strcmp(action, "wifi")) pet_runtime_notify("配置网络");
    else if (!strcmp(action, "keys")) pet_runtime_notify("配置服务");
    else if (!strcmp(action, "ownerkeys")) pet_runtime_notify("配置声纹服务");
    else if (!strcmp(action, "later")) pet_setup_cancel();
    else if (!strcmp(action, "voiceprint")) pet_runtime_notify("熟悉主人声音");
    else if (!strcmp(action, "activity")) pet_runtime_notify("调整相处节奏");
    else if (!strcmp(action, "reminders")) pet_runtime_notify("看看提醒");
    else if (!strcmp(action, "birth")) pet_runtime_notify("认识我");
    else if (!strcmp(action, "tts")) {pet_audio_stop();pet_turn_next();pet_runtime_notify("选择音色");}
    else if (!strcmp(action, "media")) pet_runtime_notify("查看媒体");
    else if (!strncmp(action,"world:",6))pet_runtime_notify(action);
    else if (!strcmp(action, "websync")) pet_runtime_notify("网页同步");
    if(s_menu)lv_obj_delete_async(s_menu);
    s_menu = NULL;
}

typedef struct { const char *label, *action; } menu_item_t;
static const menu_item_t menu_main[] = {
    {"消息与作品", "page:messages"}, {"生活与声音", "page:life"},
    {"安静陪伴", "page:quiet"}, {"网页与网络", "page:network"}, {"高级设置", "page:advanced"}
};
static const menu_item_t menu_messages[] = {
    {"查看全文", "reader"}, {"查看媒体", "media"}, {"看看提醒", "reminders"}, {"输入一句话", "write"}
};
static const menu_item_t menu_world[]={{"去小院散步","world:yard"},{"一起回家","world:home"},{"摸摸小猫","world:catpet"},{"给小猫添饭","world:catfeed"}};
static const menu_item_t menu_life[] = {
    {"小猫与小院","page:world"},
    {"选择音色", "tts"}, {"去床上休息", "home:rest"}, {"起床洗漱", "home:wake"},
    {"去电脑工作台", "home:work"}, {"看看窗外", "home:window"}, {"逛逛家里", "home:roam"}
};
static const menu_item_t menu_quiet[] = {
    {"安静两小时", "quiet"}, {"恢复正常", "resume"}, {"允许语音半小时", "voice"},
    {"设置安静时段", "hours"}, {"调整相处节奏", "activity"}
};
static const menu_item_t menu_network[] = {{"网页同步", "websync"}, {"配置网络", "wifi"}};
static const menu_item_t menu_advanced[] = {
    {"认识我", "birth"}, {"熟悉主人声音", "voiceprint"}, {"配置服务", "keys"},
#ifndef CONFIG_DESKPET_LOCAL_OWNER
    {"配置声纹服务", "ownerkeys"},
#endif
    {"稍后再设置", "later"}
};
static void menu_button(lv_obj_t *parent,const char *label,const char *action)
{
    lv_obj_t *button=lv_button_create(parent);lv_obj_set_size(button,lv_pct(100),44);
    lv_obj_t *text=lv_label_create(button);lv_label_set_text(text,label);lv_obj_center(text);
    lv_obj_add_event_cb(button,menu_action,LV_EVENT_CLICKED,(void *)action);
}
static void menu_page(const char *page)
{
    const menu_item_t *items=menu_main;size_t count=sizeof(menu_main)/sizeof(*menu_main);const char *title="家里菜单";
#define MENU_PAGE(key,array,name) if(!strcmp(page,key)){items=array;count=sizeof(array)/sizeof(*array);title=name;}
    MENU_PAGE("messages",menu_messages,"消息与作品")
    MENU_PAGE("life",menu_life,"生活与声音")
    MENU_PAGE("world",menu_world,"小猫与小院")
    MENU_PAGE("quiet",menu_quiet,"安静陪伴")
    MENU_PAGE("network",menu_network,"网页与网络")
    MENU_PAGE("advanced",menu_advanced,"高级设置")
#undef MENU_PAGE
    if(s_menu)lv_obj_delete_async(s_menu);
    lv_obj_t *panel=s_menu=lv_obj_create(lv_screen_active());
    lv_obj_set_size(panel,400,414);lv_obj_center(panel);style_panel(panel);
    lv_obj_set_scrollable(panel,false);lv_obj_set_flex_flow(panel,LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_text_font(panel,&pet_font_cn_16,0);
    lv_obj_t *heading=lv_label_create(panel);lv_label_set_text(heading,title);
    lv_obj_t *list=lv_obj_create(panel);lv_obj_set_width(list,lv_pct(100));lv_obj_set_flex_grow(list,1);
    lv_obj_set_style_bg_opa(list,LV_OPA_TRANSP,0);lv_obj_set_style_border_width(list,0,0);
    lv_obj_set_style_pad_all(list,0,0);lv_obj_set_flex_flow(list,LV_FLEX_FLOW_COLUMN);
    for(size_t i=0;i<count;i++)menu_button(list,items[i].label,items[i].action);
    /* Navigation stays visible while the content scrolls. */
    menu_button(panel,!strcmp(page,"main")?"回去":"返回上一级",!strcmp(page,"main")?"close":"page:main");
}
static void menu(lv_event_t *event)
{
    if(s_menu||s_form||s_voice_panel)return;
    menu_page("main");
}

void pet_face_toggle_menu(void)
{
    if (!s_phase || !lock_display(200)) return;
    screen_activity();
    if(s_media_panel){pet_wake_media_return(scene_time());atomic_store(&s_media_control,3);media_close_locked();pet_audio_stop();pet_turn_next();}
    if(s_voice_panel)voice_signal(PET_VOICE_CLOSE);
    else if (s_menu) { lv_obj_delete_async(s_menu); s_menu = NULL; ESP_LOGI("pet_face", "physical menu closed"); }
    else if (!s_form) {
        if (s_reader) { lv_obj_delete_async(s_reader); s_reader = NULL; }
        menu(NULL);
        ESP_LOGI("pet_face", "physical menu opened");
    }
    esp_lv_adapter_unlock();
}


/* Called only on the LVGL thread or with the display lock held. Capture never
 * touches LVGL; it supplies live state which this 100ms timer renders. */
static void refresh_activity(void)
{
    const char *phase = s_requested_phase;
    if (!s_form && !s_menu && !s_owner_panel && !s_reader && !s_voice_panel) {
        if (pet_capture_listening()) phase = "我在听";
        else if (pet_wake_feedback(scene_time())) phase = "我在，听你说";
        else if (pet_audio_playing()) phase = "说";
        else if (pet_capture_pending()) phase = "理解中";
    }
    s_mode = !strcmp(phase, "我在听") || !strcmp(phase, "听") ? 1 :
        !strcmp(phase, "想") || !strcmp(phase, "理解中") || !strcmp(phase, "听清内容") ||
        !strcmp(phase, "认声音") ? 2 : !strcmp(phase, "说") ? 3 : 0;
    lv_obj_set_hidden(s_header, !strcmp(phase, "在这儿"));
    if (!strcmp(s_visible_phase, phase)) return;
    pet_utf8_copy(s_visible_phase, sizeof(s_visible_phase), phase);
    lv_label_set_text(s_phase, phase);

}

static void animate(lv_timer_t *timer)
{
    int64_t callback_started=esp_timer_get_time();
    static uint32_t profile_at,callback_count,callback_max_us,interval_max_ms,previous_at;
    static pet_display_profile_t previous_profile;
    uint32_t now=scene_time();
    if(previous_at&&now-previous_at>interval_max_ms)interval_max_ms=now-previous_at;
    previous_at=now;
    static int last_activity=-1;
    static int shade_opa=-1;
    static uint32_t next_status;
    static uint32_t next_network;
    if(s_hint_until&&((int32_t)(now-s_hint_until)>=0||
       (pet_wake_required()&&!pet_wake_active(now)))){
        s_hint_until=0;pet_utf8_copy(s_requested_phase,sizeof(s_requested_phase),"在这儿");
        lv_label_set_text(s_caption,"");lv_obj_set_hidden(lv_obj_get_parent(s_caption),true);
    }
    refresh_activity();
    if(!next_network||(int32_t)(now-next_network)>=0){refresh_network();next_network=now+1000;}
    bool listening = pet_capture_listening();
    if (s_owner_panel && s_owner_target) {
        char progress[96]; int ms = pet_capture_recorded_ms();
        if (!s_owner_sample) snprintf(progress, sizeof(progress), "第 %d/4 段 - 请稍等", s_owner_target);
        else if (listening) snprintf(progress, sizeof(progress), "第 %d/4 段 - 已听到 %d.%d 秒", s_owner_sample, ms / 1000, ms % 1000 / 100);
        else snprintf(progress, sizeof(progress), "第 %d/4 段 - 等你开口", s_owner_sample);
        lv_label_set_text(s_owner_progress, progress);
    }
    pet_hardware_state_t state = pet_hardware_state();
    int minute = state.clock_valid ? pet_hardware_local_minute() : -1;
    bool tired = state.battery_percent >= 0 && state.battery_percent <= 15 && !state.usb_power;
    bool blocked = s_form || s_menu || s_owner_panel || s_reader || s_voice_panel || s_media_panel;
    unsigned interactions=pet_wake_interactions();
    if(interactions!=s_wake_interactions){
        s_wake_interactions=interactions;pet_screen_activity(&s_screen,now);
        if(interactions!=atomic_load(&s_screen_request_sequence))atomic_store(&s_screen_request,0);
    }
    unsigned activations=pet_wake_activations();
    if(activations!=s_wake_activations){
        s_wake_activations=activations;
        if(!blocked&&s_scene.activity==PET_HOME_SLEEPING){pet_home_sync_event("roam",0,0,now);pet_scene_command(&s_scene,PET_HOME_ROAM,now);}
    }
    if(blocked)screen_activity();
    unsigned request=atomic_load(&s_screen_request);
    if(request&&!blocked&&!listening&&!pet_audio_playing()&&s_mode!=2&&
       (request==1||s_scene.activity==PET_HOME_SLEEPING)){
        pet_screen_off(&s_screen);atomic_store(&s_screen_request,0);
    }
    int brightness=pet_screen_brightness(&s_screen,now,state.usb_power,
        blocked||listening||pet_audio_playing()||s_mode==2,tired);
    bool screen_off=brightness==0;
    if(brightness!=s_screen_brightness){
        if(bsp_display_brightness_set(brightness)==ESP_OK){
            if(!brightness||!s_screen_brightness)
                ESP_LOGI("pet_face","screen %s power=%s",brightness?"awake":"off",state.usb_power?"usb":"battery");
            s_screen_brightness=brightness;
        }
    }
    lv_obj_set_hidden(s_screen_shield,!screen_off&&!s_screen_touch);
    lv_timer_set_period(timer,screen_off?100:33);
    bool night = minute >= 1320 || (minute >= 0 && minute < 420) || pet_wake_resting();
    atomic_store(&s_presentation_allowed,!blocked&&!screen_off&&!night&&!tired&&!listening&&!pet_capture_pending()&&s_mode!=2&&!pet_audio_playing());
    if(s_result_badge)lv_obj_set_hidden(s_result_badge,blocked||screen_off||!atomic_load(&s_result_pending));
    atomic_store(&s_motion_allowed,!blocked&&!screen_off&&!night&&!tired&&!listening&&s_mode!=2&&
        !pet_audio_playing()&&s_scene.place==PET_PLACE_FLOOR&&s_scene.activity==PET_HOME_IDLE);
    static unsigned motion_sequence;
    if(state.motion_sequence!=motion_sequence){
        motion_sequence=state.motion_sequence;
        if(atomic_load(&s_motion_allowed)){
            pet_pose_t reaction=(state.motion_event&(PET_MOTION_SHAKEN|PET_MOTION_TURNED))?PET_POSE_SURPRISE:
                (state.motion_event&PET_MOTION_SETTLED)?PET_POSE_HAPPY:PET_POSE_THINK;
            pet_scene_react(&s_scene,reaction,scene_time());pet_home_sync_event("react",reaction,0,scene_time());
        }
    }
    if(s_startle)lv_obj_set_hidden(s_startle,true);
    pet_scene_input_t scene_input={.now_ms=scene_time(), .random=esp_random(),
        .listening=listening, .speaking=pet_audio_playing(), .thinking=s_mode==2,
        .blocked=blocked, .night=night, .tired=tired, .clock_valid=state.clock_valid};
    const char*caption=s_caption&&!lv_obj_is_hidden(lv_obj_get_parent(s_caption))?lv_label_get_text(s_caption):"";
    pet_home_world_t world;pet_home_sync_world(&world);
    if(world.valid&&world.location&&!world.online)scene_input.blocked=true;
    if(!pet_home_sync_step(&s_scene,scene_input,s_requested_phase,caption))pet_scene_step(&s_scene,scene_input);
    if (!blocked && !screen_off) {
        draw_character(pet_scene_art_frame(&s_scene,scene_time()));
        draw_world(&world,scene_time());
        int left, top, scale; pet_scene_projection(&s_scene, &left, &top, &scale);
        position_caption();
        if(s_book){
            bool reading=s_scene.activity==PET_HOME_READING&&!listening&&s_mode!=2&&!pet_audio_playing();
            lv_obj_set_hidden(s_book,!reading);
            if(reading){
                lv_obj_set_size(s_book,54*scale/256,34*scale/256);
                lv_obj_set_pos(s_book,left+77*scale/256,top+169*scale/256);
            }
        }
        if(last_activity!=(int)s_scene.activity) {
            ESP_LOGI("pet_face","home activity=%d place=%d target=%d ground=(%d,%d) scale=%d",
                s_scene.activity,s_scene.place,s_scene.destination,s_scene.x,s_scene.y,scale);
            last_activity=s_scene.activity;
        }
        int bob = s_scene.pose == PET_POSE_IDLE ? (int)(sinf((now%3491)*.0018f)*1.5f) : 0;
        int lean_x=state.imu_ready&&s_scene.place==PET_PLACE_FLOOR&&!listening?state.tilt_x:0;
        int lean_y=state.imu_ready&&s_scene.place==PET_PLACE_FLOOR&&!listening?state.tilt_y:0;
        bool startled=atomic_load(&s_motion_allowed)&&s_scene.reaction==PET_POSE_SURPRISE&&
            (int32_t)(s_scene.reaction_until-scene_time())>0;
        if(s_startle&&startled){lv_obj_set_pos(s_startle,left+175*scale/256,top+18*scale/256);lv_obj_set_hidden(s_startle,false);}
        int lean_angle=lean_x*5+(startled?(int)(sinf(now*.018f)*25):0);
        if(s_scene.place!=PET_PLACE_FLOOR||listening||blocked)lean_angle=0;
        lv_image_set_rotation(s_body,lean_angle);
        lv_image_set_scale(s_body, scale); lv_obj_set_pos(s_body, left+lean_x, top+bob+lean_y);
        lv_obj_set_size(s_shadow, 124 * scale / 256, 12 * scale / 256);
        lv_obj_set_pos(s_shadow, s_scene.x - 62 * scale / 256+lean_x, s_scene.y - 5+lean_y);
        lv_obj_set_hidden(s_shadow, s_scene.place == PET_PLACE_BED || s_scene.place == PET_PLACE_WORK);
        for(int i=1;i<PET_PLACE_COUNT;i++)if(s_occlusion[i]){
            const pet_home_spot_t*p=&pet_home_spots[i];bool lying=i==PET_PLACE_BED&&s_drawn_pose==PET_POSE_LIE_SLEEP;
            int y=lying?PET_BED_COVER_Y:p->mask_y,h=lying?PET_BED_COVER_H:p->mask_h;
            lv_obj_set_pos(s_occlusion[i],p->mask_x,y);lv_obj_set_size(s_occlusion[i],lying?PET_BED_COVER_W:p->mask_w,h);
            lv_obj_t*front=lv_obj_get_child(s_occlusion[i],0);if(front)lv_obj_set_pos(front,-p->mask_x,-y);
            /* A lying cel is already in the mattress plane even while the
             * logical feet still carry the bed-edge transition anchor. */
            lv_obj_set_hidden(s_occlusion[i],s_room_location!=0||(!lying&&s_scene.y>=p->front_y));
        }
        if (!strcmp(s_requested_phase, "在这儿") && !listening && !pet_audio_playing() && scene_time()-s_caption_at>8000)
            lv_obj_set_hidden(lv_obj_get_parent(s_caption), true);
        int opa=night?58:0;
        if(opa!=shade_opa){lv_obj_set_style_bg_opa(s_shade,opa,0);shade_opa=opa;}
    }
    if (!next_status||(int32_t)(now-next_status)>=0) {
        next_status=now+1000;
        char status[96];
        refresh_battery(state);
        snprintf(status, sizeof(status), "%s",pet_audio_output_allowed() ? "" : "安静陪你");
        if (s_scene.activity == PET_HOME_WAIT_COMPUTER || s_scene.activity == PET_HOME_WORKING) {
            const char *pc[] = {" 电脑未配置", " 电脑已连接", " 电脑任务进行中", " 电脑状态待核对", " 电脑待检查"};
            unsigned computer=(unsigned)pet_home_computer_state();
            if(computer<sizeof(pc)/sizeof(pc[0]))strncat(status, pc[computer], sizeof(status)-strlen(status)-1);
        }
        if(pet_wake_required()){
            char phrase[32],hint[64];pet_wake_phrase(phrase,sizeof(phrase));snprintf(hint,sizeof(hint)," %s唤醒",phrase);
            const char *wake=pet_wake_active(scene_time())?" 可以说话":pet_wake_ready()?hint:" 点我说话";
            strncat(status,wake,sizeof(status)-strlen(status)-1);
        }
        if(strcmp(status,lv_label_get_text(s_status)))lv_label_set_text(s_status, status);
        lv_obj_set_hidden(s_status, !status[0]);
    }
    uint32_t elapsed=(uint32_t)(esp_timer_get_time()-callback_started);
    callback_count++;if(elapsed>callback_max_us)callback_max_us=elapsed;
    if(now-profile_at>=5000){
        pet_display_profile_t p=pet_display_profile();uint32_t span=now-profile_at;
        ESP_LOGI("pet_ui_perf","window_ms=%u activity=%d frames=%u ticks=%u tick_max_ms=%u callback_max_us=%u decodes=%u decode_us=%u pixels=%u transfer_us=%llu",
            (unsigned)span,s_scene.activity,(unsigned)(p.frames-previous_profile.frames),(unsigned)callback_count,
            (unsigned)interval_max_ms,(unsigned)callback_max_us,(unsigned)s_decode_count,(unsigned)s_decode_us,
            (unsigned)(p.pixels-previous_profile.pixels),(unsigned long long)(p.transfer_us-previous_profile.transfer_us));
        previous_profile=p;profile_at=now;callback_count=callback_max_us=interval_max_ms=s_decode_count=s_decode_us=0;
    }
}

static void hide_volume(lv_timer_t *timer)
{
    lv_obj_set_hidden(s_volume, true);
    lv_timer_pause(timer);
}

void pet_face_start(void)
{
    pet_display_start();
    ESP_ERROR_CHECK(esp_lv_adapter_lock(-1));
    pet_panel_bind();

    lv_obj_t *screen = lv_screen_active();
    lv_obj_set_style_bg_color(screen, lv_color_hex(0x1c1a22), 0);

    s_room_pixels = heap_caps_malloc(320*320*2, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    size_t room_bytes;const uint8_t *room_data=pet_panel_room(&room_bytes);
    if (s_room_pixels && pet_asset_inflate(room_data, room_bytes, s_room_pixels, 320*320*2)) {
        uint8_t *native=heap_caps_malloc(480*480*2,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
        if(native&&pet_asset_expand_room((const uint16_t*)s_room_pixels,(uint16_t*)native)){
            free(s_room_pixels);s_room_pixels=native;s_room_scale=256;
        }else free(native);
        unsigned side=s_room_scale==256?480:320;
        s_room_image = (lv_image_dsc_t){.header={.magic=LV_IMAGE_HEADER_MAGIC,.cf=LV_COLOR_FORMAT_RGB565,
            .w=side,.h=side,.stride=side*2}, .data_size=side*side*2,.data=s_room_pixels};
        lv_obj_t *room = s_room_obj = lv_image_create(screen);
        lv_image_set_src(room, &s_room_image); lv_image_set_pivot(room, 0, 0);
        lv_image_set_scale(room, s_room_scale); lv_obj_set_pos(room, 0, 0); lv_obj_set_clickable(room, true);lv_obj_add_event_cb(room,floor_touch,LV_EVENT_CLICKED,NULL);
        for(int i=1;i<PET_PLACE_COUNT;i++) {
            const pet_home_spot_t *p = &pet_home_spots[i];
            lv_obj_t *hit = s_home_hits[i] = lv_obj_create(screen); lv_obj_remove_style_all(hit);
            lv_obj_set_size(hit,p->w,p->h); lv_obj_set_pos(hit,p->x,p->y);
            lv_obj_set_scrollable(hit,false); lv_obj_set_clickable(hit,true);
            lv_obj_add_event_cb(hit, home_touched, LV_EVENT_CLICKED, (void *)p);
        }
    } else ESP_LOGE("pet_face", "home background decode failed");
    s_shade = lv_obj_create(screen); lv_obj_remove_style_all(s_shade);
    lv_obj_set_size(s_shade, 480, 480); lv_obj_set_style_bg_color(s_shade, lv_color_hex(0x252445), 0);
    lv_obj_set_style_bg_opa(s_shade, 0, 0); lv_obj_set_clickable(s_shade, false);
    s_shadow = lv_obj_create(screen); lv_obj_remove_style_all(s_shadow);
    lv_obj_set_size(s_shadow, 124, 14); lv_obj_set_style_radius(s_shadow, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(s_shadow, lv_color_hex(0x685154), 0); lv_obj_set_style_bg_opa(s_shadow, 55, 0);
    lv_obj_set_clickable(s_shadow, false);
    pet_scene_init(&s_scene, scene_time());
    s_body = lv_image_create(screen);
    s_index_pixels = heap_caps_malloc(PET_CHARACTER_WIDTH * PET_CHARACTER_HEIGHT, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    s_sprite_pixels = heap_caps_malloc(PET_CHARACTER_WIDTH * PET_CHARACTER_HEIGHT * 3, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    s_pose_pixels[0]=s_sprite_pixels;
    for(int i=1;i<POSE_CACHE_SLOTS;i++)s_pose_pixels[i]=heap_caps_malloc(PET_CHARACTER_WIDTH*PET_CHARACTER_HEIGHT*3,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if (s_sprite_pixels && s_index_pixels) {
        memset(s_sprite_pixels, 0, PET_CHARACTER_WIDTH * PET_CHARACTER_HEIGHT * 3);
        s_sprite_image = (lv_image_dsc_t){.header={.magic=LV_IMAGE_HEADER_MAGIC,
            .cf=LV_COLOR_FORMAT_RGB565A8, .w=PET_CHARACTER_WIDTH, .h=PET_CHARACTER_HEIGHT,
            .stride=PET_CHARACTER_WIDTH*2}, .data_size=PET_CHARACTER_WIDTH*PET_CHARACTER_HEIGHT*3,
            .data=s_sprite_pixels};
        lv_image_set_src(s_body, &s_sprite_image); lv_image_set_pivot(s_body, 0, 0); draw_character(PET_POSE_IDLE);
        if (s_drawn_pose == PET_POSE_IDLE && s_room_image.data)
            ESP_LOGI("pet_face", "character scene ready: %d poses, %d sprite bytes in PSRAM", PET_ART_COUNT,
                     PET_CHARACTER_WIDTH * PET_CHARACTER_HEIGHT * 3);
        else ESP_LOGE("pet_face", "home scene initialization incomplete");
    } else ESP_LOGE("pet_face", "character PSRAM allocation failed");
    for(int i=0;i<CAT_CACHE_SLOTS;i++)s_cat_buffers[i]=heap_caps_malloc(CAT_WIDTH*CAT_HEIGHT*3,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    s_cat_pixels=s_cat_buffers[0];
    if(s_cat_pixels){
        memset(s_cat_pixels,0,CAT_WIDTH*CAT_HEIGHT*3);
        s_cat_shadow=lv_obj_create(screen);lv_obj_remove_style_all(s_cat_shadow);lv_obj_set_size(s_cat_shadow,38,6);lv_obj_set_style_radius(s_cat_shadow,LV_RADIUS_CIRCLE,0);lv_obj_set_style_bg_color(s_cat_shadow,lv_color_hex(0x685154),0);lv_obj_set_style_bg_opa(s_cat_shadow,45,0);lv_obj_set_clickable(s_cat_shadow,false);lv_obj_set_hidden(s_cat_shadow,true);
        s_cat=lv_image_create(screen);s_cat_image=(lv_image_dsc_t){.header={.magic=LV_IMAGE_HEADER_MAGIC,.cf=LV_COLOR_FORMAT_RGB565A8,.w=CAT_WIDTH,.h=CAT_HEIGHT,.stride=CAT_WIDTH*2},.data_size=CAT_WIDTH*CAT_HEIGHT*3,.data=s_cat_pixels};
        lv_image_set_src(s_cat,&s_cat_image);lv_image_set_pivot(s_cat,0,0);lv_image_set_scale(s_cat,112);lv_obj_set_clickable(s_cat,true);lv_obj_set_adv_hittest(s_cat,true);lv_obj_add_event_cb(s_cat,cat_hit,LV_EVENT_HIT_TEST,NULL);lv_obj_add_event_cb(s_cat,cat_touch,LV_EVENT_CLICKED,NULL);lv_obj_set_hidden(s_cat,true);
    }
    s_startle=lv_label_create(screen);lv_label_set_text(s_startle,"!");
    lv_obj_set_style_text_font(s_startle,&pet_font_owner_28,0);
    lv_obj_set_style_text_color(s_startle,lv_color_hex(0xffe8a8),0);
    lv_obj_set_style_bg_color(s_startle,lv_color_hex(0x49324f),0);
    lv_obj_set_style_bg_opa(s_startle,200,0);lv_obj_set_style_radius(s_startle,10,0);
    lv_obj_set_style_pad_hor(s_startle,8,0);lv_obj_set_hidden(s_startle,true);
    s_book=lv_obj_create(screen);lv_obj_remove_style_all(s_book);
    lv_obj_set_size(s_book,54,34);lv_obj_set_style_radius(s_book,3,0);
    lv_obj_set_style_bg_color(s_book,lv_color_hex(0xfff0d4),0);lv_obj_set_style_bg_opa(s_book,255,0);
    lv_obj_set_style_border_width(s_book,2,0);lv_obj_set_style_border_color(s_book,lv_color_hex(0xa45e67),0);
    lv_obj_set_clickable(s_book,false);lv_obj_set_scrollable(s_book,false);lv_obj_set_hidden(s_book,true);
    lv_obj_t *spine=lv_obj_create(s_book);lv_obj_remove_style_all(spine);
    lv_obj_set_size(spine,2,LV_PCT(85));lv_obj_center(spine);
    lv_obj_set_style_bg_color(spine,lv_color_hex(0xc79877),0);lv_obj_set_style_bg_opa(spine,180,0);lv_obj_set_clickable(spine,false);
    lv_obj_set_pos(s_body, 136, 126); lv_obj_set_clickable(s_body, true);
    lv_obj_set_scrollable(s_body, false);
    lv_obj_set_ext_click_area(s_body,48);
    lv_obj_set_adv_hittest(s_body,true);
    lv_obj_add_event_cb(s_body,character_hit_test,LV_EVENT_HIT_TEST,NULL);
    lv_obj_add_event_cb(s_body, touched, LV_EVENT_PRESSED, NULL);
    lv_obj_add_event_cb(s_body, touched, LV_EVENT_PRESSING, NULL);
    lv_obj_add_event_cb(s_body, touched, LV_EVENT_RELEASED, NULL);
    lv_obj_add_event_cb(s_body, touched, LV_EVENT_PRESS_LOST, NULL);

    if (s_room_image.data) for (int i=1;i<PET_PLACE_COUNT;i++) {
        const pet_home_spot_t *p=&pet_home_spots[i]; if(!p->mask_w) continue;
        lv_obj_t *clip=s_occlusion[i]=lv_obj_create(screen); lv_obj_remove_style_all(clip);
        lv_obj_set_pos(clip,p->mask_x,p->mask_y);lv_obj_set_size(clip,p->mask_w,p->mask_h);
        lv_obj_set_scrollable(clip,false);lv_obj_set_clickable(clip,false);
        lv_obj_t *front=lv_image_create(clip);lv_image_set_src(front,&s_room_image);
        lv_image_set_pivot(front,0,0);lv_image_set_scale(front,s_room_scale);
        lv_obj_set_pos(front,-p->mask_x,-p->mask_y);lv_obj_set_clickable(front,false);
        lv_obj_set_hidden(clip,true);
    }
    /* The night tint covers furniture crops as well, preserving their seams. */
    lv_obj_move_to_index(s_shade, lv_obj_get_child_count(screen)-1);
    lv_obj_t *header = s_header = lv_obj_create(screen); lv_obj_remove_style_all(header);
    lv_obj_set_size(header, 292, 48); lv_obj_set_pos(header, 94, 18);
    lv_obj_set_style_radius(header, 18, 0); lv_obj_set_style_bg_color(header, lv_color_hex(0x332333), 0);
    lv_obj_set_style_bg_opa(header, 218, 0); lv_obj_set_clickable(header, false);
    s_phase = lv_label_create(header); lv_label_set_text(s_phase, "在这儿");
    lv_obj_set_style_text_color(s_phase, lv_color_hex(0xfff7ee), 0);
    lv_obj_set_style_text_font(s_phase, &pet_font_cn_16, 0); lv_obj_center(s_phase);

    lv_obj_t *caption_card = lv_obj_create(screen); lv_obj_remove_style_all(caption_card);
    lv_obj_set_size(caption_card, 240, 100); lv_obj_set_pos(caption_card, 24, 82);
    lv_obj_set_clickable(caption_card, true);lv_obj_set_scrollable(caption_card,false);
    lv_obj_add_event_cb(caption_card,draw_caption,LV_EVENT_DRAW_MAIN,NULL);
    lv_obj_add_event_cb(caption_card,read_caption,LV_EVENT_CLICKED,NULL);
    s_caption = lv_label_create(caption_card);
    lv_label_set_long_mode(s_caption, LV_LABEL_LONG_DOT);
    lv_obj_set_width(s_caption, 212);lv_obj_set_height(s_caption, 64);
    lv_obj_set_style_text_align(s_caption, LV_TEXT_ALIGN_LEFT, 0);
    lv_obj_set_style_text_line_space(s_caption,2,0);
    lv_obj_set_style_text_color(s_caption, lv_color_hex(0x553b45), 0);
    lv_obj_set_style_text_font(s_caption, &pet_font_cn_16, 0);
    lv_label_set_text(s_caption, "连上网络就能说话");
    lv_obj_set_pos(s_caption,14,12);lv_obj_set_clickable(s_caption,false);
    s_status = lv_label_create(screen);
    lv_label_set_text(s_status, "");
    lv_obj_set_hidden(s_status, true);
    lv_obj_set_style_text_font(s_status, &pet_font_cn_16, 0);
    lv_obj_set_style_text_color(s_status, lv_color_hex(0xfff7ee), 0);
    lv_obj_set_style_bg_color(s_status, lv_color_hex(0x332333), 0);
    lv_obj_set_style_bg_opa(s_status, 210, 0);
    lv_obj_set_style_radius(s_status, 8, 0); lv_obj_set_style_pad_hor(s_status, 8, 0);
    lv_obj_align(s_status, LV_ALIGN_BOTTOM_MID, 0, -12);
    s_volume = lv_label_create(screen);
    lv_obj_set_style_text_font(s_volume, &pet_font_cn_16, 0);
    lv_obj_set_style_text_color(s_volume, lv_color_hex(0xf6efe4), 0);
    lv_obj_set_style_bg_color(s_volume, lv_color_hex(0x332333), 0);
    lv_obj_set_style_bg_opa(s_volume, 220, 0); lv_obj_set_style_pad_hor(s_volume, 8, 0);
    lv_obj_align(s_volume, LV_ALIGN_TOP_MID, 0, 64);
    lv_obj_set_hidden(s_volume, true);
    s_volume_timer = lv_timer_create(hide_volume, 2000, NULL);
    lv_timer_pause(s_volume_timer);
    s_battery_badge=status_badge(screen,36,draw_battery);
    s_battery_label=lv_label_create(s_battery_badge);
    lv_obj_set_style_text_font(s_battery_label,LV_FONT_DEFAULT,0);
    lv_obj_set_style_text_color(s_battery_label,lv_color_hex(0xfff7ee),0);
    lv_obj_align(s_battery_label,LV_ALIGN_BOTTOM_MID,0,-1);
    refresh_battery(pet_hardware_state());
    s_network_badge=status_badge(screen,404,draw_network);refresh_network();
    s_result_badge=lv_obj_create(screen);lv_obj_remove_style_all(s_result_badge);
    lv_obj_set_size(s_result_badge,10,10);lv_obj_set_pos(s_result_badge,437,55);
    lv_obj_set_style_bg_color(s_result_badge,lv_color_hex(0xffd5a5),0);lv_obj_set_style_bg_opa(s_result_badge,255,0);
    lv_obj_set_style_radius(s_result_badge,LV_RADIUS_CIRCLE,0);lv_obj_set_ext_click_area(s_result_badge,12);
    lv_obj_set_scrollable(s_result_badge,false);lv_obj_set_hidden(s_result_badge,true);
    lv_obj_set_clickable(s_result_badge,true);lv_obj_add_event_cb(s_result_badge,result_touched,LV_EVENT_CLICKED,NULL);
    s_screen_shield=lv_obj_create(lv_layer_top());lv_obj_remove_style_all(s_screen_shield);
    lv_obj_set_size(s_screen_shield,480,480);lv_obj_set_pos(s_screen_shield,0,0);
    lv_obj_set_clickable(s_screen_shield,true);lv_obj_set_scrollable(s_screen_shield,false);
    lv_obj_add_event_cb(s_screen_shield,screen_touch,LV_EVENT_ALL,NULL);
    lv_obj_set_hidden(s_screen_shield,true);screen_activity();
    for(lv_indev_t *input=lv_indev_get_next(NULL);input;input=lv_indev_get_next(input))
        lv_indev_add_event_cb(input,screen_input,LV_EVENT_PRESSED,NULL);
    lv_timer_create(animate, 33, NULL);

    bsp_display_unlock();
}

void pet_face_show_volume(int volume)
{
    if (!lock_display(200)) return;
    screen_activity();
    if (volume == 0) {
        lv_label_set_text(s_volume, "静音");
    } else {
        lv_label_set_text_fmt(s_volume, "音量 %d%%", volume);
    }
    lv_obj_set_hidden(s_volume, false);
    lv_timer_reset(s_volume_timer);
    lv_timer_resume(s_volume_timer);
    bsp_display_unlock();
}

static void birth_keyboard(lv_event_t *event) { pet_setup_keyboard(); }

void pet_face_birth_input(int visible)
{
    if (!lock_display(-1)) return;
    if (visible && !s_birth_input) {
        s_birth_input = lv_button_create(lv_screen_active());
        lv_obj_set_size(s_birth_input, 88, 40);
        lv_obj_align(s_birth_input, LV_ALIGN_TOP_RIGHT, -12, 108);
        lv_obj_t *label = lv_label_create(s_birth_input);
        lv_obj_set_style_text_font(label, &pet_font_cn_16, 0);
        lv_label_set_text(label, "屏幕输入"); lv_obj_center(label);
        lv_obj_add_event_cb(s_birth_input, birth_keyboard, LV_EVENT_CLICKED, NULL);
    }
    if (s_birth_input) lv_obj_set_hidden(s_birth_input, !visible);
    esp_lv_adapter_unlock();
}

void pet_face_owner_recording(int sample)
{
    if (!lock_display(-1)) return;
    s_owner_sample = sample >= 1 && sample <= 4 ? sample : 0;
    esp_lv_adapter_unlock();
}

static void owner_later(lv_event_t *event) { pet_setup_cancel(); }

void pet_face_owner_prompt(int sample, const char *phrase)
{
    if (!lock_display(-1)) return;
    if (!s_owner_panel) {
        s_owner_panel = lv_obj_create(lv_screen_active());
        lv_obj_set_size(s_owner_panel, 480, 480); lv_obj_center(s_owner_panel);
        style_panel(s_owner_panel); lv_obj_set_scrollable(s_owner_panel, false);
        s_owner_title = lv_label_create(s_owner_panel);
        lv_label_set_text(s_owner_title, "认识主人的声音"); lv_obj_align(s_owner_title, LV_ALIGN_TOP_MID, 0, 16);
        s_owner_progress = lv_label_create(s_owner_panel);
        lv_obj_set_style_text_color(s_owner_progress, lv_color_hex(0x9fd7c8), 0);
        lv_obj_align(s_owner_progress, LV_ALIGN_TOP_MID, 0, 58);
        lv_obj_t *instructions = lv_label_create(s_owner_panel);
        lv_label_set_text(instructions, "照着下面的句子读，用正常速度读完。\n读完后停约 2 秒，我会自动收句。");
        lv_obj_set_width(instructions, 400); lv_obj_set_style_text_align(instructions, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_align(instructions, LV_ALIGN_TOP_MID, 0, 92);
        s_owner_phrase = lv_label_create(s_owner_panel);
        lv_obj_set_style_text_font(s_owner_phrase, &pet_font_owner_28, 0);
        lv_obj_set_width(s_owner_phrase, 380); lv_label_set_long_mode(s_owner_phrase, LV_LABEL_LONG_WRAP);
        lv_obj_set_style_text_align(s_owner_phrase, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_align(s_owner_phrase, LV_ALIGN_CENTER, 0, -5);
        s_owner_hint = lv_label_create(s_owner_panel); lv_obj_set_width(s_owner_hint, 380);
        lv_obj_set_style_text_align(s_owner_hint, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_align(s_owner_hint, LV_ALIGN_BOTTOM_MID, 0, -78);
        lv_obj_t *later = lv_button_create(s_owner_panel); lv_obj_set_size(later, 156, 44);
        lv_obj_align(later, LV_ALIGN_BOTTOM_MID, 0, -18);
        lv_obj_t *label = lv_label_create(later); lv_label_set_text(label, "稍后再录"); lv_obj_center(label);
        lv_obj_add_event_cb(later, owner_later, LV_EVENT_CLICKED, NULL);
    }
    s_owner_target = sample; s_owner_sample = 0;
    lv_label_set_text(s_owner_phrase, phrase);
#ifdef CONFIG_DESKPET_LOCAL_OWNER
    lv_label_set_text(s_owner_hint, "现在可以读了。声音只在板上核验。");
    lv_label_set_text(s_owner_title, "本地声纹测试 - 认识主人");
#else
    lv_label_set_text(s_owner_hint, "先听提示，播完后再读。");
    lv_label_set_text(s_owner_title, "认识主人的声音");
#endif
    if (sample) lv_label_set_text_fmt(s_owner_progress, "第 %d/4 段", sample);
    else lv_label_set_text(s_owner_progress, "确认主人声音");
    esp_lv_adapter_unlock();
}

void pet_face_owner_end(void)
{
    if (!lock_display(-1)) return;
    if (s_owner_panel) lv_obj_delete_async(s_owner_panel);
    s_owner_panel = s_owner_phrase = s_owner_hint = s_owner_title = s_owner_progress = NULL;
    s_owner_sample = s_owner_target = 0;
    esp_lv_adapter_unlock();
}

static void set_face_text(const char *phase,const char *text)
{
    s_hint_until=0;
    if (phase) {
        pet_utf8_copy(s_requested_phase, sizeof(s_requested_phase), phase);
        if (s_owner_title) lv_label_set_text(s_owner_title, phase);
    }
    refresh_activity();
    if (text) {
        char *copy=pet_strdup(text);if(!copy)return;
        free(s_caption_full);s_caption_full=copy;
        s_caption_at=scene_time();
        lv_label_set_text(s_caption, text);
        lv_point_t measured;lv_text_get_size(&measured,text,&pet_font_cn_16,0,2,212,LV_TEXT_FLAG_NONE);
        int line=pet_font_cn_16.line_height+2;
        s_caption_text_height=measured.y;
        if(s_caption_text_height<line)s_caption_text_height=line;
        lv_obj_set_hidden(lv_obj_get_parent(s_caption), !text[0]);
        position_caption();
        if (s_owner_hint) lv_label_set_text(s_owner_hint, text);
    }
}
void pet_face_set(const char *phase,const char *text)
{
    if(!lock_display(200))return;
    set_face_text(phase,text);bsp_display_unlock();
}
void pet_face_hint(const char *phase,const char *text)
{
    if(!lock_display(200))return;
    set_face_text(phase,text);s_hint_until=scene_time()+5000;bsp_display_unlock();
}

void pet_face_identity(const char *creature)
{
    if (!lock_display(200)) return;
    /* The owner chose the hanfu girl independently of the semantic identity. */
    (void)creature;
    bsp_display_unlock();
}

void pet_face_message(const char *text)
{
    char *copy = pet_strdup(text);
    if (!copy || !lock_display(200)) { free(copy); return; }
    free(s_last_message); s_last_message = copy; bsp_display_unlock();
}

void pet_face_mood(const char *mood)
{
    if (!lock_display(200)) return;
    pet_pose_t pose = !strcmp(mood, "happy") ? PET_POSE_HAPPY :
        !strcmp(mood, "curious") || !strcmp(mood, "concerned") ? PET_POSE_THINK :
        !strcmp(mood, "sleepy") ? PET_POSE_SLEEP : PET_POSE_IDLE;
    pet_scene_react(&s_scene, pose, scene_time());
    if(pose!=PET_POSE_IDLE)pet_home_sync_event("react",pose,0,scene_time());
    bsp_display_unlock();
}

static void voice_signal(int action)
{
    if(!s_voice_panel||s_voice_closing)return;
    s_voice_index=lv_dropdown_get_selected(s_voice_dropdown);s_voice_action=action;
    if(action==PET_VOICE_CLOSE)s_voice_closing=true;
    pet_audio_stop();s_voice_generation=pet_turn_next();xSemaphoreGive(s_voice_done);
}
static void voice_clicked(lv_event_t *event){voice_signal((int)(intptr_t)lv_event_get_user_data(event));}
static void voice_changed(lv_event_t *event)
{
    if(s_voice_closing)return;
    pet_audio_stop();pet_turn_next();
    lv_label_set_text(s_voice_status,"点试听听听效果，满意后保存。");
}
bool pet_face_voice_open(void)
{
    if(!s_voice_done)s_voice_done=xSemaphoreCreateBinary();
    if(!s_voice_done||!lock_display(200))return false;
    if(s_form||s_voice_panel){esp_lv_adapter_unlock();return false;}
    xSemaphoreTake(s_voice_done,0);s_voice_closing=false;
    lv_obj_t *panel=s_voice_panel=lv_obj_create(lv_screen_active());
    lv_obj_set_size(panel,480,480);lv_obj_center(panel);style_panel(panel);lv_obj_set_scrollable(panel,false);
    lv_obj_t *title=lv_label_create(panel);lv_label_set_text(title,"选择我的声音");lv_obj_align(title,LV_ALIGN_TOP_MID,0,24);
    s_voice_current=lv_label_create(panel);lv_label_set_text_fmt(s_voice_current,"正在使用：%s",pet_tts_label(pet_tts_current()));
    lv_obj_align(s_voice_current,LV_ALIGN_TOP_MID,0,60);
    char options[4096]={0};size_t used=0;
    for(int i=0;i<pet_tts_count();i++)used+=snprintf(options+used,sizeof(options)-used,"%s%02d  %s",i?"\n":"",i+1,pet_tts_label(i));
    s_voice_dropdown=lv_dropdown_create(panel);lv_dropdown_set_options(s_voice_dropdown,options);
    lv_dropdown_set_selected(s_voice_dropdown,pet_tts_current());lv_dropdown_set_dir(s_voice_dropdown,LV_DIR_BOTTOM);
    lv_obj_set_width(s_voice_dropdown,390);lv_obj_align(s_voice_dropdown,LV_ALIGN_TOP_MID,0,104);
    lv_obj_set_style_text_font(s_voice_dropdown,&pet_font_cn_16,0);
    lv_obj_t *list=lv_dropdown_get_list(s_voice_dropdown);style_panel(list);lv_obj_set_style_max_height(list,190,0);
    lv_obj_set_style_text_font(list,&pet_font_cn_16,LV_PART_SELECTED);
    lv_obj_set_style_bg_color(list,lv_color_hex(0x355563),LV_PART_SELECTED);
    lv_obj_set_style_text_color(list,lv_color_hex(0xffffff),LV_PART_SELECTED);
    lv_obj_add_event_cb(s_voice_dropdown,voice_changed,LV_EVENT_VALUE_CHANGED,NULL);
    lv_obj_t *hint=lv_label_create(panel);lv_label_set_text_fmt(hint,"%d 种普通话、粤语音色\n试听：我在呀。今天想和你聊些什么呢？",pet_tts_count());
    lv_obj_set_width(hint,390);lv_obj_set_style_text_align(hint,LV_TEXT_ALIGN_CENTER,0);lv_obj_align(hint,LV_ALIGN_TOP_MID,0,224);
    s_voice_status=lv_label_create(panel);lv_label_set_text(s_voice_status,"点试听听听效果，满意后保存。");
    lv_obj_set_width(s_voice_status,390);lv_obj_set_style_text_align(s_voice_status,LV_TEXT_ALIGN_CENTER,0);
    lv_obj_align(s_voice_status,LV_ALIGN_TOP_MID,0,302);
    const char *labels[]={"试听","保存使用","回去"};
    for(int i=0;i<3;i++){
        lv_obj_t *b=lv_button_create(panel);lv_obj_set_size(b,118,48);lv_obj_align(b,LV_ALIGN_BOTTOM_MID,(i-1)*128,-24);
        lv_obj_t *label=lv_label_create(b);lv_label_set_text(label,labels[i]);lv_obj_center(label);
        lv_obj_add_event_cb(b,voice_clicked,LV_EVENT_CLICKED,(void*)(intptr_t)(i+1));
    }
    esp_lv_adapter_unlock();return true;
}
int pet_face_voice_wait(int *index,uint32_t *generation)
{
    xSemaphoreTake(s_voice_done,portMAX_DELAY);
    if(!lock_display(-1))return PET_VOICE_CLOSE;
    int action=s_voice_action;*index=s_voice_index;*generation=s_voice_generation;esp_lv_adapter_unlock();return action;
}
void pet_face_voice_status(const char *status)
{
    if(!lock_display(200))return;
    if(s_voice_panel){
        lv_label_set_text(s_voice_status,status);
        lv_label_set_text_fmt(s_voice_current,"正在使用：%s",pet_tts_label(pet_tts_current()));
    }
    esp_lv_adapter_unlock();
}
void pet_face_voice_close(void)
{
    if(!lock_display(-1))return;
    if(s_voice_panel){lv_obj_set_hidden(s_voice_panel,true);lv_obj_delete_async(s_voice_panel);}
    s_voice_panel=s_voice_dropdown=s_voice_status=s_voice_current=NULL;esp_lv_adapter_unlock();
}

static void submit_form(lv_event_t *event)
{
    bool cancel = lv_event_get_user_data(event) != NULL;
    char choice[256];
    const char *text = "";
    if (!cancel) {
        if (s_form_confirm) text = "确认";
        else if (s_dropdown) { lv_dropdown_get_selected_str(s_dropdown, choice, sizeof(choice)); text = choice; }
        else text = lv_textarea_get_text(s_field);
        if ((!text[0] && !s_form_allow_empty) || strlen(text) >= (size_t)s_form_capacity) return;
        pet_utf8_copy(s_form_out, s_form_capacity, text);
    }
    s_form_result = cancel ? -1 : 0;
    if (s_field) lv_textarea_set_text(s_field, "");
    lv_obj_t *finished = s_form; s_form = s_field = s_dropdown = NULL;
    lv_obj_set_hidden(finished, true); lv_obj_delete_async(finished);
    xSemaphoreGive(s_form_done);
}

static int form(const char *title, const char *hint, bool secret, const char *options, char *out, int capacity)
{
    if (!s_form_done) s_form_done = xSemaphoreCreateBinary();
    if (!s_form_done || !out || capacity < 2 || !lock_display(200)) return -1;
    xSemaphoreTake(s_form_done, 0);
    s_form_out = out; s_form_capacity = capacity; s_form_result = -1;
    s_form_allow_empty = secret; s_form_confirm = false;
    s_form = lv_obj_create(lv_screen_active());
    lv_obj_set_size(s_form, 480, 480); lv_obj_center(s_form);
    style_panel(s_form); lv_obj_set_scrollable(s_form, false);
    lv_obj_t *heading = lv_label_create(s_form);
    lv_label_set_text_fmt(heading, "%s\n%s", title, hint ? hint : "");
    lv_obj_set_width(heading, 430); lv_obj_set_style_text_font(heading, &pet_font_cn_16, 0);
    lv_obj_set_style_text_color(heading, lv_color_hex(0xf6efe4), 0);
    lv_obj_align(heading, LV_ALIGN_TOP_MID, 0, 20);
    if (options) {
        s_dropdown = lv_dropdown_create(s_form); lv_dropdown_set_options(s_dropdown, options);
        lv_obj_set_style_text_font(s_dropdown, &pet_font_cn_16, 0);
        /* The popup lives outside the form and doesn't inherit its CJK font.
         * LVGL also draws its selected row with a separate style part. */
        lv_obj_t *list=lv_dropdown_get_list(s_dropdown);style_panel(list);
        lv_obj_set_style_text_font(list,&pet_font_cn_16,LV_PART_SELECTED);
        lv_obj_set_style_bg_color(list,lv_color_hex(0x355563),LV_PART_SELECTED);
        lv_obj_set_style_text_color(list,lv_color_hex(0xffffff),LV_PART_SELECTED);
        lv_obj_set_style_max_height(list,240,0);
        lv_obj_set_width(s_dropdown, 420); lv_obj_align(s_dropdown, LV_ALIGN_TOP_MID, 0, 100);
    } else {
        s_field = lv_textarea_create(s_form); lv_textarea_set_one_line(s_field, true);
        lv_textarea_set_password_mode(s_field, secret); lv_textarea_set_max_length(s_field, capacity - 1);
        lv_obj_set_width(s_field, 420); lv_obj_align(s_field, LV_ALIGN_TOP_MID, 0, 100);
        lv_obj_t *keyboard = lv_keyboard_create(s_form); lv_keyboard_set_textarea(keyboard, s_field);
        lv_obj_set_size(keyboard, 440, 200); lv_obj_align(keyboard, LV_ALIGN_TOP_MID, 0, 170);
    }
    for (int i = 0; i < 2; i++) {
        lv_obj_t *button = lv_button_create(s_form); lv_obj_set_size(button, 160, 44);
        lv_obj_align(button, LV_ALIGN_BOTTOM_MID, i ? 95 : -95, -10);
        lv_obj_t *label = lv_label_create(button); lv_label_set_text(label, i ? "取消" : "确定");
        lv_obj_set_style_text_font(label, &pet_font_cn_16, 0); lv_obj_center(label);
        lv_obj_add_event_cb(button, submit_form, LV_EVENT_CLICKED, i ? (void *)1 : NULL);
    }
    bsp_display_unlock();
    ESP_LOGI("pet_face", "setup form ready (%s)", options ? "choice" : secret ? "secret" : "text");
    xSemaphoreTake(s_form_done, portMAX_DELAY);
    return s_form_result;
}

int pet_face_input(const char *title, const char *hint, int secret, char *out, int capacity)
{
    return form(title, hint, secret != 0, NULL, out, capacity);
}

int pet_face_choose(const char *title, const char *options, char *out, int capacity)
{
    return form(title, "", false, options, out, capacity);
}

int pet_face_confirm(const char *title, const char *text)
{
    char confirmed[16] = {0};
    if (!s_form_done) s_form_done = xSemaphoreCreateBinary();
    if (!s_form_done || !lock_display(200)) return -1;
    xSemaphoreTake(s_form_done, 0);
    s_form_out = confirmed; s_form_capacity = sizeof(confirmed); s_form_result = -1;
    s_form_confirm = true; s_form_allow_empty = false;
    s_form = lv_obj_create(lv_screen_active()); lv_obj_set_size(s_form, 480, 480); lv_obj_center(s_form);
    style_panel(s_form);
    lv_obj_t *heading = lv_label_create(s_form); lv_label_set_text(heading, title);
    lv_obj_set_style_text_font(heading, &pet_font_cn_16, 0);
    lv_obj_align(heading, LV_ALIGN_TOP_MID, 0, 0);
    lv_obj_t *scroll = lv_obj_create(s_form); lv_obj_set_size(scroll, 430, 310);
    lv_obj_align(scroll, LV_ALIGN_TOP_MID, 0, 40); lv_obj_set_scroll_dir(scroll, LV_DIR_VER);
    lv_obj_t *body = lv_label_create(scroll); lv_label_set_text(body, text); lv_obj_set_width(body, 395);
    lv_obj_set_style_text_font(body, &pet_font_cn_16, 0);
    for (int i = 0; i < 2; i++) {
        lv_obj_t *button = lv_button_create(s_form); lv_obj_set_size(button, 160, 44);
        lv_obj_align(button, LV_ALIGN_BOTTOM_MID, i ? 95 : -95, -10);
        lv_obj_t *label = lv_label_create(button); lv_label_set_text(label, i ? "重来" : "确认");
        lv_obj_set_style_text_font(label, &pet_font_cn_16, 0); lv_obj_center(label);
        lv_obj_add_event_cb(button, submit_form, LV_EVENT_CLICKED, i ? (void *)1 : NULL);
    }
    bsp_display_unlock(); xSemaphoreTake(s_form_done, portMAX_DELAY); return s_form_result;
}

void pet_face_panel_refresh(void)
{
#ifdef CONFIG_DESKPET_PANEL_CACHE
    if(esp_lv_adapter_lock(-1)!=ESP_OK)return;
    pet_panel_bind();s_cat_frame=-1;for(int i=0;i<CAT_CACHE_SLOTS;i++)s_cat_cached_frame[i]=-1;for(int i=0;i<POSE_CACHE_SLOTS;i++)s_cached_pose[i]=PET_ART_COUNT;s_drawn_pose=PET_ART_COUNT;
    lv_obj_invalidate(lv_screen_active());esp_lv_adapter_unlock();
#endif
}

void pet_face_read(const char*text){if(!lock_display(200))return;show_reader(text);bsp_display_unlock();}
