"""Real owner state and signed provider protocol; OpenSSL supplies host crypto."""
import base64
import datetime
import hashlib
import hmac
import json
from pathlib import Path
import unittest
from urllib.parse import urlencode
import test_runtime_core

SDK = r'''
#pragma once
#include <openssl/hmac.h>
#include <openssl/evp.h>
#include <stdint.h>
#include <stddef.h>
#include <assert.h>
#define MBEDTLS_MD_SHA256 1
#define ESP_MAC_WIFI_STA 0
typedef int mbedtls_md_info_t;
static inline const mbedtls_md_info_t *mbedtls_md_info_from_type(int t) {static int n;return &n;}
static inline int mbedtls_md_hmac(const mbedtls_md_info_t *i,const unsigned char *k,size_t n,const unsigned char *d,size_t z,unsigned char *o) {
 unsigned len;return HMAC(EVP_sha256(),k,(int)n,d,z,o,&len) ? 0 : -1;
}
static inline int mbedtls_base64_encode(unsigned char *o,size_t cap,size_t *n,const unsigned char *p,size_t z) {
 if(cap < 4*((z+2)/3)+1)return -1;int v=EVP_EncodeBlock(o,p,(int)z);*n=v;return v>=0 ? 0 : -1;
}
static inline int mbedtls_base64_decode(unsigned char *o,size_t cap,size_t *n,const unsigned char *p,size_t z) {
 if(!z || z%4 || cap<z*3/4)return -1;int v=EVP_DecodeBlock(o,p,(int)z);if(v<0)return -1;
 if(p[z-1]=='=')v--;if(z>1 && p[z-2]=='=')v--;*n=v;return 0;
}
int esp_read_mac(uint8_t *,int);
uint32_t esp_random(void);
'''

FIXTURE = r'''
#include "pet_owner.c"
#include <assert.h>
static int mode, serial_number;
static char app[32]="test-app";
const char *pet_secrets_xfyun_appid(void) {return app;}
const char *pet_secrets_xfyun_key(void) {return "test-key";}
const char *pet_secrets_xfyun_secret(void) {return "test-secret";}
bool pet_voice_usable(const int16_t *p,int n) {return p && n>=12000;}
int esp_read_mac(uint8_t *m,int type) {for(int i=0;i<6;i++)m[i]=i;return 0;}
uint32_t esp_random(void) {return ++serial_number;}
time_t time(time_t *out) {time_t n=@EPOCH@;if(out)*out=n;return n;}
char *pet_cloud_signed_json(const char *url,const cJSON *body) {
    assert(!strcmp(url,@URL@));
    const cJSON *header=cJSON_GetObjectItem(body,"header");assert(!strcmp(string((cJSON *)header,"app_id"),app));
    cJSON *op=cJSON_GetObjectItem(cJSON_GetObjectItem(body,"parameter"),XF_SERVICE);
    const char *action=string(op,"func"),*feature=string(op,"featureId");
    cJSON *result=cJSON_CreateObject();
    if(!strcmp(action,"createGroup"))cJSON_AddStringToObject(result,"groupId",s_group);
    else if(!strcmp(action,"queryFeatureList")) {cJSON_Delete(result);result=cJSON_CreateArray();}
    else if(!strcmp(action,"updateFeature")) {
        assert(cJSON_IsFalse(cJSON_GetObjectItem(op,"cover")));
        cJSON_AddStringToObject(result,"msg",mode==7 ? "failed" : "success");
    }
    else if(!strcmp(action,"searchScoreFea")) {
        feature=string(op,"dstFeatureId");
        cJSON_AddNumberToObject(result,"score",mode==4 ? 0.55 : 0.9);
        cJSON_AddStringToObject(result,"featureId",mode==2 ? "wrong-feature" : feature);
    } else cJSON_AddStringToObject(result,"featureId",feature);
    if(cJSON_GetObjectItem(body,"payload")) {
        cJSON *resource=cJSON_GetObjectItem(cJSON_GetObjectItem(body,"payload"),"resource");
        assert(!strcmp(string(resource,"encoding"),"raw"));
        assert(cJSON_GetObjectItem(resource,"sample_rate")->valueint==16000);
        assert(strlen(string(resource,"audio"))>100);
    }
    if(mode==5)cJSON_AddNumberToObject(result,"code",23005);
    char *plain=cJSON_PrintUnformatted(result);cJSON_Delete(result);char *encoded=b64((unsigned char *)plain,strlen(plain));free(plain);
    cJSON *root=cJSON_CreateObject();header=cJSON_AddObjectToObject(root,"header");
    if(mode!=3)cJSON_AddNumberToObject((cJSON *)header,"code",mode==1 ? 10313 : (mode==6 && !strcmp(action,"createGroup") ? 23008 : 0));
    cJSON *payload=cJSON_AddObjectToObject(root,"payload");char key[64];snprintf(key,sizeof(key),"%sRes",action);
    cJSON *block=cJSON_AddObjectToObject(payload,key);cJSON_AddStringToObject(block,"text",encoded);free(encoded);
    char *out=cJSON_PrintUnformatted(root);cJSON_Delete(root);return out;
}
'''


