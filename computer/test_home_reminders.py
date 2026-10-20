"""Durable time and delivery contracts without real alarms or provider calls."""
import tempfile,unittest
from pathlib import Path
from home_reminders import ReminderStore,deadline
class ReminderTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.now=1800000000;self.path=Path(self.tmp.name)/'reminders.sqlite3';self.store=ReminderStore(self.path,lambda:self.now)
 def tearDown(self):self.store.close();self.tmp.cleanup()
 def create(self,key='a',candidate='五分钟后喊我',origin='web',**spec):return self.store.create(key,dict(text='起身走一走',due='2000-01-01 00:00',repeat_minutes=0)|spec,candidate,self.now,origin=origin)
 def test_relative_time_uses_request_time_not_invented_model_date(self):
  for text,delta in [('5分钟后喊我',300),('五分钟后提醒我',300),('三十秒后叫我',30),('半小时后喊我',1800),('两小时后提醒喝水',7200)]:self.assertEqual(deadline({},text,self.now),self.now+delta)
 def test_restart_and_replay_after_due_do_not_duplicate(self):
  a=self.create();self.now+=400;self.store.close();self.store=ReminderStore(self.path,lambda:self.now);self.assertEqual(self.create()['id'],a['id']);self.assertEqual(len(self.store.due('web')),1);self.assertEqual(self.path.stat().st_mode&0o777,0o600)
 def test_only_one_recipient_claims_and_receipts_require_matching_lease(self):
  a=self.create();self.now+=300;c=self.store.claim('web',a['id']);self.assertIsNone(self.store.claim('body'));self.assertEqual(self.store.claim('web')['lease'],c['lease']);self.assertFalse(self.store.acknowledge('body',a['id'],c['lease'],'played'));self.assertTrue(self.store.acknowledge('web',a['id'],c['lease'],'displayed'));self.assertTrue(self.store.acknowledge('web',a['id'],c['lease'],'displayed'));self.assertEqual(self.store.active(),[])
 def test_expired_claim_can_transfer_and_cancellation_invalidates_audio(self):
  a=self.create();self.now+=300;c=self.store.claim('web');self.now+=91;self.assertIsNone(self.store.claim('body'));d=self.store.claim('web');self.assertNotEqual(c['lease'],d['lease']);self.assertFalse(self.store.acknowledge('web',a['id'],c['lease'],'played'));self.store.cancel(a['id'])
  with self.assertRaises(ValueError):self.store.validate_claim('web',a['id'],d['lease'])
  self.assertIsNone(self.store.claim('body'))
 def test_repeating_reminder_skips_missed_intervals_and_can_be_cancelled(self):
  a=self.create(candidate='每五分钟提醒我休息',due=__import__('datetime').datetime.fromtimestamp(self.now+300,__import__('home_reminders').TZ).strftime('%Y-%m-%d %H:%M'),repeat_minutes=5);self.now+=2000;c=self.store.claim('web');self.assertTrue(self.store.acknowledge('web',a['id'],c['lease'],'played'));row=self.store.active()[0];self.assertGreater(row['due'],self.now);self.assertLessEqual(row['due'],self.now+300);self.assertTrue(self.store.cancel(a['id']));self.assertFalse(self.store.cancel(a['id']))
 def test_invalid_time_text_implicit_repeat_and_identifiers_rejected(self):
  for spec in [dict(text=''),dict(text='字'*81),dict(repeat_minutes=1),dict(repeat_minutes=5)]:
   with self.assertRaises(ValueError):self.create(**spec)
  with self.assertRaises(ValueError):self.create(candidate='你好')
  with self.assertRaises(ValueError):self.store.claim('web',True)
 def test_pending_budget_and_ack_replay_cannot_rearm(self):
  for i in range(8):self.create(str(i))
  with self.assertRaises(ValueError):self.create('extra')
  self.now+=300;c=self.store.claim('web');self.store.acknowledge('web',c['id'],c['lease'],'played');self.store.close();self.store=ReminderStore(self.path,lambda:self.now);self.assertTrue(self.store.acknowledge('web',c['id'],c['lease'],'played'));self.assertEqual(len(self.store.active()),7)

 def test_completed_followup_survives_restart_without_claiming_owner_heard_it(self):
  from home_reminders import describe_reminders
  a=self.create();self.now+=300;claim=self.store.claim('web');self.store.acknowledge('web',a['id'],claim['lease'],'played');self.store.close();self.store=ReminderStore(self.path,lambda:self.now)
  text=describe_reminders(self.store);self.assertIn('网页',text);self.assertIn('播完',text);self.assertIn('不知道你有没有听到',text);self.assertNotIn('没有待提醒',text)
  self.assertEqual(self.store.active(),[]);self.assertNotIn('lease',self.store.recent()[0]);self.assertNotIn('recipient',self.store.recent()[0]);self.assertIsNone(self.store.claim('web'))
 def test_pending_countdown_and_overdue_are_not_completed_receipts(self):
  from home_reminders import describe_reminders
  a=self.create();self.now+=61;self.assertIn('3分59秒',describe_reminders(self.store));self.now+=240;self.store.claim('web');text=describe_reminders(self.store);self.assertIn('等提醒播完的确认',text);self.assertNotIn('回报已经播完',text)
 def test_display_only_receipt_does_not_claim_audio_and_history_is_bounded(self):
  from home_reminders import describe_reminders
  for i in range(6):
   a=self.create(str(i));self.now+=300;c=self.store.claim('web',a['id']);self.store.acknowledge('web',a['id'],c['lease'],'displayed')
  self.assertEqual(len(self.store.recent()),4);self.assertIn('没有播放声音的记录',describe_reminders(self.store));self.now+=86401;self.assertEqual(self.store.recent(),[])
 def test_cancelled_recent_reminder_is_distinct_from_never_scheduled(self):
  from home_reminders import describe_reminders
  self.store.cancel(self.create()['id']);self.assertIn('取消',describe_reminders(self.store));self.assertEqual(self.store.active(),[])
 def test_origin_browser_stays_bound_after_offline_restart_and_expired_lease(self):
  a=self.create(origin='unit-browser');self.now+=300
  self.assertEqual(self.store.due('home-browser'),[]);self.assertEqual(self.store.due('body'),[]);self.assertEqual(self.store.due(),[])
  c=self.store.claim('unit-browser');self.now+=91;self.assertIsNone(self.store.claim('body'));self.assertIsNone(self.store.claim('home-browser'))
  self.store.close();self.store=ReminderStore(self.path,lambda:self.now);fresh=self.store.claim('unit-browser');self.assertNotEqual(c['lease'],fresh['lease']);self.assertFalse(self.store.acknowledge('unit-browser',a['id'],c['lease'],'played'))
 def test_body_reminder_cannot_be_claimed_by_any_browser(self):
  a=self.create(origin='body');self.now+=300;self.assertIsNone(self.store.claim('web'));self.assertIsNone(self.store.claim('other'));self.assertEqual(self.store.claim('body')['id'],a['id'])
 def test_explicit_both_has_independent_deliveries_and_cancel_covers_both(self):
  candidate='五分钟后网页和家里的小板子两边都提醒我';a=self.create(candidate=candidate,delivery='both',delivery_request='网页和家里的小板子两边都提醒我');self.now+=300
  w=self.store.claim('web');b=self.store.claim('body');self.assertNotEqual(w['lease'],b['lease']);self.assertFalse(self.store.acknowledge('body',a['id'],w['lease'],'played'))
  self.assertTrue(self.store.acknowledge('web',a['id'],w['lease'],'played'));self.assertEqual(self.store.due('web'),[]);self.assertEqual(len(self.store.due('body')),1);self.assertEqual(len(self.store.active()),1)
  self.assertTrue(self.store.acknowledge('body',a['id'],b['lease'],'displayed'));self.assertEqual(self.store.active(),[]);self.assertEqual(len(self.store.recent()[0]['targets']),2)
  c=self.create('cancel-both',candidate=candidate,delivery='both',delivery_request='两边都提醒我');self.now+=300;self.store.cancel(c['id']);self.assertIsNone(self.store.claim('web'));self.assertIsNone(self.store.claim('body'))
 def test_unrequested_or_negated_cross_endpoint_delivery_is_rejected(self):
  for candidate,quote in [('五分钟后提醒我','两边都提醒'),('五分钟后不要在家里的板子提醒我','家里的板子提醒我')]:
   with self.assertRaises(ValueError):self.create(candidate=candidate,delivery='both',delivery_request=quote)
  with self.assertRaises(ValueError):self.store.create('no-origin',dict(text='起身'),'五分钟后提醒我',self.now)
 def test_repeating_both_does_not_wait_for_offline_endpoint_to_repeat_here(self):
  candidate='每五分钟网页和家里的小板子两边都提醒我';a=self.create(candidate=candidate,delivery='both',delivery_request='两边都提醒我',repeat_minutes=5,due=__import__('datetime').datetime.fromtimestamp(self.now+300,__import__('home_reminders').TZ).strftime('%Y-%m-%d %H:%M'));self.now+=300
  first=self.store.claim('web');self.store.acknowledge('web',a['id'],first['lease'],'played');self.now+=300;second=self.store.claim('web');self.assertNotEqual(first['lease'],second['lease']);self.assertIsNotNone(self.store.claim('body'));self.assertEqual(len(self.store.active()),1)
 def test_legacy_web_migration_uses_creator_and_unknown_source_stays_closed(self):
  import sqlite3
  self.store.close();other=Path(self.tmp.name)/'legacy';other.mkdir();db=sqlite3.connect(other/'web-chat.sqlite3');db.execute('CREATE TABLE turns(id TEXT,session TEXT)');db.execute("INSERT INTO turns VALUES('old-web','unit-browser')");db.commit();db.close()
  db=sqlite3.connect(other/'reminders.sqlite3');db.execute('CREATE TABLE reminders(id INTEGER PRIMARY KEY AUTOINCREMENT,request_id TEXT UNIQUE,text TEXT,due INTEGER,repeat_minutes INTEGER,state TEXT,recipient TEXT,lease TEXT,lease_until INTEGER,delivered TEXT,created INTEGER)')
  for n,key in enumerate(('old-web','unknown'),1):db.execute('INSERT INTO reminders VALUES(?,?,?,?,?,?,?,?,?,?,?)',(n,key,'旧提醒',int(self.now)-10,0,'scheduled','','',0,'',int(self.now)-20))
  db.commit();db.close();self.store=ReminderStore(other/'reminders.sqlite3',lambda:self.now)
  self.assertIsNone(self.store.claim('body'));self.assertEqual(self.store.claim('unit-browser')['id'],1);self.assertEqual(self.store.active()[1]['delivery_scope'],'unassigned')
