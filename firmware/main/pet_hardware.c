#include "pet_hardware.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <time.h>
#include "bsp/esp-bsp.h"
#include "driver/i2c_master.h"
#include "esp_log.h"
#include "esp_sntp.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "pet_runtime.h"
#include "pet_motion.h"
#include "pet_orientation.h"
#include "pet_display.h"

static i2c_master_dev_handle_t s_pmu, s_rtc, s_imu;
static pet_hardware_state_t s_state = {.battery_percent = -1};
static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
static const char *TAG = "pet_hardware";

static esp_err_t read_device(i2c_master_dev_handle_t dev, uint8_t reg, uint8_t *data, size_t n)
{
    return dev ? i2c_master_transmit_receive(dev, &reg, 1, data, n, 50) : ESP_ERR_INVALID_STATE;
}

static esp_err_t write_device(i2c_master_dev_handle_t dev, uint8_t reg, uint8_t value)
{
    uint8_t bytes[] = {reg, value};
    return dev ? i2c_master_transmit(dev, bytes, 2, 50) : ESP_ERR_INVALID_STATE;
}

static void add_device(uint8_t address, i2c_master_dev_handle_t *device)
{
    i2c_device_config_t config = {.dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = address, .scl_speed_hz = 100000};
    if (i2c_master_probe(bsp_i2c_get_handle(), address, 50) == ESP_OK) {
        i2c_master_bus_add_device(bsp_i2c_get_handle(), &config, device);
    }
}

static int unbcd(uint8_t value) { return (value >> 4) * 10 + (value & 15); }
static uint8_t bcd(int value) { return ((value / 10) << 4) | (value % 10); }

static bool clock_valid(void)
{
    time_t now = time(NULL);
    return now >= 1735689600 && now < 4102444800LL;
}

static void restore_rtc(void)
{
    uint8_t data[7];
    if (read_device(s_rtc, 0x04, data, 7) != ESP_OK || (data[0] & 0x80)) return;
    struct tm local = {
        .tm_sec = unbcd(data[0] & 0x7f), .tm_min = unbcd(data[1] & 0x7f),
        .tm_hour = unbcd(data[2] & 0x3f), .tm_mday = unbcd(data[3] & 0x3f),
        .tm_mon = unbcd(data[5] & 0x1f) - 1, .tm_year = unbcd(data[6]) + 100, .tm_isdst = -1,
    };
    if (local.tm_sec > 59 || local.tm_min > 59 || local.tm_hour > 23 || local.tm_mday < 1 || local.tm_mday > 31 ||
        local.tm_mon < 0 || local.tm_mon > 11 || local.tm_year < 125) return;
    time_t epoch = mktime(&local);
    if (epoch < 1735689600) return;
    struct timeval tv = {.tv_sec = epoch};
    settimeofday(&tv, NULL);
}

static void synced(struct timeval *tv)
{
    if (!s_rtc) return;
    struct tm local;
    localtime_r(&tv->tv_sec, &local);
    uint8_t bytes[] = {0x04, bcd(local.tm_sec), bcd(local.tm_min), bcd(local.tm_hour),
        bcd(local.tm_mday), bcd(local.tm_wday), bcd(local.tm_mon + 1), bcd(local.tm_year - 100)};
    /* PCF85063A: clear STOP only, then write a coherent calendar including OS=0. */
    uint8_t control;
    if (read_device(s_rtc, 0x00, &control, 1) == ESP_OK) write_device(s_rtc, 0x00, control & ~0x22);
    if (i2c_master_transmit(s_rtc, bytes, sizeof(bytes), 100) != ESP_OK) ESP_LOGW(TAG, "RTC sync failed");
}

void pet_hardware_network_ready(void)
{
    static bool started;
    if (started) return;
    esp_sntp_setoperatingmode(SNTP_OPMODE_POLL);
    esp_sntp_setservername(0, "ntp.aliyun.com");
    esp_sntp_setservername(1, "pool.ntp.org");
    esp_sntp_set_time_sync_notification_cb(synced);
    esp_sntp_init();
    started = true;
}

pet_hardware_state_t pet_hardware_state(void)
{
    portENTER_CRITICAL(&s_lock);
    pet_hardware_state_t state = s_state;
    portEXIT_CRITICAL(&s_lock);
    state.clock_valid = clock_valid();
    return state;
}

int pet_hardware_local_minute(void)
{
    if (!clock_valid()) return -1;
    time_t now = time(NULL);
    struct tm local; localtime_r(&now, &local);
    return local.tm_hour * 60 + local.tm_min;
}

void pet_hardware_description(char *out, size_t capacity)
{
    pet_hardware_state_t state = pet_hardware_state();
    char clock[48] = "时间未校准";
    if (state.clock_valid) { time_t now = time(NULL); struct tm local; localtime_r(&now, &local); strftime(clock, sizeof(clock), "%Y-%m-%d %H:%M:%S 北京时间", &local); }
    snprintf(out, capacity, "%s；电量=%d%%；电压=%dmV；USB=%s；移动=%s；惯性检测=%s；角速度约%d度/秒（只表示设备运动，不证明谁拿着或主人是否在场）；屏幕自动朝向=%u度", clock, state.battery_percent,
             state.battery_mv, state.usb_power ? "有" : "无", state.moving ? "是" : "否",state.imu_ready?"就绪":"未就绪",state.rotation_dps,pet_display_rotation());
}

