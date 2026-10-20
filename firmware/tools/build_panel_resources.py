"""Export existing bitmaps losslessly; no artwork/font rasterization changes."""
from pathlib import Path
import re,json,hashlib,struct,zlib
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/panel-resources'
GEN=ROOT/'main/panel'

def clean(s):return re.sub(r'/\*.*?\*/|//[^\n]*','',s,flags=re.S)
def nums(s):return [int(x,0) for x in re.findall(r'0x[0-9a-fA-F]+|\b\d+\b',clean(s))]
def arrays(s):return {m[1]:bytes(nums(m[2])) for m in re.finditer(r'const uint8_t (\w+)\[[^\]]*\]\s*=\s*\{(.*?)\};',s,re.S)}
def array(name,data):
 return 'static const uint8_t '+name+'[]={\n'+''.join(' '+','.join(str(x) for x in data[i:i+32])+',\n' for i in range(0,len(data),32))+'};\n'
def sha(b):return hashlib.sha256(b).hexdigest()
def cache_image(kind,data):
 prefix=struct.pack('<8sIIII32s',b'PXRES01\0',1,kind,len(data),1,hashlib.sha256(data).digest())
 return prefix+struct.pack('<I4x',zlib.crc32(prefix))+b'\xff'*(4096-64)+data

