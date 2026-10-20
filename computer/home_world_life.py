"""Bounded shared dollhouse life: connected maps and one persistent companion cat."""
import math,time
ACTIONS={'yard','home','catpet','catfeed'}
MODES={0:'在旁边陪着',1:'跟着走',2:'慢慢醒来',3:'睡着了',4:'吃东西',5:'享受摸摸',6:'蜷好准备睡',7:'舔爪洗脸',8:'走去吃饭',9:'走近你',10:'站着等一等',11:'慢慢转过身'}
# Art IDs 32..35 retain their old meaning; additional cat frames are appended.
CAT_ART={'idle':32,'walk_a':33,'walk_b':34,'sleep':35,'walk_c':36,'walk_d':37,'blink':38,'groom_a':39,'groom_b':40,'eat_a':41,'eat_b':42,'pet_a':43,'pet_b':44,'lie_down':45,'wake':46,'stretch':47,'stand':48,'turn':49}
class WorldLife:
 def __init__(self,clock=time.time,data=None):
  self.clock=clock;now=clock();self.location='home';self.pending=None;self.entered=now;self.last_outing=now;self.last_engaged=now;self.cat=dict(x=285.,y=390.,mode=0,until=0.,hunger=80.,affection=60.,face=-1,started=now,after=0,gait_ms=0.,walk_rate=0,goal=None,resume=1,turn_face=-1)
  if data is not None:self.load(data)
 def load(self,d):
  if not isinstance(d,dict) or d.get('version')!=1 or d.get('location') not in ('home','yard'):raise ValueError('invalid shared world')
  for key in ('entered','last_outing','last_engaged'):
   if type(d.get(key)) not in (int,float) or not math.isfinite(d[key]) or not 0<=d[key]<2**53:raise ValueError('invalid world clock')
  cat=d.get('cat')
  if not isinstance(cat,dict) or type(cat.get('mode')) is not int or cat.get('mode') not in MODES or cat.get('face') not in (-1,1):raise ValueError('invalid companion cat')
  animation=cat.get('animation',cat['mode'])
  if cat.get('motion_started')==cat.get('started') and 'motion' in cat:animation=cat['motion']
  if type(animation) is not int or animation not in MODES:raise ValueError('invalid cat animation')
  for key,lo,hi in [('x',0,479),('y',0,479),('until',0,2**53),('hunger',0,100),('affection',0,100)]:
   if type(cat.get(key)) not in (int,float) or not math.isfinite(cat[key]) or not lo<=cat[key]<=hi:raise ValueError('invalid companion cat field')
  started=cat.get('started',self.clock());after=cat.get('after',0)
  if type(started) not in (int,float) or not math.isfinite(started) or not 0<=started<2**53 or type(after) is not int or after not in (0,8,9):raise ValueError('invalid cat animation stage')
  pending=d.get('pending')
  if pending is not None and (not isinstance(pending,dict) or pending.get('to') not in ('home','yard') or pending.get('after') not in ('','rest','wash','work','window','read','roam')):raise ValueError('invalid journey')
  gait=cat.get('gait_ms',0.)
  if type(gait) not in (int,float) or not math.isfinite(gait) or not 0<=gait<960:raise ValueError('invalid cat gait')
  goal=cat.get('goal');resume=cat.get('resume',1);turn_face=cat.get('turn_face',cat['face'])
  if goal is not None and (not isinstance(goal,dict) or goal.get('kind') not in ('follow','rest','food','pet') or any(type(goal.get(k)) not in (int,float) or not math.isfinite(goal[k]) or not 0<=goal[k]<=479 for k in ('x','y'))):raise ValueError('invalid cat destination')
  if type(resume) is not int or resume not in (1,8,9) or type(turn_face) is not int or turn_face not in (-1,1):raise ValueError('invalid cat turn')
  self.location=d['location'];self.pending=pending;self.cat=dict(cat,mode=animation,started=started,after=after,gait_ms=gait,walk_rate=0,goal=goal,resume=resume,turn_face=turn_face)
  for key in ('entered','last_outing','last_engaged'):setattr(self,key,d[key])
 def dump(self):
  c=dict(self.cat);c['motion']=c['mode'];c['motion_started']=c['started'];c['animation']={10:0,11:1}.get(c['mode'],c['mode']);c['mode']={2:0,6:3,7:0,8:1,9:1,10:0,11:0}.get(c['mode'],c['mode'])
  return dict(version=1,location=self.location,pending=self.pending,entered=self.entered,last_outing=self.last_outing,last_engaged=self.last_engaged,cat=c)
 def snapshot(self,scene_ms):
  c=self.cat;age=int(max(0.,self.clock()-c['started'])*1000);mode=c['mode'];art=CAT_ART['idle']
  if mode in (1,8,9):art=[33,34,36,37][int(c['gait_ms'])//240%4] if c['walk_rate'] else CAT_ART['stand']
  elif mode==2:art=CAT_ART['wake'] if age<900 else CAT_ART['stretch']
  elif mode==3:art=CAT_ART['sleep']
  elif mode==4:art=CAT_ART['eat_a']+age//350%2
  elif mode==5:art=CAT_ART['pet_a']+age//600%2
  elif mode==6:art=CAT_ART['lie_down']
  elif mode==7:art=CAT_ART['groom_a']+age//450%2
  elif mode==10:art=CAT_ART['stand']
  elif mode==11:art=CAT_ART['turn']
  elif age%6200>=5980:art=CAT_ART['blink']
  return dict(version=1,location=self.location,location_name='小院' if self.location=='yard' else '家里',destination=self.pending['to'] if self.pending else '',cat=dict(x=round(c['x']),y=round(c['y']),art_frame=art,mode=mode,state=MODES[mode],phase_ms=int(c['gait_ms']) if mode in (1,8,9) else age%60000,walk_rate=c['walk_rate'] if mode in (1,8,9) else 0,hunger=round(c['hunger']),affection=round(c['affection']),face=c['face']))
 def mode(self,value,duration=0,after=0):
  now=self.clock();self.cat.update(mode=value,started=now,until=now+duration if duration else 0.,after=after,walk_rate=0)
  if value not in (1,8,9,11):self.cat['goal']=None
 def care(self,value):
  self.mode(value,8 if value==4 else 6)
  if value==4:self.cat.update(hunger=min(100.,self.cat['hunger']+35),affection=min(100.,self.cat['affection']+3))
  else:self.cat['affection']=min(100.,self.cat['affection']+5)
 def ask_cat(self,value):
  # Wake before walking to food or leaning into a pet. Never teleport a sleeper.
  if self.cat['mode'] in (3,6):self.mode(2,2.2,after=value)
  elif self.cat['mode']==2:self.cat['after']=value
  elif self.cat['mode']==11:self.cat.update(resume=value,goal=None)
  else:self.cat['goal']=None;self.mode(value)
 def route(self,target,kind,resume):
  c=self.cat;c['goal']=dict(x=target[0],y=target[1],kind=kind)
  dx=target[0]-c['x'];facing=(1 if dx>0 else -1) if abs(dx)>12 else c['face']
  if facing!=c['face']:
   c.update(resume=resume,turn_face=facing);self.mode(11,.9)
  elif c['mode']!=resume:self.mode(resume)
 @staticmethod
 def command(room,action):room.scene.lib.home_command(room.scene.ptr,{'roam':1,'rest':2,'wash':4,'work':5,'window':6,'read':7}[action],room.ms,0,0)
 def journey(self,room,destination,after=''):
  if destination==self.location:
   self.pending=None;self.entered=self.clock();self.command(room,after or 'roam');return
  if self.pending and self.pending['to']==destination:
   if after:self.pending['after']=after
   return
  self.pending=dict(to=destination,after=after);self.command(room,'window')
 def request(self,room,action):
  now=self.clock();self.last_engaged=now
  if action in ('yard','home'):self.journey(room,action)
  elif action=='catfeed':self.ask_cat(8)
  elif action=='catpet':self.ask_cat(9)
  else:raise ValueError('unsupported world action')
 def intercept(self,room,action):
  if self.pending and action in ('rest','wash','work','read','window','roam','walkto','move') and self.location=='home':self.pending=None
  if self.location=='yard' and action in ('rest','wash','work','read','window'):
   self.last_engaged=self.clock();self.journey(room,'home',action);return True
  return False
 def tick(self,room,dt_ms,live=False,blocked=False,computer=0,night=False):
  now=self.clock();wire=room.scene.wire();transitioned=False;dt=min(1.,max(0.,dt_ms/1000.));c=self.cat;c['walk_rate']=0
  c['hunger']=max(0.,c['hunger']-dt/600);c['affection']=max(0.,c['affection']-dt/3600)
  if live or blocked:self.last_engaged=now
  if self.pending and wire[16]==8 and not blocked and c['mode'] not in (2,4,5,8,9,11):
   destination=self.pending['to'];after=self.pending['after'];self.pending=None;self.location=destination;self.entered=now;transitioned=True
   if destination=='yard':self.last_outing=now
   self.command(room,after or 'roam');wire=room.scene.wire();c.update(x=min(335.,wire[0]+38.),y=min(425.,wire[1]+16.));self.mode(0)
  if self.location=='yard' and not self.pending and wire[16]==8:self.command(room,'roam');wire=room.scene.wire()
  if not self.pending and not blocked:
   if self.location=='yard' and (computer==2 or now-self.entered>=90):self.journey(room,'home','work' if computer==2 else '')
   elif self.location=='home' and not live and not night and computer!=2 and wire[16] in (0,1,8) and now-self.last_engaged>=900 and now-self.last_outing>=2400:self.journey(room,'yard')
  if c['mode'] in (2,4,5,6,7):
   if now<c['until']:return transitioned
   if c['mode']==2:self.mode(c['after']) if c['after'] else self.mode(10,6.)
   elif c['mode']==6:self.mode(3)
   elif c['mode'] in (4,5):self.mode(10,6.)
   else:self.mode(0)
  if c['mode']==11:
   if blocked or now<c['until']:return transitioned
   c['face']=c['turn_face'];self.mode(c['resume'])
  rest=self.location=='home' and wire[16]==3
  if c['mode']==3:
   if rest:return transitioned
   self.mode(2,2.2);return transitioned
  companion=(min(340.,max(120.,wire[0]+42)),min(425.,max(300.,wire[1]+16)))
  kind='food' if c['mode']==8 else 'pet' if c['mode']==9 else 'rest' if rest else 'follow'
  desired=(300.,390.) if kind=='food' else (178.,300.) if kind=='rest' else companion
  # Follow a committed destination, with a wide leash. Minor owner movement must
  # not alternate sit/walk or reverse the sprite on consecutive updates.
  moving=c['mode'] in (1,8,9);goal=c['goal']
  if not moving:
   distance=math.hypot(desired[0]-c['x'],desired[1]-c['y'])
   if distance>(8 if rest else 64) and not blocked and (c['mode']!=10 or now-c['started']>=.8):
    self.route(desired,kind,1)
    if c['mode']==11:return transitioned
   else:
    if blocked:return transitioned
    if rest:self.mode(6,1.1)
    elif c['mode']==10:
     if now>=c['until'] and wire[16]!=1:self.mode(0)
    elif not live and self.location=='home' and c['hunger']<30:self.ask_cat(8)
    elif not live and now-c['started']>=24:self.mode(7,3.6)
    return transitioned
  elif goal is None or goal['kind']!=kind or (kind=='follow' and math.hypot(desired[0]-goal['x'],desired[1]-goal['y'])>96):
   self.route(desired,kind,c['mode'])
   if c['mode']==11:return transitioned
  goal=c['goal'];target=(goal['x'],goal['y'])
  dx,dy=target[0]-c['x'],target[1]-c['y'];distance=math.hypot(dx,dy)
  if distance>8 and not blocked:
   step=min(distance,33*dt);c['x']+=dx/distance*step;c['y']+=dy/distance*step
   if c['mode'] not in (1,8,9):self.mode(1)
   # Advance the gait by travelled distance, not wall time. Paused cats hold a planted pose.
   c['gait_ms']=(c['gait_ms']+step*1000/33)%960;c['walk_rate']=1000 if step>0 else 0
  else:
   if blocked:return transitioned
   if c['mode'] in (8,9):self.care(4 if c['mode']==8 else 5)
   elif rest:self.mode(6,1.1)
   else:self.mode(10,6.)

  return transitioned
