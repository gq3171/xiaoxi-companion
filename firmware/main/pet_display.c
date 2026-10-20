#include "pet_display.h"
#include <assert.h>
#include <stdatomic.h>
#include "pet_orientation.h"
#include "esp_log.h"
#include "bsp/esp-bsp.h"
#include "bsp/touch.h"
#include "esp_heap_caps.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_io.h"
#include "esp_lv_adapter.h"
#include "freertos/semphr.h"
#include "lvgl.h"
#include "esp_timer.h"
#if LV_DRAW_BUF_STRIDE_ALIGN != 1
#error "The packed SPI flush requires LV_DRAW_BUF_STRIDE_ALIGN=1"
#endif

/* Keep one DMA-capable buffer alive until the LCD has finished consuming it. */
static esp_lcd_panel_handle_t s_panel;
static atomic_uint s_requested_rotation,s_rotation;
static bool s_touch_down;
void pet_display_request_rotation(unsigned degrees)
{
    if(degrees==0||degrees==90||degrees==180||degrees==270)atomic_store(&s_requested_rotation,degrees);
}
unsigned pet_display_rotation(void){return atomic_load(&s_rotation);}
static esp_err_t touch_read(esp_lcd_touch_handle_t touch,esp_lcd_touch_point_data_t *points,uint8_t *count,uint8_t max_count,void *context)
{
    esp_err_t result=esp_lcd_touch_read_data(touch);
    if(result==ESP_OK)result=esp_lcd_touch_get_data(touch,points,count,max_count);
    if(result!=ESP_OK){s_touch_down=false;*count=0;return result;}
    bool pressed_before=s_touch_down;s_touch_down=*count>0;
    for(unsigned i=0;i<*count;i++){
        int x=points[i].x,y=points[i].y;pet_orientation_touch(pet_display_rotation(),480,&x,&y);
        if(!i&&!pressed_before)ESP_LOGI("pet_touch","native=(%u,%u) canvas=(%d,%d) rotation=%u",points[i].x,points[i].y,x,y,pet_display_rotation());
        points[i].x=x;points[i].y=y;
    }
    return result;
}
static void rotate_display(lv_timer_t *timer)
{
    unsigned requested=atomic_load(&s_requested_rotation);
    if(requested==pet_display_rotation()||s_touch_down)return;
    /* flush() waits for every DMA transfer; this callback shares its LVGL
     * thread, so the controller is idle and no pixel buffer is in flight. */
    /* The BSP boots at MADCTL 0xA0 (270), and its touch flags are calibrated
     * to that view. Our public angle is relative to this installed baseline,
     * not the controller's absolute MADCTL angle. */
    unsigned panel_angle=(requested+270)%360;
    bsp_display_rotation_t rotation=panel_angle==90?BSP_DISPLAY_ROTATE_90:panel_angle==180?BSP_DISPLAY_ROTATE_180:panel_angle==270?BSP_DISPLAY_ROTATE_270:BSP_DISPLAY_ROTATE_0;
    if(bsp_display_rotation_set(rotation)!=ESP_OK)return;
    atomic_store(&s_rotation,requested);
    lv_obj_invalidate(lv_screen_active());
    ESP_LOGI("pet_display","auto rotation=%u, touch mapping synchronized",requested);
}
static SemaphoreHandle_t s_transfer_done;
static pet_display_profile_t s_profile;
pet_display_profile_t pet_display_profile(void){return s_profile;}

static bool transfer_done(esp_lcd_panel_io_handle_t io, esp_lcd_panel_io_event_data_t *event, void *context)
{
    BaseType_t wake = pdFALSE;
    xSemaphoreGiveFromISR(s_transfer_done, &wake);
    return wake == pdTRUE;
}

static void flush(lv_display_t *display, const lv_area_t *area, uint8_t *pixels)
{
    int64_t started=esp_timer_get_time();
    /* LV_DRAW_BUF_STRIDE_ALIGN=1: PARTIAL rows are packed to this area's width. */
    lv_draw_sw_rgb565_swap(pixels, lv_area_get_size(area));
    ESP_ERROR_CHECK(esp_lcd_panel_draw_bitmap(s_panel, area->x1, area->y1, area->x2 + 1, area->y2 + 1, pixels));
    assert(xSemaphoreTake(s_transfer_done, pdMS_TO_TICKS(2000)) == pdTRUE);
    s_profile.flushes++;s_profile.pixels+=lv_area_get_size(area);
    s_profile.transfer_us+=esp_timer_get_time()-started;
    if(lv_display_flush_is_last(display))s_profile.frames++;
    lv_display_flush_ready(display);
}

static void round_area(lv_event_t *event)
{
    lv_area_t *area = lv_event_get_param(event);
    area->x1 &= ~1; area->y1 &= ~1;
    area->x2 |= 1; area->y2 |= 1;
}

void pet_display_start(void)
{
    esp_lv_adapter_config_t adapter = ESP_LV_ADAPTER_DEFAULT_CONFIG();
    ESP_ERROR_CHECK(esp_lv_adapter_init(&adapter));
    esp_lcd_panel_io_handle_t io;
    bsp_display_config_t config = {.max_transfer_sz = 480 * 40 * 2};
    ESP_ERROR_CHECK(bsp_display_new(&config, &s_panel, &io));
    ESP_ERROR_CHECK(bsp_display_rotation_set(BSP_DISPLAY_ROTATE_270));
    s_transfer_done = xSemaphoreCreateBinary(); assert(s_transfer_done);
    esp_lcd_panel_io_callbacks_t callbacks = {.on_color_trans_done = transfer_done};
    ESP_ERROR_CHECK(esp_lcd_panel_io_register_event_callbacks(io, &callbacks, NULL));
    void *buffer = heap_caps_malloc(480 * 40 * 2, MALLOC_CAP_INTERNAL | MALLOC_CAP_DMA); assert(buffer);
    lv_display_t *display = lv_display_create(480, 480); assert(display);
    lv_display_set_color_format(display, LV_COLOR_FORMAT_RGB565);
    lv_display_set_buffers(display, buffer, NULL, 480 * 40 * 2, LV_DISPLAY_RENDER_MODE_PARTIAL);
    lv_display_set_flush_cb(display, flush);
    lv_display_add_event_cb(display, round_area, LV_EVENT_INVALIDATE_AREA, NULL);
    bsp_display_cfg_t touch_config = {.touch_flags = {.swap_xy = 1, .mirror_x = 0, .mirror_y = 1}};
    esp_lcd_touch_handle_t touch;
    ESP_ERROR_CHECK(bsp_touch_new(&touch_config, &touch));
    esp_lv_adapter_touch_config_t input = ESP_LV_ADAPTER_TOUCH_DEFAULT_CONFIG(display, touch);
    input.callbacks.custom_touch_read=touch_read;
    assert(esp_lv_adapter_register_touch(&input));
    lv_timer_create(rotate_display,100,NULL);
    ESP_ERROR_CHECK(bsp_display_brightness_set(75));
    ESP_ERROR_CHECK(esp_lv_adapter_start());
}
