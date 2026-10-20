"""Provision the name recognizer without touching existing partition boundaries.

Requires a fresh full live backup made immediately before this operation.
Writes only the reviewed app and reserved model range; never uses erase_flash.
Private backup/app contain credentials and must not be shared.
"""
import argparse,hashlib,json,os,struct,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--port',required=True);p.add_argument('--backup',type=Path,required=True);a=p.parse_args()
b=a.backup.read_bytes();assert len(b)==0x1000000,'Need complete 16MiB live backup'
os.chmod(a.backup,0o600)
model=root/'models/pet_name_wake.bin';manifest=json.loads((root/'models/pet_name_wake_manifest.json').read_text());raw=model.read_bytes()
assert len(raw)==manifest['packed_bytes'] and hashlib.sha256(raw).hexdigest()==manifest['sha256']
assert len(raw)<=0x300000
regions=[]
for offset in range(0x8000,0x8c00,32):
 magic,typ,sub,start,size,label,flags=struct.unpack('<HBBII16sI',b[offset:offset+32])
 if magic!=0x50aa:break
 regions.append((typ,sub,start,size))
 assert not(start<0xd00000 and start+size>0xa00000),'Model overlaps a real partition'
assert (0,0,0x10000,0x800000) in regions,'Unexpected application layout'
app=root/'build/deskpet.bin';assert 0<app.stat().st_size<=0x800000
oldapp=a.backup.parent/'application-before.bin';oldapp.write_bytes(b[0x10000:0x810000]);os.chmod(oldapp,0o600)
report={'backup_bytes':len(b),'backup_sha256':hashlib.sha256(b).hexdigest(),'model_sha256':manifest['sha256'],'model_offset':'0xA00000','model_bytes':len(raw),'application_offset':'0x10000','application_bytes':app.stat().st_size,'partitions_unchanged':True}
(a.backup.parent/'provision.json').write_text(json.dumps(report,indent=2)+'\n')
cmd=[sys.executable,'-m','esptool','--chip','esp32s3','--port',a.port,'--baud','460800','--before','default-reset','--after','no-reset','write-flash','--flash-mode','dio','--flash-freq','80m','--flash-size','16MB','0x10000',str(app),'0xA00000',str(model)]
with (root/'build/flash-name-wake.log').open('w') as log:subprocess.run(cmd,check=True,stdout=log,stderr=subprocess.STDOUT)
print('Application and name model written; existing partition table/NVS/SPIFFS were not written.')
