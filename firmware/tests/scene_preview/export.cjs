const fs=require('fs'),path=require('path'),sharp=require('sharp');
const input=path.resolve(process.argv[2]||'firmware/build/scene-preview');
const output=path.resolve(process.argv[3]||'firmware/assets/character');
const names=['idle','listen','speak','think','drag','night','menu','reader','symbols','near','far','bed','wash','work','wake_hint','awake','wake_reply','voices','voice_options','voice_selected','voice_closed','wifi_weak','wifi_medium','wifi_connecting','wifi_offline'];
(async()=>{
 fs.mkdirSync(output,{recursive:true});let tiles=[];
 for(let j=0;j<names.length;j++){
  const raw=fs.readFileSync(path.join(input,names[j]+'.rgb565')),rgb=Buffer.alloc(480*480*3);
  if(raw.length!==480*480*2)throw Error('invalid framebuffer');
  for(let i=0;i<480*480;i++){
   const c=raw.readUInt16LE(i*2);
   rgb[i*3]=Math.round(((c>>11)&31)*255/31);rgb[i*3+1]=Math.round(((c>>5)&63)*255/63);rgb[i*3+2]=Math.round((c&31)*255/31);
  }
  const png=await sharp(rgb,{raw:{width:480,height:480,channels:3}}).png().toBuffer();
  fs.writeFileSync(path.join(output,'lvgl-'+names[j]+'.png'),png);
  tiles.push({input:png,left:j%4*480,top:Math.floor(j/4)*480});
 }
 await sharp({create:{width:1920,height:Math.ceil(names.length/4)*480,channels:3,background:'#23212b'}}).composite(tiles).png().toFile(path.join(output,'lvgl-contact-sheet.png'));
 console.log(names.length+' views exported from actual firmware LVGL rendering.');
})().catch(e=>{console.error(e.message);process.exitCode=1;});