static void sensors(void *arg)
{
    pet_motion_t motion={0};pet_orientation_t orientation={0};
    bool low_announced = false;
    bool usb_before = false;
    int loops = 0;
    while (true) {
        pet_hardware_state_t next = pet_hardware_state();
        if (s_imu) {
            uint8_t raw[12],status;
            if (read_device(s_imu,0x2e,&status,1)==ESP_OK && (status&3)==3 && read_device(s_imu, 0x35, raw, 12) == ESP_OK) {
                float vector[3],gyro[3];
                for (int i = 0; i < 3; i++) {
                    vector[i] = (int16_t)(raw[i * 2] | (raw[i * 2 + 1] << 8)) / 4096.0f;
                    gyro[i]=(int16_t)(raw[6+i*2]|raw[7+i*2]<<8)/64.0f; /* +/-512dps */
                }
                unsigned event=pet_motion_step(&motion,vector,gyro,(uint32_t)(esp_timer_get_time()/1000));
                /* Mount transform is fixed, never inferred from a random boot pose.
                 * QMI coordinate signs are logged on readiness for physical QA. */
                float screen_gravity[3];pet_orientation_from_qmi(vector,screen_gravity);
                event|=pet_orientation_step(&orientation,screen_gravity,gyro,(uint32_t)(esp_timer_get_time()/1000));
                pet_display_request_rotation(orientation.rotation);
                if(motion.ready&&!next.imu_ready)ESP_LOGI(TAG,"orientation mount sample ax=%.3f ay=%.3f az=%.3f",(double)vector[0],(double)vector[1],(double)vector[2]);
                if(motion.ready&&!next.imu_ready)ESP_LOGI(TAG,"QMI8658 fresh accel+gyro samples calibrated");
                next.imu_ready=motion.ready;next.moving=motion.moving;
                float lean_x=orientation.gravity[0],lean_y=orientation.gravity[1];
                pet_orientation_vector(pet_display_rotation(),&lean_x,&lean_y);
                next.tilt_x=orientation.initialized?(int)lroundf(lean_x*7):0;
                next.tilt_y=motion.tilt_y;next.rotation_dps=motion.rotation_dps;
                if(event){
                    next.motion_sequence++;next.motion_event=event;
                    if(event&(PET_MOTION_TILTED|PET_MOTION_TURNED|PET_MOTION_SHAKEN))pet_runtime_notify("惯性交互惊讶");
                    if(event&PET_MOTION_SHAKEN)pet_runtime_notify("设备被连续摇动，可以用表情回应；不必每次出声");
                    else if(event&PET_MOTION_MOVED)pet_runtime_notify("设备正在被拿起或移动，不知道是谁拿着");
                    else if(event&PET_MOTION_SETTLED)pet_runtime_notify("设备已经放稳或保持不动，不等于确认放回桌面");
                    ESP_LOGI(TAG,"motion event=%u rotation_dps=%d accel=(%.3f,%.3f,%.3f) display=%u",event,next.rotation_dps,(double)vector[0],(double)vector[1],(double)vector[2],pet_display_rotation());
                }
            }else if(motion.have_time&&(uint32_t)(esp_timer_get_time()/1000)-motion.last_ms>1000){
                next.imu_ready=false;next.moving=false;next.tilt_x=next.tilt_y=next.rotation_dps=0;
            }
        }
        if (s_pmu && loops++ % 100 == 0) {
            uint8_t status, percent, voltage[2];
            if (read_device(s_pmu, 0x00, &status, 1) == ESP_OK) {
                next.usb_power = (status & 0x20) != 0;
                next.battery_percent = -1; next.battery_mv = 0;
                if ((status & 0x08) && read_device(s_pmu, 0xa4, &percent, 1) == ESP_OK && percent <= 100) next.battery_percent = percent;
                if ((status & 0x08) && read_device(s_pmu, 0x34, voltage, 2) == ESP_OK) next.battery_mv = ((voltage[0] & 0x1f) << 8) | voltage[1];
                if (next.usb_power != usb_before) pet_runtime_notify(next.usb_power ? "接上电源" : "拔下电源");
                usb_before = next.usb_power;
                if (next.battery_percent >= 0 && next.battery_percent <= 15 && !next.usb_power && !low_announced) {
                    low_announced = true; pet_runtime_notify("电量低，需要充电");
                }
                if (next.battery_percent > 25 || next.usb_power) low_announced = false;
            }
        }
        portENTER_CRITICAL(&s_lock); s_state = next; portEXIT_CRITICAL(&s_lock);
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

void pet_hardware_start(void)
{
    setenv("TZ", "CST-8", 1); tzset();
    bsp_i2c_init();
    add_device(0x34, &s_pmu); add_device(0x51, &s_rtc); add_device(0x6b, &s_imu);
    restore_rtc();
    if (s_pmu) {
        uint8_t id, adc;
        if (read_device(s_pmu, 0x03, &id, 1) != ESP_OK || id != 0x4a) s_pmu = NULL;
        else if (read_device(s_pmu, 0x30, &adc, 1) == ESP_OK) write_device(s_pmu, 0x30, adc | 1);
    }
    if (s_imu) {
        uint8_t id;
        if (read_device(s_imu, 0x00, &id, 1) != ESP_OK || id != 0x05) s_imu = NULL;
        else {
            /* QMI8658A/C: auto increment, +/-8g, +/-512dps, ODR encoding 6. */
            bool okay=write_device(s_imu,0x08,0)==ESP_OK&&write_device(s_imu,0x02,0x40)==ESP_OK&&
                write_device(s_imu,0x03,0x26)==ESP_OK&&write_device(s_imu,0x04,0x56)==ESP_OK&&write_device(s_imu,0x08,3)==ESP_OK;
            uint8_t enabled=0;
            if(!okay||read_device(s_imu,0x08,&enabled,1)!=ESP_OK||(enabled&3)!=3)s_imu=NULL;
            else ESP_LOGI(TAG,"QMI8658 accelerometer and gyro enabled, 20Hz host sampling");
        }
    }
    xTaskCreate(sensors, "pet_sensors", 4096, NULL, 3, NULL);
}
