"""Compile actual remote-mode cloud code; mock bytes, no speech or real API calls."""
import unittest
import test_runtime_core as core
import test_cloud_host as cloud

class BrainCloudTests(unittest.TestCase):
    def test_all_cloud_paths_use_brain_pairing_and_audio_envelopes(self):
        headers={'http_test_sdk.h':cloud.HTTP_SDK,'sdkconfig.h':'''#define CONFIG_DESKPET_MINIMAX_HOST "https://api.minimaxi.com"
#define CONFIG_DESKPET_COMPUTER_URL "https://computer.example"
#define CONFIG_DESKPET_COMPUTER_TOKEN "01234567890123456789012345678901"
#define CONFIG_DESKPET_REMOTE_BRAIN 1
#define CONFIG_DESKPET_BRAIN_TOKEN "01234567890123456789012345678901"
'''}
        for name in ['esp_crt_bundle.h','esp_http_client.h','esp_log.h','esp_timer.h','esp_tls.h','freertos/FreeRTOS.h','freertos/task.h']:
            headers[name]='#include "http_test_sdk.h"\n'
        fixture=cloud.FIXTURE.replace('static bool signed_mode;', 'static bool signed_mode, session_header;')
        fixture=fixture.replace('if (!strcmp(key, "Authorization"))', 'if(!strcmp(key,"X-Pet-Session")){cJSON*j=cJSON_Parse(value);assert(cJSON_GetObjectItem(j,"device"));cJSON_Delete(j);session_header=true;}\n    if (!strcmp(key, "Authorization"))')
        fixture=fixture.replace('int esp_http_client_delete_header(void *c,const char *key){','int esp_http_client_delete_header(void *c,const char *key){if(!strcmp(key,"X-Pet-Session"))session_header=false;')
        core.RuntimeCoreTests.run_c(self,fixture+r'''
bool pet_brain_enabled(void){return true;}
bool pet_brain_ensure(void){return true;}
bool pet_brain_reconcile(void){return true;}
cJSON *pet_brain_envelope(void){return cJSON_Parse("{\"device\":\"001122334455\",\"session\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"boot\":1,\"generation\":1}");}
static void kind_is(const char *kind){cJSON*j=cJSON_Parse(request);assert(!strcmp(cJSON_GetObjectItem(j,"kind")->valuestring,kind));assert(cJSON_GetObjectItem(j,"device"));assert(!strstr(request,"test-only-key"));cJSON_Delete(j);assert(bearer&&!api_key&&!version&&!session_header);assert(!strcmp(last_url,"https://computer.example/v1/brain/model"));}
int main(void){
 pet_cloud_begin_turn(pet_turn_current());assert(pet_cloud_ready());
 response="{\"ok\":true,\"text\":\"{}\"}";cJSON*h=cJSON_Parse("[{\"role\":\"user\",\"content\":\"hi\"}]");
 char*out=pet_cloud_dialogue("state",h);assert(out);kind_is("dialogue");free(out);cJSON_Delete(h);
 out=pet_cloud_birth("birth","test");assert(out);kind_is("birth");free(out);
 out=pet_cloud_minimax("reflect","test",true);assert(out);kind_is("reflection");free(out);
 out=pet_cloud_minimax("plan","test",false);assert(out);kind_is("plan");free(out);
 response="{\"text\":\"fixture\"}";int16_t pcm[512]={0};char text[128];assert(!pet_cloud_transcribe(pcm,512,text,sizeof(text)));
 assert(!strcmp(last_url,"https://computer.example/v1/brain/asr")&&session_header&&!chinese_asr&&bearer);
 response="{\"base_resp\":{\"status_code\":0},\"data\":{\"audio\":\"00000100ffff0080\"}}";
 assert(pet_cloud_speak_voice("fixture","female-shaonv",pcm,512)==4);
 assert(!strcmp(last_url,"https://computer.example/v1/brain/tts")&&!session_header&&bearer&&!api_key);
 cJSON*j=cJSON_Parse(request);assert(cJSON_GetObjectItem(j,"speech")&&cJSON_GetObjectItem(j,"device"));cJSON_Delete(j);
 free(request);return 0;}
''',['pet_cloud','pet_tts','pet_search','pet_util','pet_turn','pet_stream','pet_latency'],headers)

if __name__=='__main__':unittest.main()
