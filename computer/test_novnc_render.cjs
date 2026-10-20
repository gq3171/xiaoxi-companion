// Exercise the installed codec negotiation and visible-paint progress without pixels or a GPU.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=__dirname+'/vendor/novnc/core/';
const encodings={};for(const m of fs.readFileSync(root+'encodings.js','utf8').matchAll(/(\w+): (0x[\da-f]+|-?\d+)/g))encodings[m[1]]=Number(m[2]);
assert.equal(encodings.encodingH264,50);
const context={EventTargetMixin:class{},encodings,supportsWebCodecsH264Decode:true,Log:{Debug(){},Warn(){},Error(){}},navigator:{userAgent:'test'}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(root+'rfb.js','utf8').replace(/^import[\s\S]*?;\n/gm,'').replace('export default class RFB','class RFB')+'\nthis.RFB=RFB;',context);
let sent;context.RFB.messages.clientEncodings=(_,values)=>sent=Array.from(values);
const peer={_enableH264:false,_fbDepth:24,_qualityLevel:6,_compressionLevel:2};
context.RFB.prototype._sendEncodings.call(peer);assert.equal(sent.includes(50),false);assert.ok(sent.includes(encodings.encodingTight));assert.ok(sent.includes(encodings.encodingZRLE));assert.ok(sent.includes(encodings.encodingRaw));
peer._enableH264=true;context.RFB.prototype._sendEncodings.call(peer);assert.ok(sent.includes(50),'vendor default remains compatible for other callers');
let paints=0;const ctx={drawImage(){paints++;}},canvas=()=>({width:100,height:100,getContext:()=>ctx,style:{}});
context.document={createElement:canvas};vm.runInContext(fs.readFileSync(root+'display.js','utf8').replace(/^import[\s\S]*?;\n/gm,'').replace('export default class Display','class Display')+'\nthis.Display=Display;',context);
const display=new context.Display(canvas());display._damageBounds={left:0,top:0,right:100,bottom:100};display.flip();assert.equal(display.renderRevision,1);assert.equal(paints,1);
// Reproduce a stuck decode queue: requesting flip cannot count as painting.
const img={complete:true,width:0,height:0};display._renderQPush({type:'img',img,width:10,height:10,x:0,y:0});display.flip();
assert.equal(display.pending(),true);assert.equal(display.renderRevision,1);
const state=Object.getOwnPropertyDescriptor(context.RFB.prototype,'renderingState').get.call({_display:display});assert.equal(state.pending,true);assert.equal(state.revision,1);
img.width=10;img.height=10;display._scanRenderQ();assert.equal(display.pending(),false);assert.equal(display.renderRevision,2);
console.log('Passed real noVNC: H264 opt-out, Tight/ZRLE/Raw fallback, visible-paint revision, stalled/recovered decode queue.');
