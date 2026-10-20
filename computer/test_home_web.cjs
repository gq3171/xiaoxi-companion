/* Isolated frontend contracts. No real browser, microphone or network access. */
const fs=require('fs'),vm=require('vm'),assert=require('assert'),crypto=require('crypto');
const source=fs.readFileSync(__dirname+'/home_web/app.js','utf8');
function fixture(saved=new Map()){
 const elements=new Map(),calls=[];let microphoneCalls=0;
 const element=id=>{if(!elements.has(id))elements.set(id,{value:'',textContent:'',hidden:false,disabled:false,dataset:{},children:[],scrollHeight:0,scrollTop:0,clientHeight:0,classList:{toggle(){},add(){},remove(){}},getContext(){return{}},addEventListener(name,fn){this[name]=fn},querySelector(){return element('submit-button')},append(v){this.children.push(v)},replaceChildren(){this.children=[]},focus(){}});return elements.get(id);};
 const context={localStorage:{getItem:k=>saved.get(k)??null,setItem:(k,v)=>saved.set(k,v)},console,document:{hidden:false,getElementById:element,querySelectorAll:()=>[],createElement:()=>element(crypto.randomUUID()),addEventListener(){}},window:{isSecureContext:false,addEventListener(){}},navigator:{mediaDevices:{getUserMedia:async()=>{microphoneCalls++;throw Object.assign(Error('denied'),{name:'NotAllowedError'})}}},location:{protocol:'https:'},fetch:async(path,options)=>{calls.push({path,options});return{status:401,json:async()=>({ok:false})}},performance:{now:()=>0},requestAnimationFrame(){},setInterval:()=>1,clearInterval(){},setTimeout,TextEncoder,Blob,DataView,ArrayBuffer,Float32Array,URL,crypto};
 vm.createContext(context);vm.runInContext(source,context);return {context,element,calls,mic:()=>microphoneCalls};
}
(async()=>{
 let f=fixture();await new Promise(setImmediate);
 // A transient image failure must recover without flooding the server's web lane.
 const pictures=fixture();await new Promise(setImmediate);let outstanding=0,peak=0;const pictureAttempts=new Map();
 pictures.context.fetch=async()=>({ok:true,json:async()=>({rooms:['room'],frames:Array.from({length:12},(_,i)=>'frame'+i)})});
 pictures.context.setTimeout=fn=>setImmediate(fn);
 pictures.context.Image=class{set src(url){outstanding++;peak=Math.max(peak,outstanding);const name=url.split('?')[0],attempt=(pictureAttempts.get(name)||0)+1;pictureAttempts.set(name,attempt);setImmediate(()=>{outstanding--;if(name.endsWith('frame3.png')&&attempt===1)this.onerror();else this.onload();});}};
 await pictures.context.assets();assert(peak<=4);assert.strictEqual(pictureAttempts.get('/home/assets/frame3.png'),2);assert.strictEqual(pictureAttempts.size,13);
 // Getting into bed / early waking retain the bed-edge foot anchor (y=292).
 // The actual lying cel still belongs behind the mattress, not on the floor.
 const bed=fixture();await new Promise(setImmediate);bed.context.drawCalls=[];
 vm.runInContext(`
  Object.assign(ctx,{setTransform(){},clearRect(){},drawImage(...args){drawCalls.push(args)},beginPath(){},ellipse(){},fill(){}});
  images={room:{room:true},lie_sleep:{},sit:{}};
  manifest={frames:['lie_sleep','sit'],spots:[{action:'rest',front_y:268,mask:[36,208,156,60],sleep_mask:[36,198,168,70]}]};
  loaded=true;current={epoch:'bed-test',revision:1,wire:Array(34).fill(0),projection:[98,130,128],art_frame:0};
  current.wire[0]=155;current.wire[1]=292;current.wire[17]=1;
  render(0);
 `,bed.context);
 assert(bed.context.drawCalls.some(c=>c.length===9&&c.slice(1).join(',')==='36,198,168,70,36,198,168,70'),'lying transition must receive the bed cover even with feet at the approach anchor');
 bed.context.drawCalls.length=0;vm.runInContext('current.art_frame=1;render(0)',bed.context);
 assert(!bed.context.drawCalls.some(c=>c.length===9),'sitting at the bed edge must stay in front of the bed');
 // Sparse/battery updates must not jump straight from step A to D. Pauses freeze.
 const moving={mode:8,phase_ms:0,walk_rate:1000,art_frame:33};
 assert.deepStrictEqual([0,240,480,720].map(t=>f.context.catMotion(moving,t).art_frame),[33,34,36,37]);
 assert.strictEqual(f.context.catMotion(moving,9000).phase_ms,750);
 assert.strictEqual(f.context.catMotion({...moving,walk_rate:0},600).art_frame,33);
 assert.strictEqual(f.context.catMotion({...moving,walk_rate:0,art_frame:48},600).art_frame,48);
 assert.strictEqual(f.context.catMotion({mode:11,phase_ms:0,walk_rate:0,art_frame:49},600).art_frame,49);
 assert.strictEqual(f.context.catMotion({mode:3,phase_ms:0,art_frame:35},600).art_frame,35);
 assert.strictEqual(f.context.catMotion({mode:1,phase_ms:0,art_frame:37},600).art_frame,37);
assert.strictEqual(f.mic(),0,'loading page must never request microphone permission');
 const blob=f.context.wavFromChunks([new Float32Array(48000).fill(.5)],48000),buffer=await blob.arrayBuffer(),v=new DataView(buffer);assert.strictEqual(buffer.byteLength,32044);assert.strictEqual(v.getUint32(24,true),16000);assert.strictEqual(v.getUint16(22,true),1);assert.strictEqual(v.getInt16(44,true),16383);
 const limited=f.context.wavFromChunks([new Float32Array(31*16000)],16000);assert.strictEqual(limited.size,960044,'recording is bounded at 30 seconds');
 vm.runInContext("current={name:'小溪'}",f.context);await f.context.startRecording();assert.strictEqual(f.mic(),0);assert.match(f.element('chat-error').textContent,/受信任的 HTTPS/);
 f.context.window.isSecureContext=true;await f.context.startRecording();assert.strictEqual(f.mic(),1);assert.match(f.element('chat-error').textContent,/麦克风未获允许/);
 let stopped=0,closed=0;f.context.fakeRecording={stream:{getTracks:()=>[{stop(){stopped++}}]},node:{disconnect(){},port:{postMessage(){f.context.fakeRecording.resolveStop()}}},context:{sampleRate:16000,close:async()=>{closed++}},chunks:[new Float32Array(16000)],timer:1};vm.runInContext('recording=fakeRecording',f.context);const before=f.calls.length;await f.context.stopRecording(true);assert.strictEqual(stopped>=1,true);assert.strictEqual(closed,1);assert.strictEqual(f.calls.length,before,'cancelled recording must never upload');
 f.element('chat-text').value='你好小溪';const attempts=[];f.context.fetch=async(path,options)=>{attempts.push(JSON.parse(options.body));throw new TypeError('network failure')};
 await f.element('chat-form').submit({preventDefault(){}});await f.element('chat-form').submit({preventDefault(){}});assert.strictEqual(attempts[0].id,attempts[1].id,'retry must retain the same turn ID');assert.strictEqual(f.element('chat-text').value,'你好小溪');
 f.context.fetch=async(path,options)=>{
  if(path==='/home/api/chat'&&options.method==='POST')return {status:202,json:async()=>({ok:true})};
  if(path==='/home/api/chat/receipt')return {status:200,json:async()=>({ok:true})};
  return {status:200,json:async()=>({ok:true,turns:[{id:'a'.repeat(32),text:'你好小溪',state:'done',reply:{say:'你好呀。'}}]})};
 };
 await f.element('chat-form').submit({preventDefault(){}});assert.strictEqual(f.element('chat-text').value,'');assert.strictEqual(f.element('chat-send').disabled,false);assert.strictEqual(f.element('chat-log').children.length,2);
 const answerNode=f.element('chat-log').children[1];assert(answerNode.children.some(c=>c.textContent==='你好呀。'));assert(answerNode.children.some(c=>c.textContent==='听她说'));
 const saved=new Map(),keys=fixture(saved);await new Promise(setImmediate);vm.runInContext("current={name:'小溪'}",keys.context);keys.element('chat-text').value='键盘操作测试';let submissions=0;keys.element('chat-form').requestSubmit=()=>submissions++;
 function key(extra={}){let prevented=false;keys.element('chat-text').keydown({key:'Enter',preventDefault(){prevented=true},...extra});return prevented;}
 assert.strictEqual(key(),false);assert.strictEqual(submissions,0);assert.strictEqual(key({ctrlKey:true}),true);assert.strictEqual(key({metaKey:true}),true);assert.strictEqual(submissions,2);
 keys.element('send-on-enter').checked=true;keys.element('send-on-enter').change();assert.strictEqual(saved.get('xiaoxi.sendOnEnter'),'true');assert.strictEqual(key(),true);assert.strictEqual(submissions,3);
 assert.strictEqual(key({shiftKey:true}),false);assert.strictEqual(key({isComposing:true}),false);assert.strictEqual(key({keyCode:229}),false);keys.element('chat-text').compositionstart();assert.strictEqual(key(),false);keys.element('chat-text').compositionend();assert.strictEqual(submissions,3);
 keys.element('chat-send').disabled=true;key();keys.element('chat-send').disabled=false;key({repeat:true});assert.strictEqual(submissions,3);const restored=fixture(saved);await new Promise(setImmediate);assert.strictEqual(restored.element('send-on-enter').checked,true);assert.match(restored.element('send-key-hint').textContent,/Shift/);
 const alerts=fixture();await new Promise(setImmediate);vm.runInContext("current={name:'小溪'}",alerts.context);alerts.element('reminder-sound').checked=false;
 alerts.context.showReminders([{id:1,text:'起来走走',due:20}]);assert.strictEqual(alerts.element('reminder-notice').hidden,false);assert.strictEqual(alerts.element('reminder-text').textContent,'起来走走');assert.strictEqual(alerts.mic(),0);
 const deliveries=[];alerts.context.fetch=async(path,options)=>{deliveries.push({path,body:JSON.parse(options.body)});return {status:200,json:async()=>({ok:true,reminder:{id:1,text:'起来走走',due:20,lease:'a'.repeat(32)}})};};
 await alerts.context.deliverReminder(true);assert.strictEqual(deliveries.at(-1).body.delivery,'displayed');assert.strictEqual(alerts.element('reminder-notice').hidden,true);
 alerts.context.showReminders([{id:1,text:'起来走走',due:320}]);assert.strictEqual(alerts.element('reminder-notice').hidden,false,'recurring reminder must be shown again at new due time');
 alerts.element('reminder-sound').checked=true;let started,played=false;alerts.context.window.AudioContext=class{constructor(){this.state='running';this.destination={}}resume(){return Promise.resolve()}close(){return Promise.resolve()}decodeAudioData(){return Promise.resolve({})}createBufferSource(){started={connect(){},start(){played=true},stop(){}};return started}};alerts.context.primeReminderSound();await new Promise(setImmediate);
 deliveries.length=0;alerts.context.fetch=async(path,options)=>{deliveries.push({path,body:JSON.parse(options.body)});if(path.endsWith('/audio'))return{ok:true,arrayBuffer:async()=>new ArrayBuffer(44)};return{status:200,json:async()=>({ok:true,reminder:{id:1,text:'起来走走',due:320,lease:'b'.repeat(32)}})}};
 const delivery=alerts.context.deliverReminder(false);await new Promise(setImmediate);assert(played);assert(!deliveries.some(c=>c.path.endsWith('/ack')),'download/start is not completed delivery');started.onended();await delivery;assert.strictEqual(deliveries.at(-1).body.delivery,'played');assert.strictEqual(alerts.mic(),0);
 const packets=[];let Worklet;
 const workletContext={AudioWorkletProcessor:class{constructor(){this.port={postMessage:p=>packets.push(p)}}},registerProcessor:(name,implementation)=>Worklet=implementation,Float32Array};vm.createContext(workletContext);vm.runInContext(fs.readFileSync(__dirname+'/home_web/recorder.js','utf8'),workletContext);
 const worklet=new Worklet();worklet.process([[new Float32Array(256).fill(.2)]]);worklet.port.onmessage({data:'stop'});assert.strictEqual(packets[0].samples.length,256);assert.strictEqual(packets[1].stopped,true);worklet.process([[new Float32Array(256)]]);assert.strictEqual(packets.length,2);
 console.log('Passed frontend: bounded 16kHz WAV conversion; no microphone on load/insecure page; permission refusal; cancel stops capture without upload; retry keeps draft and ID; successful send renders text and playback; worklet flushes and stops; Enter/Ctrl/Command modes, Shift newline, IME protection, busy/repeat guard and saved preference.');
})().catch(error=>{console.error(error);process.exitCode=1});
