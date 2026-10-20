"""Real runtime reminder admission: never announce delivery before audible speech."""
import unittest
import test_autonomy_host as a
import test_runtime_core as core
class RemoteReminderTests(unittest.TestCase):
 def test_quiet_capture_and_delivery_failure_do_not_consume_reminder(self):
  fixture=a.FIXTURE.replace('#include "pet_runtime.c"','#define CONFIG_DESKPET_HOME_SYNC 1\n#include "pet_runtime.c"\nstatic bool remote_audible,recording_now;static int remote_taken,remote_finished;static bool remote_success;')
  fixture=fixture.replace('bool pet_speech_audible(void) { return false; }','bool pet_speech_audible(void) { return remote_audible; }').replace('bool pet_capture_listening(void) { return false; }','bool pet_capture_listening(void) { return recording_now; }')
  code=fixture+r'''
bool pet_home_sync_take_reminder(char*out,size_t n){remote_taken++;snprintf(out,n,"起来走走");return true;}
void pet_home_sync_finish_reminder(bool played){remote_finished++;remote_success=played;}
int pet_home_sync_pair_code(char*out,size_t n){return -1;}
void pet_home_sync_world(pet_home_world_t*out){*out=(pet_home_world_t){0};}
int pet_home_sync_world_request(const char*a){return -1;}
void pet_home_sync_start(void){}
int pet_home_sync_pair(char*out,size_t n){return -1;}
int main(void){
 init();s_quiet_until=fake_now+MINUTE_US;reminders(pet_turn_current());assert(remote_taken==0);
 s_quiet_until=0;recording_now=true;reminders(pet_turn_current());assert(remote_taken==0);
 recording_now=false;reminders(pet_turn_current());assert(remote_taken==1&&remote_finished==1&&!remote_success);
 remote_audible=true;reminders(pet_turn_current());assert(remote_taken==2&&remote_finished==2&&remote_success);
 return 0;
}
'''
  headers={'runtime_test_sdk.h':a.SDK}
  for name in ['esp_log.h','esp_timer.h','esp_wifi.h','nvs.h','freertos/FreeRTOS.h','freertos/queue.h','freertos/task.h']:headers[name]='#include "runtime_test_sdk.h"\n'
  core.RuntimeCoreTests.run_c(self,code,['pet_tts','pet_search','pet_util','pet_policy','pet_turn','pet_owner_session','pet_life','pet_computer','pet_home','pet_latency','pet_wake_gate','pet_input'],headers)