class OwnerHostTests(unittest.TestCase):
    def test_signing_independent_enrollment_commit_and_fail_closed_verification(self):
        prefix = next((p for p in (Path('/opt/homebrew/opt/openssl@3'), Path('/usr/local/opt/openssl@3'), Path('/usr'))
                       if (p / 'include/openssl/hmac.h').exists()), None)
        if not prefix:
            self.skipTest('OpenSSL headers required for host signing test')
        headers = {'owner_test_sdk.h': SDK}
        for name in ('mbedtls/base64.h', 'mbedtls/md.h', 'esp_mac.h', 'esp_random.h'):
            headers[name] = '#include "owner_test_sdk.h"\n'
        stamp = datetime.datetime(2026, 10, 17, tzinfo=datetime.timezone.utc)
        date = 'Sat, 17 Oct 2026 00:00:00 GMT'
        origin = f'host: api.xf-yun.com\ndate: {date}\nPOST /v1/private/s1aa729d0 HTTP/1.1'
        signature = base64.b64encode(hmac.new(b'test-secret', origin.encode(), hashlib.sha256).digest()).decode()
        auth = f'api_key="test-key", algorithm="hmac-sha256", headers="host date request-line", signature="{signature}"'
        url = 'https://api.xf-yun.com/v1/private/s1aa729d0?' + urlencode({
            'authorization': base64.b64encode(auth.encode()).decode(), 'host': 'api.xf-yun.com', 'date': date
        }).replace('+', '%20')
        body = r'''
int main(void) {
    int16_t *pcm=calloc(48000,sizeof(int16_t));assert(pcm);
    assert(!pet_owner_locked());assert(pet_owner_commit()==-1);
    assert(pet_owner_stage(pcm,48000)==0);assert(pet_owner_commit()==-1);
    assert(pet_owner_verify_candidate(pcm,48000)<0);assert(pet_owner_add_sample(pcm,48000)==-1);
    pcm[0]=1;assert(pet_owner_add_sample(pcm,48000)==0);
    pcm[0]=2;assert(pet_owner_add_sample(pcm,48000)==0);
    assert(pet_owner_verify_candidate(NULL,48000)<0);
    assert(pet_owner_verify_candidate(pcm,48000)<0);pcm[0]=3;
    mode=4;assert(pet_owner_verify_candidate(pcm,48000)<PET_OWNER_THRESHOLD);assert(pet_owner_commit()==-1);
    mode=0;assert(pet_owner_verify_candidate(pcm,48000)>=PET_OWNER_THRESHOLD);assert(pet_owner_commit()==0);
    assert(pet_owner_locked());s_loaded=false;assert(pet_owner_locked());
    for(mode=1;mode<=5;mode++)assert(pet_owner_verify(pcm,48000)<PET_OWNER_THRESHOLD);
    mode=0;assert(pet_owner_verify(pcm,48000)>=PET_OWNER_THRESHOLD);
    char previous[33];strcpy(previous,s_feature);assert(pet_owner_stage(pcm,48000)==0);
    mode=4;pet_owner_verify_candidate(pcm,48000);assert(pet_owner_commit()==-1);assert(!strcmp(previous,s_feature));
    mode=0;pet_owner_abort();assert(pet_owner_locked());
    mode=6;assert(pet_owner_stage(pcm,48000)==0);mode=0;pet_owner_abort();
    assert(pet_owner_stage(pcm,48000)==0);pcm[0]=4;
    mode=7;assert(pet_owner_add_sample(pcm,48000)==-1);mode=0;pet_owner_abort();assert(pet_owner_locked());
    strcpy(app,"other-app");assert(!pet_owner_locked());strcpy(app,"test-app");assert(pet_owner_locked());
    assert(pet_snapshot_save(OWNER_BASE,"{\"verified\":true}",2048,&s_sequence)==0);
    s_loaded=false;assert(!pet_owner_locked());assert(!pet_owner_storage_ok());
    assert(pet_owner_stage(pcm,48000)==-1);
    free(pcm);return 0;
}
'''
        code = (FIXTURE + body).replace('@EPOCH@', str(int(stamp.timestamp()))).replace('@URL@', json.dumps(url))
        flags = ['-I', str(prefix / 'include'), '-L', str(prefix / 'lib'), '-lcrypto']
        test_runtime_core.RuntimeCoreTests.run_c(self, code, ['pet_util'], headers, flags)
