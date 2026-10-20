// Exercise connection timing and ownership feedback without a browser or network.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const clients=[],timers=[],elements=[];const requests=[];let deferredPoll=null;let now=1000,state={ready:true,phase:'running',control:false};
class Element{constructor(){this.listeners={};this.dataset={};}prepend(){}setAttribute(){}replaceChildren(){}remove(){}addEventListener(k,f){this.listeners[k]=f;}removeEventListener(k){delete this.listeners[k];}}
class RFB{constructor(target,url,options){this.listeners={};this.options=options;clients.push(this);}addEventListener(k,f){this.listeners[k]=f;}disconnect(){this.listeners.disconnect?.();}}
const context={RFB,document:{listeners:{},hidden:false,addEventListener(k,f){this.listeners[k]=f;},removeEventListener(k){delete this.listeners[k];},createElement:()=>{const e=new Element();elements.push(e);return e;}},URL,location:{href:'https://xiaoxi.example:8791/home/',protocol:'https:'},Date:{now:()=>now},setTimeout:f=>(timers.push(f),timers.length),clearTimeout(){},Error};
vm.createContext(context);vm.runInContext(fs.readFileSync(__dirname+'/home_web/desktop-client.js','utf8').replace(/^import .*;\n/,'').replace('export function createDesktop','function createDesktop'),context);
const status=new Element(),task=new Element(),take=new Element(),resume=new Element(),placeholder=new Element();
const api=async (path,body)=>{requests.push({path,body});if(path.endsWith('/session')&&deferredPoll)return deferredPoll;if(path.endsWith('/take'))state={...state,control:true};if(path.endsWith('/return'))state={...state,control:false};return {status:200,value:state};};
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 const ui=context.createDesktop({api,viewport:new Element(),status,task,take,resume,placeholder});await flush();assert.equal(clients.length,1);assert.equal(elements[0].dataset.input,'view');assert.equal(clients[0].showDotCursor,false);assert.equal(clients[0].options.enableH264,false);
 now+=1800;await timers.shift()();assert.equal(clients.length,1,'slow initial handshake must not reconnect every poll');
 clients[0].listeners.connect();assert.equal(status.textContent,'实时桌面 · noVNC');
 state.phase='waiting_user';now+=1800;await timers.shift()();assert.equal(status.textContent,'等待你处理 · 可接管桌面');
 state.phase='running';now+=1800;await timers.shift()();assert.equal(status.textContent,'实时桌面 · noVNC','hand-back feedback must clear after resume');
 await take.listeners.click();assert.equal(clients.length,2);assert.equal(clients[1].viewOnly,false);assert.equal(take.textContent,'交回小溪');assert.equal(elements[0].dataset.input,'control');clients[1].listeners.connect();assert.equal(status.textContent,'你正在接管 · 小溪已暂停');
 await take.listeners.click();assert.equal(clients.at(-1).viewOnly,true);
 // Hold a read-only poll across a successful takeover. Its late reply must be discarded.
 let resolve;deferredPoll=new Promise(r=>resolve=r);const lateReadOnly=timers.shift()();await flush();
 await take.listeners.click();const controlled=clients.at(-1);assert.equal(controlled.viewOnly,false);
 deferredPoll=null;resolve({status:200,value:{...state,control:false}});await lateReadOnly;
 assert.equal(clients.at(-1),controlled);assert.equal(elements[0].dataset.input,'control');assert.equal(take.textContent,'交回小溪');
 // And vice versa: a late control poll must not undo a hand-back.
 deferredPoll=new Promise(r=>resolve=r);const lateControl=timers.shift()();await flush();
 await take.listeners.click();const viewer=clients.at(-1);assert.equal(viewer.viewOnly,true);
 deferredPoll=null;resolve({status:200,value:{...state,control:true}});await lateControl;
 assert.equal(clients.at(-1),viewer);assert.equal(elements[0].dataset.input,'view');assert.equal(take.textContent,'接管桌面');
 // Local counters contain no text/keys/coordinates and travel only under the existing lease renewal.
 await take.listeners.click();clients.at(-1).listeners.connect();
 elements[0].listeners.mousedown({buttons:1,clientX:999,key:'private'});elements[0].listeners.mouseup({buttons:0});
 elements[0].listeners.keydown({key:'private'});now+=6000;await timers.shift()();
 const counters=requests.filter(r=>r.path.endsWith('/renew')).at(-1).body.input;
 assert.equal(counters.down,1);assert.equal(counters.up,1);assert.equal(counters.nonzero,1);assert.equal(counters.keys,1);assert.equal(counters.connected,1);
 assert.equal('key' in counters,false);assert.equal('clientX' in counters,false);
 // A browser can retain a stale open WebSocket; server-side channel loss must reconnect it.
 const stale=clients.at(-1);state.control_connected=false;now+=1800;await timers.shift()();
 assert.notEqual(clients.at(-1),stale);assert.equal(clients.at(-1).viewOnly,false);assert.equal(status.textContent,'正在连接控制桌面…');
 state.control_connected=true;clients.at(-1).listeners.connect();now+=1800;const live=clients.at(-1);await timers.shift()();assert.equal(clients.at(-1),live);
 // A decoder queue can stall while its WebSocket still looks connected.
 live.renderingState={pending:true,revision:1};now+=1800;await timers.shift()();
 now+=1800;await timers.shift()();now+=4500;await timers.shift()();
 assert.equal(live.viewOnly,true);assert.match(status.textContent,/画面刷新停住/);
 now+=4500;await timers.shift()();assert.notEqual(clients.at(-1),live,'stuck paint queue must reconnect, keeping the existing control lease');
 assert.equal(clients.at(-1).viewOnly,false);clients.at(-1).listeners.connect();
 const healthy=clients.at(-1);healthy.renderingState={pending:true,revision:1};
 for(let i=0;i<8;i++){healthy.renderingState.revision++;now+=1800;await timers.shift()();}
 assert.equal(clients.at(-1),healthy,'a busy but progressing render queue is healthy');
 healthy.renderingState.pending=false;now+=60000;await timers.shift()();assert.equal(clients.at(-1),healthy,'static desktop must not trigger reconnect');
 // Returning from a throttled/background tab obtains a new full framebuffer.
 context.document.hidden=true;context.document.listeners.visibilitychange();assert.equal(clients.at(-1),healthy);
 context.document.hidden=false;context.document.listeners.visibilitychange();now+=1800;await timers.shift()();
 assert.notEqual(clients.at(-1),healthy);assert.equal(clients.at(-1).viewOnly,false);clients.at(-1).listeners.connect();
 await take.listeners.click();clients.at(-1).listeners.connect();state.control_busy=true;now+=1800;await timers.shift()();
 assert.equal(take.disabled,true);assert.equal(take.textContent,'其他电脑接管中');assert.equal(status.textContent,'其他电脑正在接管 · 当前仅观看');
 ui.stop();assert.equal(take.listeners.click,undefined);assert.equal(context.document.listeners.visibilitychange,undefined);assert.equal(elements[0].listeners.mousedown,undefined);
 console.log('Passed noVNC UI: slow handshake, pause/resume status, explicit takeover/return, stale ownership polls, cursor fallback and cleanup.');
})().catch(e=>{console.error(e);process.exitCode=1;});
