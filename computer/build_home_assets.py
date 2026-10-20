"""Export the existing exact panel palette/RGB565 assets for browser Canvas."""
import argparse,hashlib,json,re,zlib
from pathlib import Path
from PIL import Image

def build(root,out,resources=None):
    root,out=Path(root),Path(out);out.mkdir(parents=True,exist_ok=True)
    resources=Path(resources) if resources else root/'firmware/build/panel-resources'
    manifest=json.loads((resources/'manifest.json').read_text())
    assert hashlib.sha256((root/'firmware/main/character/pet_character_assets.c').read_bytes()).hexdigest()==manifest['source_art_sha256'],'rebuild panel resources from current art first'
    data=(resources/(manifest['art']['sha256']+'.bin')).read_bytes()
    assert hashlib.sha256(data).hexdigest()==manifest['art']['sha256']
    source=(root/'firmware/main/panel/pet_panel_art.c').read_text()
    names=manifest['frame_names'];frames=manifest['frames']
    assert len(frames)==len(names)
    for name,(palette,pixels,size,mirror) in zip(names,frames):
        a,b,n=map(int,(palette,pixels,size));indices=zlib.decompress(data[b:b+n]);assert len(indices)==208*264
        rgba=bytearray()
        for index in indices:
            blue,green,red,alpha=data[a+index*4:a+index*4+4]
            rgba.extend(((red>>3)*255//31,(green>>2)*255//63,(blue>>3)*255//31,alpha))
        image=Image.frombytes('RGBA',(208,264),bytes(rgba))
        if mirror:image=image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        image.save(out/(name+'.png'))
    for label,key in [('room','home'),('yard','yard')]:
        room=manifest['rooms'][key];pixels=zlib.decompress(data[room['offset']:room['offset']+room['bytes']]);assert len(pixels)==320*320*2
        import struct
        src=struct.unpack('<'+str(320*320)+'H',pixels);expanded=[]
        for y in range(480):
            sy,fy=divmod(y*2,3);ny=min(319,sy+1)
            for x in range(480):
                sx,fx=divmod(x*2,3);nx=min(319,sx+1)
                a,b,c,d=src[sy*320+sx],src[sy*320+nx],src[ny*320+sx],src[ny*320+nx]
                value=0
                for shift,mask in [(11,31),(5,63),(0,31)]:
                    channel=(((a>>shift)&mask)*(3-fx)*(3-fy)+((b>>shift)&mask)*fx*(3-fy)+((c>>shift)&mask)*(3-fx)*fy+((d>>shift)&mask)*fx*fy+4)//9
                    value|=channel<<shift
                expanded.append(value)
        pixels=struct.pack('<'+str(480*480)+'H',*expanded)
        rgb=bytearray()
        for i in range(0,len(pixels),2):
            value=pixels[i]|pixels[i+1]<<8;rgb.extend((((value>>11)&31)*255//31,((value>>5)&63)*255//63,(value&31)*255//31))
        Image.frombytes('RGB',(480,480),bytes(rgb)).save(out/(label+'.png'))
    constants=dict((k,int(v)) for k,v in re.findall(r'#define (PET_BED_\w+) (\d+)',(root/'firmware/main/pet_home.h').read_text()))
    cover=[36,constants['PET_BED_COVER_Y'],constants['PET_BED_COVER_W'],constants['PET_BED_COVER_H']]
    spots=[dict(name='床',action='rest',box=[26,144,174,124],mask=[36,208,156,60],sleep_mask=cover,front_y=268),dict(name='洗漱台',action='wash',box=[391,228,83,137],mask=[396,286,77,73],front_y=365),dict(name='电脑工作台',action='work',box=[248,115,168,124],mask=[303,207,55,32],front_y=239),dict(name='窗边',action='window',box=[15,40,182,114],mask=[0,0,0,0],front_y=200)]
    (out/'manifest.json').write_text(json.dumps(dict(version=1,source_sha256=manifest['art']['sha256'],frames=names,rooms=['room','yard'],spots=spots),ensure_ascii=False,indent=2)+'\n')
    return len(frames)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output');p.add_argument('--resources',type=Path);a=p.parse_args();print('exported frames',build(Path(__file__).resolve().parent.parent,a.output,a.resources))
