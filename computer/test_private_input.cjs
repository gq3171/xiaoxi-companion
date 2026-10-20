const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
class Element{
 constructor(tag='div'){this.tag=tag;this.children=[];this.listeners={};this.value='';this.hidden=false;this.open=false;this.checked=false;}
 append(e){this.children.push(e)}replaceChildren(){this.children=[]}focus(){}showModal(){this.open=true}close(){this.open=false}
 addEventListener(k,f){this.listeners[k]=f}removeEventListener(k){delete this.listeners[k]}
 querySelectorAll(){return this.children.flatMap(c=>['input','select'].includes(c.tag)?[c]:c.querySelectorAll())}
 querySelector(){return this.querySelectorAll()[0]||null}reportValidity(){return true}
}
const elements=new Map(),timers=[],calls=[],$=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id)};
let request={id:'a'.repeat(32),job_id:'b'.repeat(32),state:'pending',origin:'https://example.invalid',action:'下一步',fields:[{id:'account',kind:'account',label:'邮箱'},{id:'password',kind:'password',label:'密码'}]},failed=false;
const api=async(path,body)=>{calls.push({path,body});if(path.endsWith('/claim'))return{status:200,value:{ok:true,request:{...request,lease:'c'.repeat(32)}}};if(path.endsWith('/submit')){if(failed)throw Error('network');request={...request,state:'queued'};return{status:200,value:{ok:true}}}return{status:200,value:{request}}};
const context={document:{hidden:false,getElementById:$,createElement:tag=>new Element(tag)},Date,Error,Set,Object,setTimeout:fn=>(timers.push(fn),timers.length),clearTimeout(){}};
vm.createContext(context);vm.runInContext(fs.readFileSync(__dirname+'/home_web/private-input.js','utf8').replace('export function createPrivateInput','function createPrivateInput'),context);
const flush=()=>new Promise(setImmediate);
(async()=>{
 const client=context.createPrivateInput({api});await flush();assert.equal($('private-dialog').open,true);assert.equal($('private-origin').textContent,'https://example.invalid');
 let fields=$('private-fields').querySelectorAll();assert.equal(fields.length,2);assert.equal(fields[1].type,'password');
 fields[0].value='synthetic@example.invalid';fields[1].value='SYNTHETIC_ONLY_PASSWORD';$('private-activate').checked=true;
 await $('private-form').listeners.submit({preventDefault(){}});
 const sent=calls.find(c=>c.path.endsWith('/submit'));assert.equal(sent.body.values.password,undefined,'temporary submission dictionary must be cleared after transport');
 assert.equal(sent.body.activate,true);assert.equal($('private-dialog').open,false);assert.equal($('private-fields').querySelectorAll().length,0);
 assert(calls.every(c=>c.path.startsWith('api/private-input')),'no private value travels through chat');
 request={...request,id:'e'.repeat(32),state:'pending',auto_open:false};await timers.shift()();assert.equal($('private-dialog').open,false,'another browser task must not auto-claim input');await $('private-open').listeners.click();assert.equal($('private-dialog').open,true);await $('private-later').listeners.click({preventDefault(){}});
 request={...request,id:'d'.repeat(32),state:'pending',auto_open:true};await timers.shift()();assert.equal($('private-dialog').open,true);
 fields=$('private-fields').querySelectorAll();fields[0].value='x';fields[1].value='FAILED_SUBMISSION_SENTINEL';failed=true;
 await $('private-form').listeners.submit({preventDefault(){}});assert.equal($('private-fields').querySelectorAll().length,0);assert.match($('private-error').textContent,/未确认/);
 const attempts=calls.filter(c=>c.path.endsWith('/submit')).length;await timers.shift()();assert.equal(calls.filter(c=>c.path.endsWith('/submit')).length,attempts,'network uncertainty never retries credentials');
 client.stop();assert.equal($('private-dialog').open,false);assert.equal($('private-form').listeners.submit,undefined);
 assert(!/localStorage|sessionStorage|api\/chat/.test(fs.readFileSync(__dirname+'/home_web/private-input.js','utf8')));
 console.log('Passed private form UI: proactive popup, origin/action review, masked input, dedicated transport, erase on success/failure, no secret retry or storage, cleanup.');
})().catch(error=>{console.error(error);process.exitCode=1});
