#include "pet_media.h"
#include "pet_cloud.h"
#include "pet_face.h"
#include "pet_audio.h"
#include "pet_turn.h"
#include "pet_setup.h"
#include "pet_computer.h"
#include "pet_wake_gate.h"
#include "pet_util.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "esp_jpeg_dec.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mbedtls/base64.h"
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <stdatomic.h>

static cJSON *s_catalog;
static int s_request,s_choice,s_selected=-1;
static unsigned s_index;
static atomic_bool s_playing;
static const char *s_result="尚未播放";
static uint32_t s_generation;
static char s_catalog_job[33];
static const char *text(const cJSON *o,const char *key){const cJSON*v=cJSON_GetObjectItemCaseSensitive(o,key);return cJSON_IsString(v)?v->valuestring:"";}
static int number(const cJSON *o,const char *key){const cJSON*v=cJSON_GetObjectItemCaseSensitive(o,key);return cJSON_IsNumber(v)?v->valueint:0;}
static unsigned char *decode(const char *base64,size_t limit,size_t *size)
{
    *size=0;size_t n=strlen(base64);if(!n||n>(limit+2)/3*4)return NULL;
    unsigned char *bytes=pet_alloc(limit);if(!bytes)return NULL;
    if(mbedtls_base64_decode(bytes,limit,size,(const unsigned char*)base64,n)||!*size||*size>limit){free(bytes);return NULL;}
    return bytes;
}
static bool catalog(void)
{
    cJSON *request=cJSON_CreateObject();
    if(s_catalog_job[0])cJSON_AddStringToObject(request,"job_id",s_catalog_job);
    char *raw=pet_cloud_computer("media_list",request);cJSON_Delete(request);
    cJSON *reply=raw?cJSON_Parse(raw):NULL;free(raw);
    cJSON *items=cJSON_GetObjectItemCaseSensitive(reply,"media");
    bool ok=cJSON_IsTrue(cJSON_GetObjectItem(reply,"ok"))&&cJSON_IsArray(items)&&cJSON_GetArraySize(items)<=4;
    if(ok&&s_catalog_job[0])for(int i=0;i<cJSON_GetArraySize(items);i++)if(strcmp(text(cJSON_GetArrayItem(items,i),"job_id"),s_catalog_job))ok=false;
    if(ok){s_selected=-1;cJSON_Delete(s_catalog);s_catalog=cJSON_Duplicate(items,true);}
    cJSON_Delete(reply);return ok;
}
bool pet_media_active(void){return atomic_load(&s_playing);}
void pet_media_context(char *out,size_t n)
{
    pet_network_state_t network=pet_setup_network_state();
    const cJSON *item=s_selected>=0?cJSON_GetArrayItem(s_catalog,s_selected):NULL;
    if(n)snprintf(out,n,"media_protocol=1；实体屏幕480x480/2.16英寸；媒体预览320x240，视频8帧/秒，音频16kHz单声道；没有外接显示/手机投屏接口。实体按键菜单可打开媒体列表。当前播放器=%s，标题=%s，进度包=%u/%d，实际回执=%s，允许发声=%d，音量=%d，WiFi有IP=%d，信号=%ddBm。图片可看，音视频需明确播放。网络、电池与安静状态见设备上报。文件已准备不等于已播放，回执不证明主人已观看。",
        s_playing?"播放中":"未播放",text(item,"title"),s_index,number(item,"frames"),s_result,pet_audio_output_allowed(),pet_audio_get_volume(),network.connected,network.rssi);
}
void pet_media_command(const char *action,int index,uint32_t generation)
{
    if(!action)return;
    if(!strcmp(action,"show")||!strcmp(action,"play")){s_catalog_job[0]=0;pet_wake_media_begin();s_request=!strcmp(action,"play")?2:1;s_choice=index;s_generation=generation;}
    else if(!strcmp(action,"pause")){s_playing=false;s_result="已暂停";pet_audio_stop();pet_face_media_status("已暂停",false);}
    else if(!strcmp(action,"close")){s_request=0;pet_wake_media_return((uint32_t)(esp_timer_get_time()/1000));s_playing=false;s_result="已关闭";pet_audio_stop();pet_face_media_close();}
}
bool pet_media_present_result(const char *job_id,uint32_t generation){
    if(!job_id||strlen(job_id)!=32||s_request||s_playing)return false;
    for(int i=0;i<32;i++)if(!((job_id[i]>='0'&&job_id[i]<='9')||(job_id[i]>='a'&&job_id[i]<='f')))return false;
    memcpy(s_catalog_job,job_id,33);pet_wake_media_begin();s_request=1;s_choice=1;s_generation=generation;return true;
}
static uint16_t *frame_pixels(const char *encoded)
{
    size_t length;unsigned char *bytes=decode(encoded,60*1024,&length);if(!bytes)return NULL;
    jpeg_dec_config_t config=DEFAULT_JPEG_DEC_CONFIG();config.output_type=JPEG_PIXEL_FORMAT_RGB565_LE;
    jpeg_dec_handle_t decoder=NULL;jpeg_dec_header_info_t info={0};jpeg_dec_io_t io={.inbuf=bytes,.inbuf_len=(int)length};
    bool ok=jpeg_dec_open(&config,&decoder)==JPEG_ERR_OK;
    if(ok)ok=jpeg_dec_parse_header(decoder,&io,&info)==JPEG_ERR_OK&&info.width==320&&info.height==240;
    unsigned char *pixels=ok?jpeg_calloc_align(320*240*2,16):NULL;
    if(ok&&!pixels)ok=false;
    if(ok){io.outbuf=pixels;ok=jpeg_dec_process(decoder,&io)==JPEG_ERR_OK;}
    if(decoder)jpeg_dec_close(decoder);
    free(bytes);
    if(!ok){free(pixels);return NULL;}return (uint16_t*)pixels;
}
bool pet_media_self_test(void)
{
    #include "pet_media_probe.h"
    uint16_t *pixels=frame_pixels(PET_MEDIA_PROBE);
    bool ok=pixels&&(pixels[320*120+160]&0xf800u)>0xc000u&&(pixels[320*120+160]&0x07ffu)<0x200u;
    free(pixels);
    ESP_LOGI("pet_media","JPEG decoder self-test ready=%d",ok);
    if(ok&&pet_setup_connected()){
        cJSON *request=cJSON_CreateObject();pet_cloud_begin_turn(pet_turn_current());
        char *raw=pet_cloud_computer("media_probe",request);cJSON_Delete(request);
        cJSON *reply=raw?cJSON_Parse(raw):NULL;free(raw);
        pixels=cJSON_IsTrue(cJSON_GetObjectItem(reply,"ok"))?frame_pixels(text(reply,"frame")):NULL;
        bool transport=pixels&&(pixels[320*120+160]&0xf800u)>0xc000u&&(pixels[320*120+160]&0x07ffu)<0x200u;
        free(pixels);cJSON_Delete(reply);
        ESP_LOGI("pet_media","JPEG transport self-test ready=%d",transport);
    }
    return ok;
}
static bool packet(const cJSON *item,int64_t due,bool play_audio)
{
    cJSON *request=cJSON_CreateObject();cJSON_AddStringToObject(request,"job_id",text(item,"job_id"));
    cJSON_AddStringToObject(request,"id",text(item,"id"));cJSON_AddNumberToObject(request,"index",s_index);
    pet_cloud_begin_turn(s_generation);char *raw=pet_cloud_computer("media_chunk",request);cJSON_Delete(request);
    cJSON *reply=raw?cJSON_Parse(raw):NULL;free(raw);
    bool ok=pet_turn_valid(s_generation)&&cJSON_IsTrue(cJSON_GetObjectItem(reply,"ok"))&&
        !strcmp(text(reply,"job_id"),text(item,"job_id"))&&!strcmp(text(reply,"id"),text(item,"id"))&&number(reply,"index")== (int)s_index&&
        (cJSON_IsTrue(cJSON_GetObjectItem(reply,"eof"))==(s_index+1==(unsigned)number(item,"frames")))&&
        (!strcmp(text(item,"kind"),"audio")||text(reply,"frame")[0])&&
        (!cJSON_IsTrue(cJSON_GetObjectItem(item,"has_audio"))||text(reply,"audio")[0]);
    uint16_t *pixels=NULL;
    if(ok&&text(reply,"frame")[0]){pixels=frame_pixels(text(reply,"frame"));ok=pixels!=NULL;}
    if(ok&&play_audio&&text(reply,"audio")[0]&&pet_audio_output_allowed()&&pet_audio_get_volume()>0){
        size_t length;unsigned char *pcm=decode(text(reply,"audio"),8000,&length);
        ok=pcm&&!(length%2)&&pet_audio_stream_write((int16_t*)pcm,length/2,s_generation);free(pcm);
    }
    while(ok&&pet_turn_valid(s_generation)&&due>esp_timer_get_time())vTaskDelay(pdMS_TO_TICKS(5));
    ok=ok&&pet_turn_valid(s_generation);
    if(ok&&pixels)ok=pet_face_media_frame(pixels,320,240);
    free(pixels);
    if(ok){
        if(!s_index&&pet_computer_media_presented(text(item,"job_id")))pet_face_result_pending(false);
        s_index++;
    }
    bool end=ok&&cJSON_IsTrue(cJSON_GetObjectItem(reply,"eof"));cJSON_Delete(reply);
    if(end)s_playing=false;
    return ok;
}
void pet_media_tick(uint32_t generation)
{
    int control=pet_face_media_control();
    if(control==3){pet_media_command("close",0,generation);return;}
    if(control==4){s_catalog_job[0]=0;s_request=1;s_choice=0;s_generation=generation;}
    if(control==2){pet_media_command("pause",0,generation);return;}
    if(control==1&&s_selected>=0){s_playing=true;s_generation=generation;}
    if(s_request){
        int mode=s_request;s_request=0;
        if(!pet_turn_valid(s_generation))return;
        pet_cloud_begin_turn(s_generation);
        if(!catalog()||!cJSON_GetArraySize(s_catalog)){pet_face_set("媒体结果","还没有可查看的媒体文件，或小主机暂时没有连接。");return;}
        if(!pet_turn_valid(s_generation))return;
        int count=cJSON_GetArraySize(s_catalog),chosen=s_choice-1;
        if(s_catalog_job[0]){
            chosen=-1;
            for(int i=0;i<count;i++){
                const char *kind=text(cJSON_GetArrayItem(s_catalog,i),"kind");
                if(!strcmp(kind,"image")||!strcmp(kind,"video")){chosen=i;break;}
            }
            if(chosen<0)return;
        }
        if(chosen<0||chosen>=count){
            if(mode==2&&count==1)chosen=0;
            else{
                char options[768]={0};
                for(int i=0;i<count;i++){char line[160];cJSON *item=cJSON_GetArrayItem(s_catalog,i);snprintf(line,sizeof(line),"%d. %s%s",i+1,text(item,"title"),i+1<count?"\n":"");strncat(options,line,sizeof(options)-strlen(options)-1);}
                char answer[160];if(pet_face_choose("媒体结果",options,answer,sizeof(answer))){pet_wake_media_return((uint32_t)(esp_timer_get_time()/1000));return;}
                chosen=atoi(answer)-1;if(chosen<0||chosen>=count)return;
            }
        }
        if(!pet_turn_valid(s_generation))return;
        s_selected=chosen;s_index=0;s_generation=pet_turn_current();
        cJSON *item=cJSON_GetArrayItem(s_catalog,s_selected);
        bool image=!strcmp(text(item,"kind"),"image");
        pet_face_media_open(text(item,"title"),!image);s_playing=image||mode==2;
        if(!s_playing){
            if(!strcmp(text(item,"kind"),"video")){packet(item,0,false);s_index=0;}
            pet_face_media_status("点播放开始",false);
        }
    }
    if(!s_playing||s_selected<0)return;
    cJSON *item=cJSON_GetArrayItem(s_catalog,s_selected);
    bool image=!strcmp(text(item,"kind"),"image"),audio=cJSON_IsTrue(cJSON_GetObjectItem(item,"has_audio"));
    int fps=number(item,"fps"),count=number(item,"frames");
    if(count<1||count>14401||(!image&&fps!=4&&fps!=8)){s_playing=false;pet_face_media_status("媒体格式暂不支持",false);return;}
    if(s_index>=(unsigned)count)s_index=0;
    bool audible=audio&&pet_audio_output_allowed()&&pet_audio_get_volume()>0;
    if(!strcmp(text(item,"kind"),"audio")&&!audible){s_playing=false;s_result="静音未播放";pet_face_media_status("当前静音，调高音量后播放",false);return;}
    if(audible&&!pet_audio_stream_begin_media(s_generation)){s_playing=false;pet_face_media_status("声音暂时不可用",false);return;}
    s_result=image?"正在展示":audible?"播放中":"静音播放中";
    pet_face_media_status(image?"图片":s_result,!image);
    int64_t started=esp_timer_get_time()-(int64_t)s_index*1000000/(fps?fps:1);
    bool complete=false,failed=false,first=true;
    while(s_playing&&pet_turn_valid(s_generation)){
        int control=pet_face_media_control();
        if(control){
            s_playing=false;
            if(control==3)pet_face_media_close();
            else if(control==4){pet_face_media_close();s_catalog_job[0]=0;s_request=1;s_choice=0;s_generation=pet_turn_current();}
            else pet_face_media_status("已暂停",false);
            break;
        }
        int64_t due=!image&&strcmp(text(item,"kind"),"audio")?started+(int64_t)s_index*1000000/fps:0;
        bool now_audible=audio&&pet_audio_output_allowed()&&pet_audio_get_volume()>0;
        if(now_audible!=audible){
            if(audible)pet_audio_stream_end(false);
            if(!strcmp(text(item,"kind"),"audio")&&!now_audible){audible=false;s_result="静音暂停";s_playing=false;break;}
            if(now_audible&&!pet_audio_stream_begin_media(s_generation)){failed=true;s_playing=false;break;}
            audible=now_audible;
        }
        if(!packet(item,first?0:due,audible)){failed=pet_turn_valid(s_generation);s_playing=false;break;}
        if(first){first=false;started=esp_timer_get_time()-(int64_t)(s_index-1)*1000000/(fps?fps:1);}
        if(!s_playing){complete=true;break;}
        if(image){s_playing=false;complete=true;break;}
    }
    if(audible){pet_audio_stream_end(complete);if(complete&&!pet_audio_stream_ok()){complete=false;failed=pet_turn_valid(s_generation);}}
    if(complete){s_result=image?"图片已展示":audio&&!audible?"静音预览结束":"播放完毕";pet_face_media_status(s_result,false);}
    else if(failed){s_result="连接中断，未完成";pet_face_media_status("连接中断，点播放可从此处继续",false);}
    else if(pet_turn_valid(s_generation)){s_result="已暂停";pet_face_media_status("已暂停",false);}
    else if(!pet_turn_valid(s_generation)){
        s_result="交互打断，未完成";
        int control=pet_face_media_control();
        if(control==2)pet_face_media_status("已暂停",false);
        else{pet_face_media_close();if(control==4){s_catalog_job[0]=0;s_request=1;s_choice=0;s_generation=pet_turn_current();}}
    }
    s_playing=false;
}
