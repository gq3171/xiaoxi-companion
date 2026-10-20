#include "pet_input.h"
#include <string.h>
#include <stdint.h>
#include <ctype.h>
static const char *value(const cJSON *o,const char *k)
{
    const cJSON *v=cJSON_GetObjectItemCaseSensitive(o,k);
    return cJSON_IsString(v)?v->valuestring:"";
}
bool pet_input_direct(const cJSON *answer,bool microphone)
{
    if(!cJSON_IsObject(answer))return false;
    const char *action=value(answer,"action");
    if(strcmp(action,"speak") && strcmp(action,"search") && strcmp(action,"list_reminders") && strcmp(action,"cancel_reminder")&&
       strcmp(action,"computer_task")&&strcmp(action,"computer_cancel")&&strcmp(action,"computer_resume"))return false;
    return !microphone || !strcmp(value(answer,"input"),"direct");
}
bool pet_input_remember(const cJSON *answer,bool microphone,bool owner)
{
    return owner && pet_input_direct(answer,microphone) &&
        (!microphone || cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(answer,"remember")));
}

static size_t speech_letters(const char *text,uint32_t *out,size_t capacity)
{
    size_t n=0;const unsigned char *p=(const unsigned char*)text;
    while(*p&&n<capacity){
        uint32_t c=*p++;
        if(c>=0xc2&&c<=0xdf&&p[0]&&((p[0]&0xc0)==0x80)){c=((c&31)<<6)|(p[0]&63);p++;}
        else if(c>=0xe0&&c<=0xef&&p[0]&&p[1]&&((p[0]&0xc0)==0x80)&&((p[1]&0xc0)==0x80)){c=((c&15)<<12)|((p[0]&63)<<6)|(p[1]&63);p+=2;}
        else if(c>=128)continue;
        if((c>=0x3400&&c<=0x9fff)||(c<128&&isalnum((unsigned char)c)))out[n++]=c<128?(uint32_t)tolower((unsigned char)c):c;
    }
    return n;
}
bool pet_input_echo_candidate(const char *candidate,const char *recent_reply)
{
    if(!candidate||!recent_reply)return false;
    /* Explicit questions/corrections/quotation requests may intentionally reuse
     * our words. Short answers never qualify as a transcript echo. */
    const char *intent[]={"刚才","你说","为什么","什么意思","解释","纠正","不是","我说","再说","重复","翻译","吗","呢","?","？"};
    for(size_t i=0;i<sizeof(intent)/sizeof(intent[0]);i++)if(strstr(candidate,intent[i]))return false;
    uint32_t input[384],reply[768];size_t n=speech_letters(candidate,input,384),m=speech_letters(recent_reply,reply,768);
    if(n<12||n>320||m<12)return false;
    size_t matched=0;
    for(size_t i=0;i+1<n;i++)for(size_t j=0;j+1<m;j++)if(input[i]==reply[j]&&input[i+1]==reply[j+1]){matched++;break;}
    return matched*100>=(n-1)*82;
}
