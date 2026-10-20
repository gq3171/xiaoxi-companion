"""Check real LCD flush ownership, rectangles and byte order with a fake DMA ISR."""
import unittest
import test_runtime_core

SDK = r'''
#pragma once
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#define ESP_OK 0
#define ESP_LOGI(...) ((void)0)
typedef int esp_err_t;
#define ESP_ERROR_CHECK(x) assert((x) == 0)
#define pdFALSE 0
#define pdTRUE 1
#define pdMS_TO_TICKS(x) (x)
#define MALLOC_CAP_INTERNAL 1
#define MALLOC_CAP_DMA 2
#define LV_COLOR_FORMAT_RGB565 0
#define LV_DRAW_BUF_STRIDE_ALIGN 1
#define LV_DISPLAY_RENDER_MODE_PARTIAL 0
#define LV_EVENT_INVALIDATE_AREA 0
typedef int BaseType_t;
typedef void *SemaphoreHandle_t;
typedef void *esp_lcd_panel_handle_t;
typedef void *esp_lcd_panel_io_handle_t;
typedef void *esp_lcd_touch_handle_t;
typedef struct { int unused; } esp_lcd_panel_io_event_data_t;
typedef struct { int unused; } lv_display_t;
typedef struct { int unused; } lv_timer_t;
typedef struct { int unused; } lv_obj_t;
typedef enum {BSP_DISPLAY_ROTATE_0,BSP_DISPLAY_ROTATE_90,BSP_DISPLAY_ROTATE_180,BSP_DISPLAY_ROTATE_270} bsp_display_rotation_t;
typedef struct {int x,y;} esp_lcd_touch_point_data_t;
int bsp_display_rotation_set(bsp_display_rotation_t);
int esp_lcd_touch_read_data(esp_lcd_touch_handle_t);
int esp_lcd_touch_get_data(esp_lcd_touch_handle_t,esp_lcd_touch_point_data_t*,uint8_t*,uint8_t);
lv_timer_t *lv_timer_create(void (*cb)(lv_timer_t*),uint32_t,void*);
lv_obj_t *lv_screen_active(void);
void lv_obj_invalidate(lv_obj_t*);
typedef struct { int x1,y1,x2,y2; } lv_area_t;
typedef struct { void *param; } lv_event_t;
typedef struct { int unused; } esp_lv_adapter_config_t;
#define ESP_LV_ADAPTER_DEFAULT_CONFIG() {0}
typedef struct { int max_transfer_sz; } bsp_display_config_t;
typedef struct { struct { int swap_xy,mirror_x,mirror_y; } touch_flags; } bsp_display_cfg_t;
typedef struct { lv_display_t *disp; void *touch; struct{int (*custom_touch_read)(void*,esp_lcd_touch_point_data_t*,uint8_t*,uint8_t,void*);}callbacks; } esp_lv_adapter_touch_config_t;
#define ESP_LV_ADAPTER_TOUCH_DEFAULT_CONFIG(d,t) {d,t}
typedef struct { bool (*on_color_trans_done)(esp_lcd_panel_io_handle_t,esp_lcd_panel_io_event_data_t *,void *); } esp_lcd_panel_io_callbacks_t;
SemaphoreHandle_t xSemaphoreCreateBinary(void);
int xSemaphoreGiveFromISR(SemaphoreHandle_t, BaseType_t *);
int xSemaphoreTake(SemaphoreHandle_t, int);
void *heap_caps_malloc(size_t, unsigned);
int esp_lv_adapter_init(const esp_lv_adapter_config_t *);
int esp_lv_adapter_start(void);
int bsp_display_new(const bsp_display_config_t *,esp_lcd_panel_handle_t *,esp_lcd_panel_io_handle_t *);
int esp_lcd_panel_io_register_event_callbacks(esp_lcd_panel_io_handle_t,const esp_lcd_panel_io_callbacks_t *,void *);
int esp_lcd_panel_draw_bitmap(esp_lcd_panel_handle_t,int,int,int,int,const void *);
int bsp_touch_new(const bsp_display_cfg_t *,esp_lcd_touch_handle_t *);
int bsp_display_brightness_set(int);
void *esp_lv_adapter_register_touch(const esp_lv_adapter_touch_config_t *);
lv_display_t *lv_display_create(int,int);
void lv_display_set_color_format(lv_display_t *,int);
void lv_display_set_buffers(lv_display_t *,void *,void *,size_t,int);
void lv_display_set_flush_cb(lv_display_t *,void (*)(lv_display_t *,const lv_area_t *,uint8_t *));
void lv_display_add_event_cb(lv_display_t *,void (*)(lv_event_t *),int,void *);
void lv_draw_sw_rgb565_swap(void *,uint32_t);
void lv_display_flush_ready(lv_display_t *);
bool lv_display_flush_is_last(lv_display_t *);
int64_t esp_timer_get_time(void);
void *lv_event_get_param(lv_event_t *);
static inline unsigned lv_area_get_size(const lv_area_t *a) {return (a->x2-a->x1+1)*(a->y2-a->y1+1);}
'''