def main():
 OUT.mkdir(parents=True,exist_ok=True);GEN.mkdir(exist_ok=True)
 art=(ROOT/'main/character/pet_character_assets.c').read_text();a=arrays(art)
 art_manifest=json.loads((ROOT/'assets/character/manifest.json').read_text());names=[f['name'] for f in art_manifest['frames']]
 assert len(names)==52
 payload=bytearray();frames=[];locations={}
 for f in art_manifest['frames']:
  name=f.get('alias',f['name'])
  if name not in locations:
   while len(payload)%4:payload.append(0)
   pal=len(payload);payload+=a[name+'_palette'];pixel=len(payload);payload+=a[name+'_pixels'];locations[name]=(pal,pixel,len(a[name+'_pixels']))
  frames.append((*locations[name],bool(f.get('mirror',False))))
 while len(payload)%4:payload.append(0)
 room=len(payload);payload+=a['room_pixels']
 while len(payload)%4:payload.append(0)
 yard=len(payload);payload+=a['yard_pixels'];artdata=bytes(payload)
 assert len(artdata)+4096<=0xc0000,'art must fit either committed bank'
 font=(ROOT/'main/fonts/pet_font_cn_16.c').read_text()
 bitmap_start=font.index('static LV_ATTRIBUTE_LARGE_CONST const uint8_t glyph_bitmap[]')
 bitmap_end=font.index('};',bitmap_start)+2
 bitmap=bytes(nums(font[font.index('{',bitmap_start)+1:bitmap_end-2]))
 dsc_start=font.index('static const lv_font_fmt_txt_glyph_dsc_t glyph_dsc[]')
 dsc_end=font.index('};',dsc_start)+2
 descriptors=[dict((k,int(v)) for k,v in re.findall(r'\.(\w+)\s*=\s*(-?\d+)',m)) for m in re.findall(r'\{([^}]+)\}',font[dsc_start:dsc_end])]
 assert len(descriptors)>20000
 map_start=font.index('static const lv_font_fmt_txt_cmap_t cmaps[]');map_end=font.index('};',map_start)+2
 intarrays={m[1]:nums(m[2]) for m in re.finditer(r'const uint(?:8|16)_t (\w+)\[[^\]]*\]\s*=\s*\{(.*?)\};',font[dsc_end:map_start],re.S)}
 glyphs={}
 for body in re.findall(r'\{([^}]+)\}',font[map_start:map_end]):
  fields=dict(re.findall(r'\.(\w+)\s*=\s*([^,}\n]+)',body))
  start=int(fields['range_start']);length=int(fields['range_length']);gid=int(fields['glyph_id_start'])
  ofs=fields.get('glyph_id_ofs_list','NULL').strip();unicodes=fields.get('unicode_list','NULL').strip();typ=fields['type'].strip()
  for relative in range(length):
   if 'SPARSE' in typ:
    if relative not in intarrays[unicodes]:continue
    index=intarrays[unicodes].index(relative)
   else:index=relative
   g=gid+(intarrays[ofs][index] if ofs!='NULL' else index)
   if g and g<len(descriptors):glyphs[start+relative]=g
 chars=set(range(32,127))
 for f in (ROOT/'main').glob('*.c'):
  if f.name in ('pet_face.c','pet_setup.c','pet_birth.c','pet_controls.c','pet_hardware.c','pet_home.c','pet_screen.c','pet_runtime.c','pet_voice.c','pet_tts.c'):
   source=clean(f.read_text())
   for text in re.findall(r'"((?:\\.|[^"\\])*)"',source):chars.update(ord(ch) for ch in text if ord(ch)>=128)
 chars.update(map(ord,'小溪小西请稍等正在恢复房间网络暂时不可用设置返回确定取消资源'))
 chars=sorted(c for c in chars if c in glyphs)
 small=bytearray();entries=[dict(bitmap_index=0,adv_w=0,box_w=0,box_h=0,ofs_x=0,ofs_y=0)]
 for cp in chars:
  g=glyphs[cp];d=dict(descriptors[g]);end=descriptors[g+1]['bitmap_index'] if g+1<len(descriptors) else len(bitmap)
  assert end>=d['bitmap_index'];blob=bitmap[d['bitmap_index']:end];d['bitmap_index']=len(small);small+=blob;entries.append(d)
 # Keep the full metric/cmap tables so cached glyph indices never depend on CPU ABI.
 fullmeta=font[dsc_start:map_end]
 dsc=lambda ds:'{'+','.join('.'+k+'='+str(v) for k,v in ds.items())+'}'
 source='#include "lvgl.h"\n#include "fonts/pet_font_symbols_16.h"\n#include "pet_panel.h"\n'+fullmeta+'\n'
 source+=array('small_bitmap',small)
 source+='static const lv_font_fmt_txt_glyph_dsc_t small_dsc[]={\n'+',\n'.join(dsc(d) for d in entries)+'\n};\n'
 source+='static const uint16_t small_unicode[]={'+','.join(str(c-32) for c in chars)+'};\n'
 source+='static const lv_font_fmt_txt_cmap_t small_cmap[]={ {.range_start=32,.range_length=65504,.glyph_id_start=1,.unicode_list=small_unicode,.glyph_id_ofs_list=NULL,.list_length='+str(len(chars))+',.type=LV_FONT_FMT_TXT_CMAP_SPARSE_TINY} };\n'
 source+='static const lv_font_fmt_txt_dsc_t small_font_dsc={.glyph_bitmap=small_bitmap,.glyph_dsc=small_dsc,.cmaps=small_cmap,.cmap_num=1,.bpp=2,.bitmap_format=1};\n'
 source+='static lv_font_fmt_txt_dsc_t full_font_dsc={.glyph_dsc=glyph_dsc,.cmaps=cmaps,.cmap_num=86,.bpp=2,.bitmap_format=1};\n'
 common='.get_glyph_dsc=lv_font_get_glyph_dsc_fmt_txt,.get_glyph_bitmap=lv_font_get_bitmap_fmt_txt,.line_height=31,.base_line=9,.subpx=LV_FONT_SUBPX_NONE,.underline_position=-2,.underline_thickness=1'
 source+='static const lv_font_t small_font={'+common+',.dsc=&small_font_dsc,.fallback=&pet_font_symbols_16};\n'
 source+='static bool full_glyph(const lv_font_t*f,lv_font_glyph_dsc_t*d,uint32_t c,uint32_t n){return full_font_dsc.glyph_bitmap&&lv_font_get_glyph_dsc_fmt_txt(f,d,c,n);}\n'
 source+='const lv_font_t pet_font_cn_16={'+common.replace('.get_glyph_dsc=lv_font_get_glyph_dsc_fmt_txt','.get_glyph_dsc=full_glyph')+',.dsc=&full_font_dsc,.fallback=&small_font};\n'
 source+='bool pet_panel_font_bind(const uint8_t*p,size_t n){if(!p||n!='+str(len(bitmap))+')return false;full_font_dsc.glyph_bitmap=p;return true;}\n'
 (GEN/'pet_panel_font.c').write_text(source)
 source='#include "pet_panel.h"\n#include "character/pet_character_assets.h"\n'+array('idle_palette',a['idle_palette'])+array('idle_pixels',a['idle_pixels'])+array('room_pixels',a['room_pixels'])
 source+='const pet_character_frame_t pet_character_frames[PET_ART_COUNT] = {\n'+',\n'.join(' {idle_palette,idle_pixels,sizeof(idle_pixels)}' for _ in names)+'\n};\n'
 source+='const uint8_t *const pet_room_compressed=room_pixels;\nconst size_t pet_room_compressed_size=sizeof(room_pixels);\n'
 source+='static pet_character_frame_t remote_frames[PET_ART_COUNT];\nstatic const uint8_t*remote_room,*remote_yard;\n'
 source+='const pet_character_frame_t *pet_panel_frame(unsigned pose){if(pose>=PET_ART_COUNT||(!remote_room&&pose>=PET_ART_CAT_IDLE))return NULL;return remote_room?&remote_frames[pose]:&pet_character_frames[pose];}\n'
 source+='const uint8_t *pet_panel_room(size_t*n){*n='+str(len(a['room_pixels']))+';return remote_room?remote_room:room_pixels;}\n'
 source+='const uint8_t *const pet_yard_compressed=NULL;\nconst size_t pet_yard_compressed_size=0;\nconst uint8_t *pet_panel_yard(size_t*n){*n=remote_yard?'+str(len(a['yard_pixels']))+':0;return remote_yard;}\n'
 source+='bool pet_panel_art_bind(const uint8_t*p,size_t n){if(!p||n!='+str(len(artdata))+')return false;\n'
 for i,(pal,pixel,length,mirror) in enumerate(frames):source+=f' remote_frames[{i}]=(pet_character_frame_t){{p+{pal},p+{pixel},{length},{str(mirror).lower()}}};\n'
 source+=f' remote_room=p+{room};remote_yard=p+{yard};return true;}}\n'
 (GEN/'pet_panel_art.c').write_text(source)
 meta={'version':1,'frame_names':names,'frames':frames,'rooms':{'home':{'offset':room,'bytes':len(a['room_pixels'])},'yard':{'offset':yard,'bytes':len(a['yard_pixels'])}},'font':{'sha256':sha(bitmap),'bytes':len(bitmap),'kind':1},'art':{'sha256':sha(artdata),'bytes':len(artdata),'kind':2},'fallback_glyphs':len(chars),'fallback_bitmap_bytes':len(small),'fallback_art_bytes':sum(len(a[x]) for x in ('idle_palette','idle_pixels','room_pixels')),'source_font_sha256':sha(font.encode()),'source_art_sha256':sha(art.encode())}
 for name,data,kind in [('font',bitmap,1),('art',artdata,2)]:
  (OUT/(meta[name]['sha256']+'.bin')).write_bytes(data);(OUT/(name+'-cache.bin')).write_bytes(cache_image(kind,data))
 header='#pragma once\n'
 for name in ('font','art'):header+=f'#define PET_PANEL_{name.upper()}_SIZE {meta[name]["bytes"]}u\n#define PET_PANEL_{name.upper()}_SHA "{meta[name]["sha256"]}"\n'
 (GEN/'pet_panel_manifest.h').write_text(header)
 (OUT/'manifest.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(meta))
if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);args=parser.parse_args()
 if args.output:OUT=args.output
 main()
