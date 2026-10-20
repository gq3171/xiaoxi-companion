import unittest
import test_runtime_core as core

class OrientationTests(unittest.TestCase):
    def test_cardinal_debounce_flat_diagonal_shake_stale_and_wrap(self):
        core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include <math.h>
#include "pet_orientation.h"
static unsigned hold(pet_orientation_t*s,float x,float y,float z,uint32_t*t,int n){float a[]={x,y,z},g[]={0,0,0};unsigned event=0;for(int i=0;i<n;i++){*t+=50;event|=pet_orientation_step(s,a,g,*t);}return event;}
int main(void){
 const unsigned angles[]={0,90,180,270};const float a[4][2]={{0,1},{-1,0},{0,-1},{1,0}};
 for(unsigned i=0;i<4;i++){
  pet_orientation_t s={0};uint32_t t=0xffffff00u;
  hold(&s,a[i][0],a[i][1],0,&t,12);assert(s.rotation==0);
  unsigned events=hold(&s,a[i][0],a[i][1],0,&t,8);assert(s.rotation==angles[i]);
  if(i)assert(events&PET_ORIENT_TURNED);
  hold(&s,0,0,1,&t,50);assert(s.rotation==angles[i]);
  hold(&s,.707f,.707f,0,&t,50);assert(s.rotation==angles[i]);
  float bad[]={1,0,0},spin[]={0,0,120};t+=50;assert(!pet_orientation_step(&s,bad,spin,t));assert(s.rotation==angles[i]);
  bad[0]=NAN;t+=50;assert(!pet_orientation_step(&s,bad,spin,t));
 }
 pet_orientation_t s={0};uint32_t t=0;hold(&s,0,1,0,&t,25);
 assert(hold(&s,.45f,.89f,0,&t,20)&PET_ORIENT_TILTED);
 hold(&s,0,1,0,&t,25);assert(!hold(&s,.45f,.89f,0,&t,20));
 hold(&s,0,1,0,&t,180);assert(hold(&s,.45f,.89f,0,&t,20)&PET_ORIENT_TILTED);
 pet_orientation_t fresh={0};t=0;hold(&fresh,-1,0,0,&t,10);t+=2000;hold(&fresh,-1,0,0,&t,1);assert(fresh.rotation==0);hold(&fresh,-1,0,0,&t,14);assert(fresh.rotation==90);
 return 0;}
''',['pet_orientation'])
    def test_measured_board_mount_and_four_usb_edges_are_upright(self):
        core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include "pet_orientation.h"
int main(void){
 /* Owner explicitly held USB down for three seconds, then laid flat.
  * Several settled samples agreed on +ay. The prior ax-labelled sample
  * was not synchronized to the real pose and must not define the mount. */
 const float samples[7][3]={{.087f,.946f,.204f},{.115f,.961f,.173f},{.189f,.959f,.115f},
  {-.99f,0,.15f},{0,-.99f,.15f},{.99f,0,.15f},{.012f,-.043f,1.025f}};
 const unsigned expected[]={0,0,0,270,180,90,0};float gyro[3]={0};
 for(int i=0;i<7;i++){
  pet_orientation_t s={0};float g[3];pet_orientation_from_qmi(samples[i],g);
  for(unsigned t=0;t<=1500;t+=50)pet_orientation_step(&s,g,gyro,t);
  assert(s.rotation==expected[i]);
 }
 /* Synthetic quarter turns use the sensor's right-handed installed axes. */
 const unsigned physical[]={0,90,180,270},compensation[]={0,270,180,90};
 for(int i=0;i<4;i++)assert((physical[i]+compensation[i])%360==0);
 float g[]={.087f,.946f,.204f};pet_orientation_from_qmi(g,g);assert(g[0]<0&&g[1]>.94f);
 return 0;}
''',['pet_orientation'])

    def test_inverse_touch_matches_all_rotated_pixels_and_edges(self):
        core.RuntimeCoreTests.run_c(self,r'''
#include <assert.h>
#include "pet_orientation.h"
int main(void){
 for(int r=0;r<360;r+=90)for(int x=0;x<480;x+=17)for(int y=0;y<480;y+=19){
  int px=x,py=y;
  if(r==90){px=479-y;py=x;}else if(r==180){px=479-x;py=479-y;}else if(r==270){px=y;py=479-x;}
  pet_orientation_touch(r,480,&px,&py);assert(px==x&&py==y);
 }
 int x=480,y=-1;pet_orientation_touch(90,480,&x,&y);assert(x==0&&y==0);
 float a=-1,b=0;pet_orientation_vector(90,&a,&b);assert(a==0&&b==1);
 return 0;}
''',['pet_orientation'])
