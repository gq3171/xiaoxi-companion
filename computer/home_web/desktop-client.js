import RFB from '/home/novnc/core/rfb.js';

export function createDesktop({api,viewport,status,task,take,resume,placeholder}) {
 let rfb=null,timer=null,stopped=false,connected=false,control=false,serial=0,renewed=0,busy=false,connecting=0,ownershipVersion=0,otherOwner=false,pendingSince=0,renderRevision=-1,renderBlocked=false;
 const screen=document.createElement('div');screen.className='novnc-screen';screen.dataset.input='view';screen.setAttribute('aria-label','小溪正在操作的真实 Linux 桌面');viewport.prepend(screen);
 const input={down:0,up:0,pointerDown:0,pointerUp:0,nonzero:0,click:0,wheel:0,keys:0};let inputVersion=0,reportedInput=-1;
 const inputHandlers=[];
 for(const [event,key] of [['mousedown','down'],['mouseup','up'],['pointerdown','pointerDown'],['pointerup','pointerUp'],['click','click'],['wheel','wheel'],['keydown','keys']]){
  const handler=e=>{if(!control||!connected||renderBlocked)return;input[key]=Math.min(1000000000,input[key]+1);if(event==='mousedown'&&e.buttons)input.nonzero=Math.min(1000000000,input.nonzero+1);inputVersion++;};
  screen.addEventListener(event,handler,{capture:true,passive:true});inputHandlers.push([event,handler]);
 }
 const text=s=>status.textContent=s;
 async function request(action,body={}){const r=await api('api/desktop/control/'+action,body);if(r.status!==200)throw Error(r.value.message||'这一步没有完成，请稍后再试。');return r.value;}
 function disconnect(){serial++;pendingSince=0;renderRevision=-1;renderBlocked=false;if(rfb)rfb.disconnect();rfb=null;connected=false;connecting=0;screen.dataset.input='view';screen.replaceChildren();}
 function connect(writable){
  disconnect();control=writable;connecting=Date.now();const generation=serial;
  screen.dataset.input=writable?'control':'view';take.textContent=writable?'交回小溪':otherOwner?'其他电脑接管中':'接管桌面';
  const url=new URL('/home/api/desktop/ws'+(writable?'?mode=control':''),location.href);url.protocol=location.protocol==='https:'?'wss:':'ws:';
  rfb=new RFB(screen,url.toString(),{enableH264:false});rfb.viewOnly=!writable;rfb.showDotCursor=false;rfb.dragViewport=false;rfb.focusOnClick=true;rfb.scaleViewport=true;rfb.resizeSession=false;rfb.background='#202b37';rfb.qualityLevel=6;rfb.compressionLevel=2;
  text(writable?'正在连接控制桌面…':'正在连接实时桌面…');
  rfb.addEventListener('connect',()=>{if(generation!==serial)return;connected=true;connecting=0;placeholder.hidden=true;text(writable?'你正在接管 · 小溪已暂停':otherOwner?'其他电脑正在接管 · 当前仅观看':'实时桌面 · noVNC');});
  rfb.addEventListener('disconnect',()=>{if(generation!==serial)return;connected=false;connecting=0;text('桌面连接暂时中断，正在重连…');});
  rfb.addEventListener('securityfailure',()=>{if(generation===serial)text('桌面连接未通过校验，请重新连接。');});
 }
 async function tick(){
  if(stopped)return;
  const version=ownershipVersion;
  try{
   if(busy)return;
   const r=await api('api/desktop/session');
   // A poll sent before take/return must never replace the acknowledged owner.
   if(stopped||busy||version!==ownershipVersion)return;
   if(r.status!==200)throw Error('桌面暂时未连接');const s=r.value;
   const t=s.task;task.textContent=s.phase==='waiting_user'?'需要你完成当前步骤：'+s.message:s.phase==='interrupted'?'任务已中断，页面仍保留；核对后可继续。':t?(t.state==='succeeded'?'最近完成：':'当前任务：')+t.goal:'小溪的专用电脑已准备好。';
   otherOwner=s.control_busy===true;take.disabled=otherOwner;take.textContent=s.control?'交回小溪':otherOwner?'其他电脑接管中':'接管桌面';resume.hidden=!s.job_id||s.control||!['waiting_user','interrupted'].includes(s.phase);resume.dataset.job=s.job_id||'';
   if(s.control&&(Date.now()-renewed>30000||inputVersion!==reportedInput&&Date.now()-renewed>5000)){const version=inputVersion;await request('renew',version!==reportedInput?{input:{...input,connected:connected?1:0}}:{});renewed=Date.now();reportedInput=version;}
   if(stopped||busy||version!==ownershipVersion)return;
   if(s.ready){if(!rfb||(!connected&&Date.now()-connecting>15000)||control!==s.control||connected&&s.control&&s.control_connected===false)connect(s.control===true);}else{text('桌面正在准备…');placeholder.hidden=false;}
   if(connected&&rfb){
    const drawing=rfb.renderingState;
    if(document.hidden||!drawing?.pending||drawing.revision!==renderRevision){pendingSince=0;renderBlocked=false;}
    else if(!pendingSince)pendingSince=Date.now();
    renderRevision=drawing?.revision;
    if(pendingSince&&Date.now()-pendingSince>4000)renderBlocked=true;
    // An open socket is not proof that its queued images have been painted.
    // Block input on the stale picture; reconnect without replaying clicks.
    rfb.viewOnly=!control||renderBlocked;
    if(pendingSince&&Date.now()-pendingSince>8000){connect(s.control===true);return;}
   }
   if(connected&&renderBlocked)text('画面刷新停住，正在恢复…');
   else if(connected)text(s.control?'你正在接管 · 小溪已暂停':otherOwner?'其他电脑正在接管 · 当前仅观看':s.phase==='waiting_user'?'等待你处理 · 可接管桌面':s.phase==='interrupted'?'任务已中断 · 可核对后继续':'实时桌面 · noVNC');
  }catch(e){if(!stopped&&version===ownershipVersion)text(e.message||'桌面正在重新连接…');}
  finally{if(!stopped)timer=setTimeout(tick,1800);}
 }
 async function toggle(){
  if(busy)return;busy=true;ownershipVersion++;take.disabled=true;
  try{
   const s=await request(control?'return':'take');if(stopped)return;
   ownershipVersion++;otherOwner=s.control_busy===true;renewed=Date.now();resume.hidden=true;connect(s.control===true);
  }catch(e){if(!stopped)text(e.message);}finally{busy=false;if(!stopped)take.disabled=false;}
 }
 async function continueTask(){if(busy)return;busy=true;ownershipVersion++;try{await request('resume',{job_id:resume.dataset.job});if(!stopped)text('小溪正在核对当前页面，再继续任务。');}catch(e){if(!stopped)text(e.message);}finally{busy=false;}}
 const visible=()=>{if(!document.hidden&&rfb)disconnect();};
 document.addEventListener('visibilitychange',visible);
 take.addEventListener('click',toggle);resume.addEventListener('click',continueTask);tick();
 return {stop(){stopped=true;ownershipVersion++;clearTimeout(timer);document.removeEventListener('visibilitychange',visible);disconnect();take.removeEventListener('click',toggle);resume.removeEventListener('click',continueTask);for(const [event,handler] of inputHandlers)screen.removeEventListener(event,handler,true);screen.remove();},reconnect(){disconnect();}};
}
