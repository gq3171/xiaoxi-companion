import unittest
import test_runtime_core as core

class PanelCacheTests(unittest.TestCase):
    def test_actual_hash_commit_corruption_power_loss_and_rollback_selection(self):
        core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "pet_panel_cache.h"
int main(void){
 uint8_t hash[32];pet_panel_sha256("abc",3,hash);assert(hash[0]==0xba&&hash[31]==0xad);
 const unsigned cap=65536;uint8_t*a=malloc(cap),*b=malloc(cap);memset(a,255,cap);memset(b,255,cap);
 pet_panel_spec_t old={.kind=1,.bytes=8193},next=old;
 for(int i=0;i<8193;i++)a[PET_PANEL_HEADER+i]=i%251;
 pet_panel_sha256(a+PET_PANEL_HEADER,old.bytes,old.sha);pet_panel_cache_commit(a,&old,1);
 assert(pet_panel_cache_valid(a,cap,&old));assert(!pet_panel_cache_valid(b,cap,&old));
 uint32_t sequence;assert(pet_panel_cache_target(a,cap,b,cap,&sequence)==1&&sequence==2);
 for(int i=0;i<8193;i++)b[PET_PANEL_HEADER+i]=(i+1)%251;
 pet_panel_sha256(b+PET_PANEL_HEADER,next.bytes,next.sha);
 /* No commit header: a torn download must leave the previous slot usable. */
 assert(!pet_panel_cache_valid(b,cap,&next)&&pet_panel_cache_valid(a,cap,&old));
 uint8_t header[64];pet_panel_cache_commit(header,&next,2);memcpy(b,header,31);
 assert(!pet_panel_cache_valid(b,cap,&next));memcpy(b,header,64);
 assert(pet_panel_cache_valid(b,cap,&next)&&!pet_panel_cache_valid(b,cap,&old));
 assert(pet_panel_cache_target(a,cap,b,cap,&sequence)==0&&sequence==3);
 b[PET_PANEL_HEADER+123]^=1;assert(!pet_panel_cache_valid(b,cap,&next));
 assert(pet_panel_cache_target(a,cap,b,cap,&sequence)==1&&sequence==2);
 b[PET_PANEL_HEADER+123]^=1;b[56]^=1;assert(!pet_panel_cache_valid(b,cap,&next));
 assert(!pet_panel_cache_valid(a,PET_PANEL_HEADER+1,&old));
 assert(!pet_panel_cache_valid(NULL,0,&old));
 pet_panel_cache_commit(a,&old,UINT32_MAX);assert(pet_panel_cache_target(a,cap,b,cap,&sequence)<0);
 free(a);free(b);return 0;}
''',['pet_panel_cache','pet_util'])
