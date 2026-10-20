// Private fields travel only through this one-shot endpoint, never chat/storage.
export function createPrivateInput({api}) {
 const $=id=>document.getElementById(id),dialog=$('private-dialog'),form=$('private-form'),fields=$('private-fields'),notice=$('private-notice');
 let stopped=false,timer=null,current=null,lease=null,sending=false,renewed=0,latest=null;
 const dismissed=new Set();
 const erase=()=>{for(const input of fields.querySelectorAll('input,select'))input.value='';fields.replaceChildren();};
 function close(){erase();if(dialog.open)dialog.close();current=null;lease=null;}
 function error(text){$('private-error').textContent=text;}
 function render(request){
  erase();current=request;lease=request.lease;$('private-origin').textContent=request.origin;
  $('private-action').textContent=request.action?'本次可授权点击网站上的“'+request.action+'”，仅限当前页面这一步。':'本次只填入当前页面，由小溪重新观察后继续。';
  for(const field of request.fields){
   const label=document.createElement('label');label.textContent=field.label;
   const input=document.createElement(field.kind==='select'?'select':'input');input.name=field.id;input.required=true;
   input.autocomplete=field.kind==='password'?'new-password':'off';input.spellcheck=false;
   if(field.kind==='select'){
    const blank=document.createElement('option');blank.value='';blank.textContent='请选择';input.append(blank);
    for(const option of field.options){const node=document.createElement('option');node.value=option.id;node.textContent=option.label;input.append(node);}
   }else{input.type=['password','otp'].includes(field.kind)?'password':'text';input.maxLength=1024;if(field.kind==='otp')input.inputMode='numeric';}
   label.append(input);fields.append(label);
  }
  $('private-activate').checked=!!request.action;$('private-activate-row').hidden=!request.action;
  $('private-activate-label').textContent=request.action?'填写后点击“'+request.action+'”并继续此任务':'仅填写';
  $('private-submit').disabled=false;$('private-submit').textContent=request.action?'确认填写并继续':'填入并继续';error('');
  if(!dialog.open)dialog.showModal();fields.querySelector('input,select')?.focus();
 }
 async function open(request){
  if(sending||!request||!['pending','claimed'].includes(request.state))return;
  try{const r=await api('api/private-input/claim',{id:request.id});if(stopped)return;if(r.status!==200)throw Error('另一个设备正在处理，或当前页面已经变化。');renewed=Date.now();render(r.value.request);}
  catch(e){$('private-status').textContent=e.message;}
 }
 async function poll(){
  if(stopped)return;
  try{
   if(!document.hidden){
    const r=await api('api/private-input');if(stopped)return;
    if(r.status===200){
     latest=r.value.request;const pending=latest&&['pending','claimed'].includes(latest.state);
     notice.hidden=!latest||dismissed.has(latest.id)&&!pending;
     $('private-open').hidden=!pending;
     $('private-status').textContent=!latest?'':latest.claimed_elsewhere?'这一步正在另一台设备填写。':pending?'有一步需要你补充信息，填好后小溪会继续。':({queued:'已收到，正在填入网站…',applying:'正在填入当前网站…',filled:'这一页已填写，小溪正在核对并继续。',uncertain:'填写结果需要核对，没有自动重发。请查看实际页面，核对后点“继续任务”。',expired:'私密窗口已过期，请点“继续任务”重新检查当前页面。',cancelled:'本次填写已停止，原任务和页面仍保留。'}[latest.state]||'');
     if(current&&(!latest||latest.id!==current.id||!['pending','claimed'].includes(latest.state))&&!sending)close();
     if(current&&pending&&latest.id===current.id&&Date.now()-renewed>30000){
      const renew=await api('api/private-input/claim',{id:current.id});
      if(renew.status===200){lease=renew.value.request.lease;renewed=Date.now();}else{close();$('private-status').textContent='填写权已变化，请重新打开窗口。';}
     }
     if(pending&&latest.auto_open!==false&&!latest.claimed_elsewhere&&!current&&!dismissed.has(latest.id)&&!sending)await open(latest);
    }
   }
  }catch{/* Preserve no secrets in error text or retry queues. */}
  finally{if(!stopped)timer=setTimeout(poll,2200);}
 }
 async function later(event){
  event?.preventDefault();if(sending)return;
  const old=current,oldLease=lease;if(old)dismissed.add(old.id);close();
  if(old)try{await api('api/private-input/release',{id:old.id,lease:oldLease});}catch{}
 }
 async function submit(event){
  event.preventDefault();if(!current||sending||!form.reportValidity())return;
  const request=current,values={};for(const input of fields.querySelectorAll('input,select'))values[input.name]=input.value;
  const activate=!!request.action&&$('private-activate').checked;
  sending=true;$('private-submit').disabled=true;error('');
  try{
   const result=await api('api/private-input/submit',{id:request.id,lease,values,activate});
   if(result.status!==200||result.value?.state==='uncertain')throw Error('网站、填写权或请求已变化，内容没有自动重发。请重新核对。');
   dismissed.add(request.id);$('private-status').textContent='已收到，正在填入当前网站，完成后自动继续。';close();
  }catch(e){erase();error('提交结果未确认，已清空窗口内容；请先核对任务状态，不要连续重发。');}
  finally{for(const key of Object.keys(values))delete values[key];sending=false;$('private-submit').disabled=false;}
 }
 const opener=()=>{if(latest){dismissed.delete(latest.id);open(latest);}};
 $('private-open').addEventListener('click',opener);$('private-later').addEventListener('click',later);dialog.addEventListener('cancel',later);form.addEventListener('submit',submit);poll();
 return {stop(){stopped=true;clearTimeout(timer);close();$('private-open').removeEventListener('click',opener);$('private-later').removeEventListener('click',later);dialog.removeEventListener('cancel',later);form.removeEventListener('submit',submit);}};
}
