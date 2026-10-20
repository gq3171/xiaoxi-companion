"""Pack unmodified Espressif MultiNet5 Chinese weights for reserved flash range.

Run with PYTHONPATH=firmware/build/wake-tools; pypinyin is a build tool only.
The generated Han pronunciation table uses pypinyin (MIT); default readings
are not a promise of correctly resolving every personal-name polyphone.
"""
from pathlib import Path
import hashlib,json,struct
from pypinyin import lazy_pinyin,Style
root=Path(__file__).resolve().parents[1]
name='mn5q8_cn';src=root/'managed_components/espressif__esp-sr/model/multinet_model'/name
files=[(p.name,p) for p in sorted(src.iterdir())]
files += [("_TEST_"+p.stem,p) for p in sorted((root/'models/wake_tests').glob('*.pcm'))]
header=bytearray(struct.pack('<I32sI',1,name.encode(),len(files)));data=bytearray();offset=40+40*len(files);metadata={}
for filename,p in files:
 raw=p.read_bytes();header+=struct.pack('<32sII',filename.encode(),offset+len(data),len(raw));data+=raw
 metadata[filename]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
packed=header+data
(root/'models/pet_name_wake.bin').write_bytes(packed)
sha=hashlib.sha256(packed).hexdigest()
(root/'models/pet_name_wake_manifest.json').write_text(json.dumps({'model':name,'source':'espressif/esp-sr bundled component','flash_offset':'0xA00000','reserved_bytes':0x300000,'packed_bytes':len(packed),'sha256':sha,'files':metadata},indent=2)+'\n')
(root/'main/pet_name_wake_model.h').write_text(f'#pragma once\n#define PET_NAME_WAKE_MODEL_BYTES {len(packed)}u\n#define PET_NAME_WAKE_MODEL_SHA256 "{sha}"\n')
first=0x3400;last=0x9fff
readings=[]
for code in range(first,last+1):
 s=lazy_pinyin(chr(code),style=Style.NORMAL,errors=lambda _:[''])[0].replace('ü','v')
 readings.append(s if s.isascii() and s.isalpha() and len(s)<=6 else '')
syllables=sorted(set(readings));indices={s:i for i,s in enumerate(syllables)}
strings=''.join('    "'+s+'",\n' for s in syllables)
values=[str(indices[s]) for s in readings]
rows='\n'.join('    '+','.join(values[i:i+24])+',' for i in range(0,len(values),24))
(root/'main/pet_name_pinyin.inc').write_text('/* Generated from pypinyin (MIT). See models/NAME_WAKE.md. */\nstatic const char *const syllables[]={\n'+strings+'};\nstatic const uint16_t han_syllable[]={\n'+rows+'\n};\n')
print('Model packed:',len(packed),'bytes; Han table:',len(readings)*2,'bytes;',len(syllables),'syllables')
