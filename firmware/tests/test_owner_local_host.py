"""Exercise real local enrollment/persistence code; NN is a controlled fixture.

These tests establish protocol behavior, not biometric recognition accuracy.
"""
from pathlib import Path
import unittest
import test_runtime_core

SDK = r'''
#pragma once
#include <openssl/evp.h>
#include <stdlib.h>
#include <string.h>
static inline int mbedtls_base64_encode(unsigned char *o,size_t cap,size_t *n,const unsigned char *p,size_t z) {
 if(cap < 4*((z+2)/3)+1)return -1;int v=EVP_EncodeBlock(o,p,(int)z);*n=v;return v>=0 ? 0 : -1;
}
static inline int mbedtls_base64_decode(unsigned char *o,size_t cap,size_t *n,const unsigned char *p,size_t z) {
 if(!z || z%4)return -1;size_t room=z*3/4;unsigned char *tmp=malloc(room);if(!tmp)return -1;
 int v=EVP_DecodeBlock(tmp,p,(int)z);if(v<0){free(tmp);return -1;}
 if(p[z-1]=='=')v--;if(z>1 && p[z-2]=='=')v--;
 if(v<0 || (size_t)v>cap){free(tmp);return -1;}memcpy(o,tmp,v);free(tmp);*n=v;return 0;
}
'''

FIXTURE = r'''
#include "pet_owner_local.c"
#include <assert.h>
#include <stdio.h>
static int voice, unavailable, broken;
bool pet_voice_usable(const int16_t *p,int n){return p && n>=12000;}
bool pet_owner_embedding_ready(void){return !unavailable;}
bool pet_owner_embedding(const int16_t *p,int n,float *out){
 if(unavailable)return false;
 memset(out,0,sizeof(float)*PET_OWNER_EMBED_DIM);
 out[voice]=broken ? NAN : 1.f;out[3]=.03f*(p[0]%3);return true;
}
static int16_t pcm[48000];
'''


class OwnerLocalHostTests(unittest.TestCase):
    def test_enrollment_fresh_verification_atomic_storage_and_model_binding(self):
        prefix = next((p for p in (Path('/opt/homebrew/opt/openssl@3'), Path('/usr/local/opt/openssl@3'), Path('/usr'))
                       if (p / 'include/openssl/evp.h').exists()), None)
        if not prefix:
            self.skipTest('OpenSSL headers required for host base64 fixture')
        body = r'''
int main(void){
 assert(PET_OWNER_THRESHOLD==.60f);
 assert(!pet_owner_locked());assert(pet_owner_storage_ok());assert(pet_owner_commit()==-1);
 assert(pet_owner_stage(pcm,24000)==-1);assert(s_count==0);
 assert(pet_owner_stage(pcm,48000)==0);assert(!pet_owner_locked());assert(pet_owner_commit()==-1);
 assert(pet_owner_add_sample(pcm,48000)==-1);pcm[0]=1;
 voice=1;assert(pet_owner_add_sample(pcm,48000)==-1);assert(s_count==1);
 voice=0;assert(pet_owner_add_sample(pcm,48000)==0);pcm[0]=2;
 assert(pet_owner_add_sample(pcm,48000)==0);assert(pet_owner_verify_candidate(pcm,48000)<0);
 pcm[0]=3;voice=1;assert(pet_owner_verify_candidate(pcm,48000)<PET_OWNER_THRESHOLD);assert(pet_owner_commit()==-1);
 voice=0;assert(pet_owner_verify_candidate(pcm,48000)>=PET_OWNER_THRESHOLD);assert(pet_owner_commit()==0);
 assert(pet_owner_locked());s_loaded=false;assert(pet_owner_locked());assert(pet_owner_verify(pcm,48000)>=PET_OWNER_THRESHOLD);
 assert(pet_owner_verify(pcm,24000)>=PET_OWNER_THRESHOLD);
 assert(pet_owner_verify(pcm,11999)<0);
 voice=1;assert(pet_owner_verify(pcm,24000)<PET_OWNER_THRESHOLD);
 assert(pet_owner_verify(pcm,48000)<PET_OWNER_THRESHOLD);
 voice=0;broken=1;assert(pet_owner_verify(pcm,48000)<0);broken=0;
 unavailable=1;assert(!pet_owner_locked());assert(pet_owner_verify(pcm,48000)<0);unavailable=0;
 assert(pet_owner_locked());assert(pet_owner_stage(pcm,48000)==0);pet_owner_abort();assert(pet_owner_locked());
 uint32_t sequence=0;char *saved=pet_snapshot_load(OWNER_BASE,2048,&sequence);assert(saved && strlen(saved)<2048);
 assert(2*(strlen(saved)+20)<=4096); /* two snapshot headers included */
 cJSON *root=cJSON_Parse(saved);assert(root);free(saved);
 cJSON_ReplaceItemInObject(root,"model_hash",cJSON_CreateString("different-model"));
 char *bad=cJSON_PrintUnformatted(root);cJSON_Delete(root);
 assert(pet_snapshot_save(OWNER_BASE,bad,2048,&sequence)==0);free(bad);s_loaded=false;
 assert(!pet_owner_locked());assert(!pet_owner_storage_ok());assert(pet_owner_stage(pcm,48000)==-1);
 assert(pet_snapshot_save(OWNER_BASE,"{\"provider\":\"xfyun-v2\",\"verified\":true}",2048,&sequence)==0);s_loaded=false;
 assert(!pet_owner_storage_ok());assert(pet_owner_stage(pcm,48000)==-1);
 return 0;
}
'''
        test_runtime_core.RuntimeCoreTests.run_c(self, FIXTURE + body, ['pet_util'],
            {'mbedtls/base64.h': SDK},
            ['-DCONFIG_DESKPET_LOCAL_OWNER=1', '-I', str(prefix / 'include'), '-L', str(prefix / 'lib'), '-lcrypto'])
