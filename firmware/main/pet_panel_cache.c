#include "pet_panel_cache.h"
#include "pet_util.h"
#include <string.h>
#ifdef ESP_PLATFORM
#include "mbedtls/sha256.h"
#elif defined(__APPLE__)
#include <CommonCrypto/CommonDigest.h>
#else
#include <openssl/sha.h>
#endif
void pet_panel_sha256(const void *p,size_t n,uint8_t out[32]){
#ifdef ESP_PLATFORM
    mbedtls_sha256(p,n,out,0);
#elif defined(__APPLE__)
    CC_SHA256(p,(CC_LONG)n,out);
#else
    SHA256(p,n,out);
#endif
}
static uint32_t u32(const uint8_t*p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static void put(uint8_t*p,uint32_t n){for(int i=0;i<4;i++)p[i]=(uint8_t)(n>>(i*8));}
bool pet_panel_cache_header(const uint8_t*p,size_t cap,uint32_t*kind,uint32_t*bytes,uint32_t*seq){
    if(!p||cap<PET_PANEL_HEADER||memcmp(p,"PXRES01",8)||u32(p+8)!=1||u32(p+56)!=pet_crc32((const char*)p,56))return false;
    uint32_t k=u32(p+12),n=u32(p+16),s=u32(p+20);
    if((k!=1&&k!=2)||!n||n>cap-PET_PANEL_HEADER||!s)return false;
    if(kind)*kind=k;
    if(bytes)*bytes=n;
    if(seq)*seq=s;
    return true;
}
static bool valid_payload(const uint8_t*p,size_t cap){
    uint32_t n;if(!pet_panel_cache_header(p,cap,NULL,&n,NULL))return false;
    uint8_t hash[32];pet_panel_sha256(p+PET_PANEL_HEADER,n,hash);return !memcmp(hash,p+24,32);
}
bool pet_panel_cache_valid(const uint8_t*p,size_t cap,const pet_panel_spec_t*spec){
    uint32_t k,n;if(!spec||!pet_panel_cache_header(p,cap,&k,&n,NULL)||k!=spec->kind||n!=spec->bytes||memcmp(p+24,spec->sha,32))return false;
    return valid_payload(p,cap);
}
int pet_panel_cache_target(const uint8_t*a,size_t an,const uint8_t*b,size_t bn,uint32_t*sequence){
    uint32_t sa=0,sb=0;
    if(valid_payload(a,an))pet_panel_cache_header(a,an,NULL,NULL,&sa);
    if(valid_payload(b,bn))pet_panel_cache_header(b,bn,NULL,NULL,&sb);
    uint32_t latest=sa>sb?sa:sb;if(latest==UINT32_MAX)return -1;
    *sequence=latest+1;return sa>sb?1:0;
}
void pet_panel_cache_commit(uint8_t out[64],const pet_panel_spec_t*spec,uint32_t seq){
    memset(out,0,64);memcpy(out,"PXRES01",8);put(out+8,1);put(out+12,spec->kind);put(out+16,spec->bytes);put(out+20,seq);memcpy(out+24,spec->sha,32);put(out+56,pet_crc32((const char*)out,56));
}