CODE = r'''
#include <stdlib.h>
#include <string.h>
#include "pet_display.c"
static lv_display_t disp;
static lv_timer_t timer;
static lv_obj_t screen;
static int invalidated,panel_result,panel_rotation,point_count;
int bsp_display_rotation_set(bsp_display_rotation_t r){panel_rotation=r;return panel_result;}
int esp_lcd_touch_read_data(void*t){return 0;}
int esp_lcd_touch_get_data(void*t,esp_lcd_touch_point_data_t*p,uint8_t*n,uint8_t max){*n=point_count;if(*n)p[0]=(esp_lcd_touch_point_data_t){100,200};return 0;}
lv_timer_t *lv_timer_create(void(*cb)(lv_timer_t*),uint32_t period,void*u){assert(cb==rotate_display&&period==100);return &timer;}
lv_obj_t *lv_screen_active(void){return &screen;}
void lv_obj_invalidate(lv_obj_t*o){assert(o==&screen);invalidated++;}
int64_t esp_timer_get_time(void){static int64_t t;return ++t;}
bool lv_display_flush_is_last(lv_display_t *d){return true;}
static bool done, consumed;
static int ready;
static lv_area_t rectangle;
static esp_lcd_panel_io_callbacks_t callbacks;
SemaphoreHandle_t xSemaphoreCreateBinary(void) {return (void *)1;}
int xSemaphoreGiveFromISR(SemaphoreHandle_t s,BaseType_t *w) {done=true;return 1;}
int xSemaphoreTake(SemaphoreHandle_t s,int timeout) {assert(done);done=false;consumed=true;return 1;}
void *heap_caps_malloc(size_t n,unsigned caps) {assert(n==38400 && caps==(MALLOC_CAP_INTERNAL|MALLOC_CAP_DMA));return malloc(n);}
int esp_lv_adapter_init(const esp_lv_adapter_config_t *c) {return 0;}
int esp_lv_adapter_start(void) {return 0;}
int bsp_display_new(const bsp_display_config_t *c,void **panel,void **io) {assert(c->max_transfer_sz==38400);*panel=(void *)1;*io=(void *)2;return 0;}
int esp_lcd_panel_io_register_event_callbacks(void *io,const esp_lcd_panel_io_callbacks_t *c,void *u) {callbacks=*c;return 0;}
int bsp_touch_new(const bsp_display_cfg_t *c,void **t) {assert(c->touch_flags.swap_xy==1 && c->touch_flags.mirror_y==1);*t=(void *)3;return 0;}
int bsp_display_brightness_set(int n) {assert(n==75);return 0;}
void *esp_lv_adapter_register_touch(const esp_lv_adapter_touch_config_t *c) {assert(c->disp==&disp&&c->callbacks.custom_touch_read==touch_read);return (void *)1;}
lv_display_t *lv_display_create(int x,int y) {assert(x==480 && y==480);return &disp;}
void lv_display_set_color_format(lv_display_t *d,int c) {}
void lv_display_set_buffers(lv_display_t *d,void *a,void *b,size_t n,int mode) {assert(a && !b && n==38400);}
void lv_display_set_flush_cb(lv_display_t *d,void (*cb)(lv_display_t *,const lv_area_t *,uint8_t *)) {assert(cb==flush);}
void lv_display_add_event_cb(lv_display_t *d,void (*cb)(lv_event_t *),int event,void *u) {assert(cb==round_area);}
void *lv_event_get_param(lv_event_t *e) {return e->param;}
void lv_draw_sw_rgb565_swap(void *p,uint32_t n) {uint8_t *b=p;for(unsigned i=0;i<n;i++){uint8_t t=b[2*i];b[2*i]=b[2*i+1];b[2*i+1]=t;}}
int esp_lcd_panel_draw_bitmap(void *p,int x,int y,int endx,int endy,const void *pixels) {
    assert(x==rectangle.x1 && y==rectangle.y1 && endx==rectangle.x2+1 && endy==rectangle.y2+1);
    assert(!done && !consumed);const uint8_t *b=pixels;
    for(unsigned i=0;i<lv_area_get_size(&rectangle);i++) {assert(b[2*i]==(uint8_t)(i+1) && b[2*i+1]==(uint8_t)i);}
    assert(ready==0);callbacks.on_color_trans_done((void *)2,NULL,NULL);return 0;
}
void lv_display_flush_ready(lv_display_t *d) {assert(consumed && !done);ready++;}
int main(void) {
    pet_display_start();assert(panel_rotation==BSP_DISPLAY_ROTATE_270&&pet_display_rotation()==0);
    lv_area_t regions[]={{13,41,18,44},{0,0,479,39},{478,478,479,479}};
    for(unsigned k=0;k<3;k++) {
        rectangle=regions[k];size_t n=lv_area_get_size(&rectangle);uint8_t *b=malloc(n*2+16);
        for(unsigned i=0;i<n;i++){b[2*i]=(uint8_t)i;b[2*i+1]=(uint8_t)(i+1);}memset(b+n*2,0xa5,16);
        ready=0;consumed=false;flush(&disp,&rectangle,b);assert(ready==1);
        for(unsigned i=0;i<16;i++)assert(b[n*2+i]==0xa5);free(b);
    }
    lv_area_t a={1,3,478,478};lv_event_t e={&a};round_area(&e);
    assert(a.x1==0 && a.y1==2 && a.x2==479 && a.y2==479);
    esp_lcd_touch_point_data_t p;uint8_t count;
    point_count=1;touch_read((void*)3,&p,&count,1,NULL);assert(p.x==100&&p.y==200);
    pet_display_request_rotation(90);rotate_display(&timer);assert(pet_display_rotation()==0&&!invalidated);
    point_count=0;touch_read((void*)3,&p,&count,1,NULL);rotate_display(&timer);
    assert(pet_display_rotation()==90&&panel_rotation==BSP_DISPLAY_ROTATE_0&&invalidated==1);
    point_count=1;touch_read((void*)3,&p,&count,1,NULL);assert(p.x==200&&p.y==379);
    point_count=0;touch_read((void*)3,&p,&count,1,NULL);
    panel_result=-1;pet_display_request_rotation(180);rotate_display(&timer);assert(pet_display_rotation()==90&&invalidated==1);
    panel_result=0;rotate_display(&timer);assert(pet_display_rotation()==180&&panel_rotation==BSP_DISPLAY_ROTATE_90&&invalidated==2);
    pet_display_request_rotation(42);rotate_display(&timer);assert(pet_display_rotation()==180&&panel_rotation==BSP_DISPLAY_ROTATE_90&&invalidated==2);
    pet_display_request_rotation(270);rotate_display(&timer);point_count=1;touch_read((void*)3,&p,&count,1,NULL);assert(p.x==279&&p.y==100&&panel_rotation==BSP_DISPLAY_ROTATE_180);
    point_count=0;touch_read((void*)3,&p,&count,1,NULL);pet_display_request_rotation(0);rotate_display(&timer);
    assert(panel_rotation==BSP_DISPLAY_ROTATE_270&&pet_display_rotation()==0);
    point_count=1;touch_read((void*)3,&p,&count,1,NULL);assert(p.x==100&&p.y==200);
    return 0;
}
'''


class DisplayHostTests(unittest.TestCase):
    def test_small_rectangles_dma_lifetime_and_full_width_byte_order(self):
        headers = {"display_test_sdk.h": SDK}
        for name in ("esp_timer.h", "bsp/esp-bsp.h", "bsp/touch.h", "esp_heap_caps.h", "esp_lcd_panel_ops.h",
                     "esp_lcd_panel_io.h", "esp_lv_adapter.h", "freertos/semphr.h", "lvgl.h", "esp_log.h"):
            headers[name] = '#include "display_test_sdk.h"\n'
        test_runtime_core.RuntimeCoreTests.run_c(self, CODE, ["pet_orientation"], headers)
