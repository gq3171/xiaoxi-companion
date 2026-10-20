#include "pet_wake_name.h"
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include "pet_name_pinyin.inc"

bool pet_wake_name_build(const char *name,char *phrase,size_t phrase_size,char *pinyin,size_t pinyin_size)
{
    if(!phrase||!phrase_size||!pinyin||!pinyin_size)return false;
    phrase[0]=pinyin[0]=0;
    if(!name)return false;
    const unsigned char *p=(const unsigned char *)name;size_t count=0;
    const char *sounds[4];
    while(*p){
        if(count==4||p[0]<0xe0||p[0]>0xef||!p[1]||(p[1]&0xc0)!=0x80||!p[2]||(p[2]&0xc0)!=0x80)return false;
        unsigned cp=((p[0]&15)<<12)|((p[1]&63)<<6)|(p[2]&63);
        if(cp<0x3400||cp>0x9fff)return false;
        const char *sound=syllables[han_syllable[cp-0x3400]];
        if(!sound[0])return false;
        sounds[count++]=sound;p+=3;
    }
    if(!count)return false;
    size_t bytes=(size_t)(p-(const unsigned char *)name),need=0;
    for(size_t i=0;i<count;i++)need+=strlen(sounds[i]);
    need=need*2+count*2-1;
    if(bytes*2>=phrase_size||need>=pinyin_size||need>63)return false;
    memcpy(phrase,name,bytes);memcpy(phrase+bytes,name,bytes+1);
    size_t used=0;
    for(size_t i=0;i<count*2;i++){
        if(i)pinyin[used++]=' ';
        size_t n=strlen(sounds[i%count]);memcpy(pinyin+used,sounds[i%count],n);used+=n;
    }
    pinyin[used]=0;return true;
}
