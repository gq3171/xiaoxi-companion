"""Replay real screen policy across power, activity and clock rollover."""
import unittest
import test_runtime_core

class ScreenHostTests(unittest.TestCase):
    def test_fade_power_change_wake_and_rollover(self):
        test_runtime_core.RuntimeCoreTests.run_c(self, r'''
#include <assert.h>
#include "pet_screen.h"
#include "pet_wake_gate.h"
int main(void){
 pet_screen_t s={0};
 assert(pet_screen_brightness(&s,1000,false,false,false)==75);
 int before=75;
 for(unsigned t=51000;t<61000;t+=137){
  int n=pet_screen_brightness(&s,t,false,false,false);assert(n<=before&&n>0);before=n;
 }
 assert(pet_screen_brightness(&s,61000,false,false,false)==0);
 pet_screen_activity(&s,62000);assert(pet_screen_brightness(&s,62000,false,false,false)==75);
 assert(pet_screen_brightness(&s,122000,false,false,false)==0);
 assert(pet_screen_brightness(&s,123000,true,false,false)==75);
 assert(pet_screen_brightness(&s,407999,true,false,false)==75);
 assert(pet_screen_brightness(&s,415500,true,false,false)>0);
 assert(pet_screen_brightness(&s,423000,true,false,false)==0);
 assert(pet_screen_brightness(&s,424000,false,false,true)==50);
 assert(pet_screen_brightness(&s,999000,false,true,true)==50);
 assert(pet_screen_brightness(&s,1058999,false,false,true)>0);
 assert(pet_screen_brightness(&s,1059000,false,false,true)==0);
 pet_screen_activity(&s,UINT32_MAX-30000);
 assert(pet_screen_brightness(&s,29999,false,false,false)==0);
 pet_wake_require(true);unsigned token=pet_wake_interactions();
 pet_wake_heard(40000);assert(pet_wake_interactions()!=token);
 token=pet_wake_interactions();pet_wake_hold(true,40001);
 pet_wake_active(40002);assert(pet_wake_interactions()==token);
 pet_wake_activity(40003);assert(pet_wake_interactions()!=token);
 unsigned activations=pet_wake_activations();
 pet_wake_rest();assert(pet_wake_resting()&&!pet_wake_active(40004));
 pet_wake_activity(40005);assert(pet_wake_resting()&&!pet_wake_active(40005));
 assert(pet_wake_activations()==activations);
 pet_wake_heard(40006);assert(!pet_wake_resting()&&pet_wake_active(40006));
 assert(pet_wake_activations()!=activations);
 pet_screen_activity(&s,60000);s.usb_power=false;pet_screen_off(&s);
 assert(pet_screen_brightness(&s,60001,false,true,false)==0);
 assert(pet_screen_brightness(&s,80000,false,true,false)==0);
 pet_screen_activity(&s,80001);assert(pet_screen_brightness(&s,80001,false,false,false)==75);
 return 0;
}
''', ["pet_screen","pet_wake_gate"])
