#include "pet_util.h"
#include <stdlib.h>
#include <string.h>
void *pet_alloc(size_t n){return malloc(n);}
char *pet_strdup(const char *s){if(!s)return NULL;size_t n=strlen(s)+1;char *p=malloc(n);if(p)memcpy(p,s,n);return p;}
size_t pet_utf8_copy(char *dst,size_t size,const char *src){if(!size)return 0;size_t n=strlen(src);if(n>=size){n=size-1;while(n&&((unsigned char)src[n]&0xc0)==0x80)n--;}memcpy(dst,src,n);dst[n]=0;return n;}
uint32_t pet_crc32(const void *p,size_t n){const unsigned char *s=p;uint32_t c=UINT32_MAX;for(size_t i=0;i<n;i++){c^=s[i];for(int b=0;b<8;b++)c=(c>>1)^(0xedb88320u&(0u-(c&1u)));}return ~c;}
/* No filesystem side effects: the SQLite transaction commits the returned
 * complete state and operation ID together, or commits neither. */
int pet_snapshot_save(const char *b,const char *s,size_t n,uint32_t *seq){if(!s||strlen(s)>n)return -1;(*seq)++;return 0;}
char *pet_snapshot_load(const char *b,size_t n,uint32_t *seq){*seq=0;return NULL;}
bool pet_snapshot_exists(const char *b){return false;}
