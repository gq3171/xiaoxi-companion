"""Real native map journeys, persistent pet care and unchanged scene protocol."""
import json,secrets,tempfile,unittest
from pathlib import Path
import home_sync as home
from home_world_life import WorldLife
import test_home_sync as fixture
class WorldLifeTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):fixture.HomeSyncTests.setUpClass();cls.library=fixture.HomeSyncTests.library
 @classmethod
 def tearDownClass(cls):fixture.HomeSyncTests.tearDownClass()
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.clock=fixture.Clock();self.world=home.HomeWorld(self.root/'home-sync.json',self.library,self.root/'assets',clock=self.clock.wall,monotonic=self.clock.mono,start=False)
 def tearDown(self):self.world.close();self.tmp.cleanup()
 def command(self,action,**kw):return dict(id=secrets.token_hex(16),epoch=self.world.epoch,revision=self.world.revision,action=action)|kw
 def advance(self,seconds):
  for _ in range(round(seconds*20)):self.clock.now+=.05;self.world.snapshot()
 def test_journey_reaches_door_before_map_switch_and_cat_is_shared(self):
  self.world.command(self.command('yard'),'web');self.assertEqual(self.world.life.location,'home');self.assertEqual(self.world.life.pending['to'],'yard');self.advance(10);s=self.world.snapshot();self.assertEqual(s['world']['location'],'yard');self.assertEqual(len(s['wire']),34);self.assertTrue(0<=s['art_frame']<52);self.assertTrue(32<=s['world']['cat']['art_frame']<=49)
  self.world.command(self.command('rest'),'web');self.assertEqual(self.world.life.location,'yard');self.assertEqual(self.world.life.pending['after'],'rest');self.advance(30);self.assertEqual(self.world.life.location,'home');self.assertEqual(self.world.snapshot()['wire'][16],3)
 def test_feeding_is_idempotent_and_care_survives_restart(self):
  self.world.life.cat['hunger']=20.;self.world.life.cat['affection']=20.;event=self.command('catfeed');self.world.command(event,'web');self.assertEqual(self.world.life.cat['mode'],8);self.assertEqual(self.world.life.cat['hunger'],20.);self.world.command(event,'web');self.assertEqual(self.world.life.cat['hunger'],20.);self.advance(2);self.assertAlmostEqual(self.world.life.cat['hunger'],55.,places=2)
  self.world.close();self.world=home.HomeWorld(self.world.path,self.library,self.world.assets,clock=self.clock.wall,monotonic=self.clock.mono,start=False);self.assertAlmostEqual(self.world.life.cat['hunger'],55.,places=2);self.assertEqual(self.world.life.cat['mode'],4)
 def test_new_indoor_request_cancels_outbound_journey(self):
  self.world.command(self.command('yard'),'web');self.world.command(self.command('rest'),'web');self.assertIsNone(self.world.life.pending);self.advance(25);self.assertEqual(self.world.life.location,'home');self.assertEqual(self.world.snapshot()['wire'][16],3)
 def test_floor_walk_is_motion_and_not_teleport(self):
  self.world.command(self.command('walkto',x=170,y=400),'web');s=self.world.snapshot();self.assertNotEqual(s['wire'][:2],[170,400]);self.advance(12);s=self.world.snapshot();self.assertEqual(s['wire'][:2],[170,400]);self.assertEqual(s['wire'][16],0)
 def test_outdoor_computer_request_returns_home_before_sitting(self):
  self.world.command(self.command('yard'),'web');self.advance(10);self.world.command(self.command('work'),'web');self.assertEqual(self.world.life.pending['after'],'work');self.advance(30);s=self.world.snapshot();self.assertEqual(s['world']['location'],'home');self.assertEqual(s['wire'][17],3);self.assertIn(s['wire'][16],(6,7))
 def test_invalid_persistent_cat_is_rejected_without_reset(self):
  data=self.world.life.dump();data['cat']['hunger']=float('nan')
  with self.assertRaises(ValueError):WorldLife(self.clock.wall,data)
 def test_no_autonomous_outing_during_chat_or_at_night_and_outdoor_visit_returns(self):
  self.world.life.last_engaged-=3000;self.world.life.last_outing-=3000;self.world.life.tick(self.world,50,live=True);self.assertIsNone(self.world.life.pending);self.world.life.last_engaged-=3000;self.world.life.tick(self.world,50,night=True);self.assertIsNone(self.world.life.pending)
  self.world.command(self.command('yard'),'web');self.advance(120);self.assertEqual(self.world.life.location,'home')

 def test_all_four_walk_frames_and_dedicated_care_art_are_used(self):
  life=self.world.life;life.cat.update(x=120.,y=425.,face=1);life.mode(1);life.tick(self.world,50,live=True);frames=[]
  for _ in range(4):
   frames.append(life.snapshot(0)['cat']['art_frame'])
   for _ in range(5):self.clock.now+=.05;life.tick(self.world,50,live=True)
  self.assertEqual(set(frames),{33,34,36,37})
  for mode,expected in [(4,{41,42}),(5,{43,44}),(7,{39,40})]:
   life.mode(mode,8);first=life.snapshot(0)['cat']['art_frame'];self.clock.now+=.65;second=life.snapshot(0)['cat']['art_frame'];self.assertEqual({first,second},expected)
 def test_sleep_wake_stretch_walk_then_eat_without_teleport_or_early_food_credit(self):
  self.world.command(self.command('rest'),'web');self.advance(30);life=self.world.life;self.assertEqual(life.cat['mode'],3);life.cat['hunger']=20.;position=(life.cat['x'],life.cat['y'])
  self.world.command(self.command('catfeed'),'web');self.assertEqual(life.cat['mode'],2);self.assertEqual(life.snapshot(0)['cat']['art_frame'],46);self.advance(1.1);self.assertEqual(life.snapshot(0)['cat']['art_frame'],47);self.assertEqual((life.cat['x'],life.cat['y']),position);self.assertLessEqual(life.cat['hunger'],20.)
  self.advance(1.2);self.assertIn(life.cat['mode'],(8,11));self.assertLessEqual(life.cat['hunger'],20.);self.advance(6);self.assertEqual(life.cat['mode'],4);self.assertAlmostEqual(life.cat['x'],300.,delta=8);self.assertGreater(life.cat['hunger'],54)
  self.advance(15);self.assertEqual(life.cat['mode'],3)
 def test_pending_pet_wake_survives_restart_and_legacy_mode_is_readable(self):
  self.world.command(self.command('rest'),'web');self.advance(30);self.world.command(self.command('catpet'),'web');self.advance(.8);self.world.save();data=self.world.life.dump();self.assertEqual(data['cat']['mode'],0);self.assertEqual(data['cat']['animation'],2)
  self.world.close();self.world=home.HomeWorld(self.world.path,self.library,self.world.assets,clock=self.clock.wall,monotonic=self.clock.mono,start=False);self.assertEqual(self.world.life.cat['after'],9);self.advance(2.2);self.assertEqual(self.world.life.cat['mode'],5)
  legacy=data.copy();legacy['cat']=dict(data['cat']);[legacy['cat'].pop(k,None) for k in ('animation','started','after')];self.assertEqual(WorldLife(self.clock.wall,legacy).cat['mode'],0)
 def test_every_animation_dump_keeps_old_firmware_life_modes_and_roundtrips(self):
  for mode in range(12):
   self.world.life.mode(mode,2,after=8);data=self.world.life.dump();self.assertIn(data['cat']['mode'],(0,1,3,4,5));self.assertIn(data['cat']['animation'],range(10));self.assertEqual(WorldLife(self.clock.wall,data).cat['mode'],mode)
 def test_idle_grooming_has_two_frames_and_does_not_start_while_talking(self):
  life=self.world.life;life.cat.update(x=282.,y=406.);life.mode(0);self.clock.now+=25;life.tick(self.world,50,live=True);self.assertEqual(life.cat['mode'],0);life.tick(self.world,50);self.assertEqual(life.cat['mode'],7);self.assertEqual(life.snapshot(0)['cat']['art_frame'],39);self.clock.now+=.5;self.assertEqual(life.snapshot(0)['cat']['art_frame'],40)


 def test_gait_freezes_when_blocked_and_resumes_without_phase_reset(self):
  life=self.world.life;life.cat.update(x=120.,y=425.,face=1);life.mode(1)
  for _ in range(5):self.clock.now+=.05;life.tick(self.world,50,live=True)
  before=life.snapshot(0)['cat'];self.assertEqual(before['walk_rate'],1000)
  for _ in range(30):self.clock.now+=.05;life.tick(self.world,50,blocked=True)
  paused=life.snapshot(0)['cat'];self.assertEqual(paused['phase_ms'],before['phase_ms']);self.assertEqual(paused['art_frame'],48);self.assertEqual(paused['walk_rate'],0)
  life.tick(self.world,50,live=True);self.assertGreater(life.cat['gait_ms'],before['phase_ms']);self.assertEqual(life.snapshot(0)['cat']['walk_rate'],1000)
 def test_gait_depends_on_distance_not_time_and_persists(self):
  life=self.world.life;life.cat.update(x=120.,y=425.,face=1);life.mode(1);self.clock.now+=100
  self.assertEqual(life.snapshot(0)['cat']['phase_ms'],0)
  life.tick(self.world,50,live=True);self.assertAlmostEqual(life.cat['gait_ms'],50.)
  self.assertEqual(WorldLife(self.clock.wall,life.dump()).snapshot(0)['cat']['phase_ms'],50)
  data=life.dump();data['cat'].pop('gait_ms');self.assertEqual(WorldLife(self.clock.wall,data).cat['gait_ms'],0)
  data['cat']['gait_ms']=float('inf')
  with self.assertRaises(ValueError):WorldLife(self.clock.wall,data)


 def cat_room(self,x=240,y=390,activity=1):
  from types import SimpleNamespace
  wire=[0]*34;wire[0]=x;wire[1]=y;wire[16]=activity
  return SimpleNamespace(scene=SimpleNamespace(wire=lambda:wire)),wire
 def test_follow_uses_latched_goal_and_stands_instead_of_sitting_between_steps(self):
  life=self.world.life;room,wire=self.cat_room();life.cat.update(x=120.,y=406.,face=1);life.mode(0)
  states=[]
  for i in range(110):
   wire[0]=240+(12 if i%2 else -12);self.clock.now+=.05;life.tick(room,50,live=True)
   state=life.snapshot(0)['cat'];states.append(state);self.assertEqual(state['face'],1)
  walking=[c for c in states if c['mode']==1];self.assertTrue(walking)
  self.assertTrue(all(c['art_frame'] in (33,34,36,37) for c in walking))
  self.assertEqual(states[-1]['mode'],10);self.assertEqual(states[-1]['art_frame'],48)
  self.assertEqual({c['mode'] for c in states},{1,10})
 def test_small_owner_movement_does_not_restart_following_or_flip_standing_cat(self):
  life=self.world.life;room,wire=self.cat_room();life.cat.update(x=300.,y=406.,face=1);life.mode(10,6)
  for i in range(180):
   wire[0]=240+(20 if i%2 else -20);self.clock.now+=.05;life.tick(room,50,live=True)
   c=life.snapshot(0)['cat'];self.assertEqual((c['mode'],c['art_frame'],c['face']),(10,48,1))
  wire[16]=0;life.tick(room,50,live=True);self.assertEqual(life.cat['mode'],0)
 def test_reversal_has_stationary_turn_before_changing_facing_and_survives_restart(self):
  life=self.world.life;room,wire=self.cat_room(x=120);life.cat.update(x=300.,y=406.,face=1);life.mode(0)
  life.tick(room,50,live=True);self.assertEqual(life.cat['mode'],11);self.assertEqual(life.cat['face'],1);self.assertEqual(life.snapshot(0)['cat']['art_frame'],49)
  self.clock.now+=.28;life.tick(room,50,live=True);self.assertEqual((life.cat['x'],life.cat['y']),(300.,406.))
  restored=WorldLife(self.clock.wall,life.dump());self.assertEqual(restored.cat['mode'],11);self.assertEqual(restored.cat['goal'],life.cat['goal'])
  self.clock.now+=.65;restored.tick(room,50,live=True);self.assertEqual(restored.cat['face'],-1);self.assertEqual(restored.cat['mode'],1);self.assertLess(restored.cat['x'],300.)
 def test_older_software_can_read_turn_and_stale_optional_motion_is_ignored(self):
  life=self.world.life;life.mode(11,.9);data=life.dump();self.assertEqual(data['cat']['animation'],1);self.assertEqual(data['cat']['mode'],0)
  data['cat']['animation']=3;data['cat']['started']+=2
  self.assertEqual(WorldLife(self.clock.wall,data).cat['mode'],3)
 def test_waking_and_care_finish_standing_without_a_seated_flash(self):
  life=self.world.life;room,wire=self.cat_room();life.cat.update(x=282.,y=406.,face=1)
  for mode in (2,4,5):
   life.mode(mode,.2);self.clock.now+=.3;life.tick(room,50,live=True)
   c=life.snapshot(0)['cat'];self.assertEqual((c['mode'],c['art_frame']),(10,48))
 def test_invalid_optional_goal_and_turn_are_rejected(self):
  for field,value in [('goal',{'x':float('nan'),'y':400,'kind':'follow'}),('turn_face',0),('resume',4)]:
   data=self.world.life.dump();data['cat'][field]=value
   with self.assertRaises(ValueError):WorldLife(self.clock.wall,data)

 def test_map_exit_waits_for_cat_care_to_finish_instead_of_erasing_it(self):
  life=self.world.life;life.cat.update(x=300.,y=390.,hunger=20.);life.care(4);self.world.command(self.command('yard'),'web');self.advance(6);self.assertEqual(life.location,'home');self.assertEqual(life.cat['mode'],4);self.advance(6);self.assertEqual(life.location,'yard');self.assertGreater(life.cat['hunger'],54)
