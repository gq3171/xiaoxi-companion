#include "pet_tts.h"
#include "pet_util.h"
#include "cJSON.h"
#include <string.h>
#include <stdlib.h>
#include <stdatomic.h>
#ifdef ESP_PLATFORM
#include "freertos/FreeRTOS.h"
static portMUX_TYPE s_lock=portMUX_INITIALIZER_UNLOCKED;
#define LOCK() portENTER_CRITICAL(&s_lock)
#define UNLOCK() portEXIT_CRITICAL(&s_lock)
#else
#define LOCK() ((void)0)
#define UNLOCK() ((void)0)
#endif
#ifndef PET_STORAGE_ROOT
#define PET_STORAGE_ROOT "/spiffs"
#endif
#define VOICE_BASE PET_STORAGE_ROOT "/tts_voice"
#define VOICE_LIMIT (PET_TTS_MAX_ACK_SAMPLES*4+256)
/* https://platform.minimax.cn/docs/faq/system-voice-id, checked 2026-10-17. */
static const struct { const char *id,*label; } voices[]={
 {"male-qn-qingse","青涩青年"},{"male-qn-jingying","精英青年"},
 {"male-qn-badao","霸道青年"},{"male-qn-daxuesheng","青年大学生"},
 {"female-shaonv","少女音色"},{"female-yujie","御姐音色"},
 {"female-chengshu","成熟女性"},{"female-tianmei","甜美女性"},
 {"male-qn-qingse-jingpin","青涩青年精品"},{"male-qn-jingying-jingpin","精英青年精品"},
 {"male-qn-badao-jingpin","霸道青年精品"},{"male-qn-daxuesheng-jingpin","青年大学生精品"},
 {"female-shaonv-jingpin","少女音色精品"},{"female-yujie-jingpin","御姐音色精品"},
 {"female-chengshu-jingpin","成熟女性精品"},{"female-tianmei-jingpin","甜美女性精品"},
 {"clever_boy","聪明男童"},{"cute_boy","可爱男童"},{"lovely_girl","萌萌女童"},
 {"cartoon_pig","卡通猪小琪"},{"bingjiao_didi","病娇弟弟"},{"junlang_nanyou","俊朗男友"},
 {"chunzhen_xuedi","纯真学弟"},{"lengdan_xiongzhang","冷淡学长"},{"badao_shaoye","霸道少爷"},
 {"tianxin_xiaoling","甜心小玲"},{"qiaopi_mengmei","俏皮萌妹"},{"wumei_yujie","妩媚御姐"},
 {"diadia_xuemei","嗲嗲学妹"},{"danya_xuejie","淡雅学姐"},
 {"Chinese (Mandarin)_Reliable_Executive","沉稳高管"},
 {"Chinese (Mandarin)_News_Anchor","新闻女声"},{"Chinese (Mandarin)_Mature_Woman","傲娇御姐"},
 {"Chinese (Mandarin)_Unrestrained_Young_Man","不羁青年"},{"Arrogant_Miss","嚣张小姐"},
 {"Robot_Armor","机械战甲"},{"Chinese (Mandarin)_Kind-hearted_Antie","热心大婶"},
 {"Chinese (Mandarin)_HK_Flight_Attendant","港普空姐"},{"Chinese (Mandarin)_Humorous_Elder","搞笑大爷"},
 {"Chinese (Mandarin)_Gentleman","温润男声"},{"Chinese (Mandarin)_Warm_Bestie","温暖闺蜜"},
 {"Chinese (Mandarin)_Male_Announcer","播报男声"},{"Chinese (Mandarin)_Sweet_Lady","甜美女声"},
 {"Chinese (Mandarin)_Southern_Young_Man","南方小哥"},{"Chinese (Mandarin)_Wise_Women","阅历姐姐"},
 {"Chinese (Mandarin)_Gentle_Youth","温润青年"},{"Chinese (Mandarin)_Warm_Girl","温暖少女"},
 {"Chinese (Mandarin)_Kind-hearted_Elder","花甲奶奶"},{"Chinese (Mandarin)_Cute_Spirit","憨憨萌兽"},
 {"Chinese (Mandarin)_Radio_Host","电台男主播"},{"Chinese (Mandarin)_Lyrical_Voice","抒情男声"},
 {"Chinese (Mandarin)_Straightforward_Boy","率真弟弟"},{"Chinese (Mandarin)_Sincere_Adult","真诚青年"},
 {"Chinese (Mandarin)_Gentle_Senior","温柔学姐"},{"Chinese (Mandarin)_Stubborn_Friend","嘴硬竹马"},
 {"Chinese (Mandarin)_Crisp_Girl","清脆少女"},{"Chinese (Mandarin)_Pure-hearted_Boy","清澈邻家弟弟"},
 {"Chinese (Mandarin)_Soft_Girl","柔和少女"},{"Cantonese_ProfessionalHost（F)","粤语专业女主持"},
 {"Cantonese_GentleLady","粤语温柔女声"},{"Cantonese_ProfessionalHost（M)","粤语专业男主持"},
 {"Cantonese_PlayfulMan","粤语活泼男声"},{"Cantonese_CuteGirl","粤语可爱女孩"},
 {"Cantonese_KindWoman","粤语善良女声"}
};
static atomic_int s_current=4;
static int16_t *s_ack;
static size_t s_samples;
static uint32_t s_sequence;
int pet_tts_count(void){return sizeof(voices)/sizeof(voices[0]);}
const char *pet_tts_id(int i){return i>=0&&i<pet_tts_count()?voices[i].id:NULL;}
const char *pet_tts_label(int i){return i>=0&&i<pet_tts_count()?voices[i].label:"";}
int pet_tts_find(const char *id){if(id)for(int i=0;i<pet_tts_count();i++)if(!strcmp(id,voices[i].id))return i;return -1;}
int pet_tts_current(void){return atomic_load(&s_current);}
static int nibble(char c){return c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:-1;}
static void apply(int index,int16_t *pcm,size_t samples)
{
    LOCK();int16_t *old=s_ack;s_ack=pcm;s_samples=samples;atomic_store(&s_current,index);UNLOCK();free(old);
}
void pet_tts_start(void)
{
    apply(4,NULL,0);
    char *raw=pet_snapshot_load(VOICE_BASE,VOICE_LIMIT,&s_sequence);
    cJSON *root=raw?cJSON_Parse(raw):NULL;free(raw);
    cJSON *id=cJSON_GetObjectItemCaseSensitive(root,"voice"),*audio=cJSON_GetObjectItemCaseSensitive(root,"pcm");
    int index=cJSON_IsString(id)?pet_tts_find(id->valuestring):-1;
    size_t length=cJSON_IsString(audio)?strlen(audio->valuestring):0;
    if(index>=0&&length>=6400&&length<=PET_TTS_MAX_ACK_SAMPLES*4&&length%4==0){
        int16_t *pcm=pet_alloc(length/2);bool okay=pcm!=NULL;
        for(size_t i=0;okay&&i<length;i+=4){
            int a=nibble(audio->valuestring[i]),b=nibble(audio->valuestring[i+1]);
            int c=nibble(audio->valuestring[i+2]),d=nibble(audio->valuestring[i+3]);
            if(a<0||b<0||c<0||d<0)okay=false;
            else pcm[i/4]=(int16_t)((a<<4)|b|(c<<12)|(d<<8));
        }
        if(okay)apply(index,pcm,length/4);else free(pcm);
    }
    cJSON_Delete(root);
}
int pet_tts_save(int index,const int16_t *pcm,size_t samples)
{
    if(!pet_tts_id(index)||!pcm||samples<1600||samples>PET_TTS_MAX_ACK_SAMPLES)return -1;
    char *hex=pet_alloc(samples*4+1);int16_t *copy=pet_alloc(samples*sizeof(*copy));
    if(!hex||!copy){free(hex);free(copy);return -1;}
    static const char digits[]="0123456789abcdef";
    for(size_t i=0;i<samples;i++){
        unsigned v=(uint16_t)pcm[i];
        hex[i*4]=digits[(v>>4)&15];hex[i*4+1]=digits[v&15];
        hex[i*4+2]=digits[(v>>12)&15];hex[i*4+3]=digits[(v>>8)&15];
    }
    hex[samples*4]=0;memcpy(copy,pcm,samples*sizeof(*copy));
    cJSON *root=cJSON_CreateObject();cJSON_AddStringToObject(root,"voice",pet_tts_id(index));
    cJSON_AddStringToObject(root,"pcm",hex);free(hex);
    char *raw=cJSON_PrintUnformatted(root);cJSON_Delete(root);
    int result=raw?pet_snapshot_save(VOICE_BASE,raw,VOICE_LIMIT,&s_sequence):-1;free(raw);
    if(result==0)apply(index,copy,samples);else free(copy);
    return result;
}
size_t pet_tts_ack_size(void){LOCK();size_t n=s_samples;UNLOCK();return n;}
size_t pet_tts_ack_read(size_t offset,int16_t *out,size_t capacity)
{
    if(!out||capacity>512)return 0;
    LOCK();size_t n=offset<s_samples?s_samples-offset:0;if(n>capacity)n=capacity;
    if(n)memcpy(out,s_ack+offset,n*sizeof(*out));
    UNLOCK();return n;
}
