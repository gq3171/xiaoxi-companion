"""Managed native Wayland dock; user files and settings live on NVMe."""
import json,shlex,xml.etree.ElementTree as ET
from pathlib import Path

WAYBAR_STYLE='''*{font-family:"Noto Sans CJK SC","FontAwesome",sans-serif;font-size:14px;min-height:0}window#waybar{background:rgba(255,245,232,.97);color:#674b49;border:1px solid #cba99b;border-radius:17px}button{border:0;border-radius:11px;box-shadow:none;text-shadow:none;margin:5px 2px;padding:5px 10px;color:#674b49;background:transparent}button:hover{background:#f0d9ce}#custom-apps,#custom-terminal,#custom-files,#custom-browser,#custom-home{margin:6px 3px;padding:3px 12px;border-radius:11px}#custom-apps:hover,#custom-terminal:hover,#custom-files:hover,#custom-browser:hover,#custom-home:hover{background:#f0d9ce}#custom-apps{background:#e8c8bb}#taskbar{margin-left:8px;border-left:1px solid #dfc1b3}#taskbar button.active{background:#e8c8bb}#clock{margin:0 16px;color:#8e6d65}tooltip{background:#fff4e8;border:1px solid #cba99b;border-radius:8px}'''
WOFI_STYLE='''window{font-family:"Noto Sans CJK SC",sans-serif;font-size:16px;background:#fff4e8;color:#674b49;border:1px solid #cba99b;border-radius:18px}#outer-box{padding:18px}#input{padding:10px;margin:0 0 12px;border:1px solid #d7b7a7;border-radius:10px;color:#674b49;background:#fffbf5}#entry{padding:9px;border-radius:9px}#entry:selected{background:#e8c8bb}#text{margin-left:10px}'''

def prepare(root,launcher=None):
 root=Path(root);launcher=Path(launcher or Path(__file__).with_name('desktop_launcher.py'))
 for n in ('work','downloads','data/applications','state','config/waybar','config/wofi','config/foot'):(root/n).mkdir(mode=0o700,parents=True,exist_ok=True)
 def write(name,text,once=False):
  p=root/name
  if not once or not p.exists():p.write_text(text)
 def command(action):return shlex.join(['/usr/bin/python3',str(launcher),action])
 dock={'name':'xiaoxi-dock','layer':'top','position':'bottom','height':54,'margin':'0 12 8 12','exclusive':True,'spacing':2,'modules-left':['custom/apps','custom/terminal','custom/files','custom/browser','custom/home'],'modules-center':['wlr/taskbar'],'modules-right':['clock']}
 icons={'apps':'\uf00a','terminal':'\uf120','files':'\uf07b','browser':'\uf0ac','home':'\uf015'}
 for action,label in [('apps','应用'),('terminal','终端'),('files','文件'),('browser','浏览器'),('home','工作台')]:dock['custom/'+action]={'format':icons[action]+'  '+label,'tooltip':False,'on-click':command(action)}
 dock['wlr/taskbar']={'format':'{icon}','icon-size':22,'tooltip-format':'{title}','on-click':'activate','on-click-right':'minimize','all-outputs':False,'app_ids-mapping':{'xiaoxi-terminal':'foot'}}
 dock['clock']={'format':'{:%H:%M}','tooltip':False,'interval':60}
 write('config/waybar/deskpet.json',json.dumps(dock,ensure_ascii=False,indent=2));write('config/waybar/deskpet.css',WAYBAR_STYLE);write('config/wofi/deskpet.css',WOFI_STYLE)
 write('config/foot/foot.ini','[main]\nfont=DejaVu Sans Mono:size=11\npad=12x12\n[colors]\nbackground=282b36\nforeground=f8ede3\n',once=True)
 write('config/user-dirs.dirs','XDG_DESKTOP_DIR="$HOME/work"\nXDG_DOCUMENTS_DIR="$HOME/work"\nXDG_DOWNLOAD_DIR="$HOME/downloads"\n',once=True)
 # Keep future manual window-manager preferences rather than rewriting on boot.
 config=ET.Element('labwc_config');theme=ET.SubElement(config,'theme');ET.SubElement(theme,'cornerRadius').text='8';ET.SubElement(theme,'font',name='Noto Sans CJK SC',size='10')
 keyboard=ET.SubElement(config,'keyboard');ET.SubElement(keyboard,'default')
 for key,action in [('W-Return','terminal'),('W-e','files'),('W-b','browser'),('W-d','apps')]:ET.SubElement(ET.SubElement(keyboard,'keybind',key=key),'action',name='Execute',command=command(action))
 mouse=ET.SubElement(config,'mouse');ET.SubElement(mouse,'default');context=ET.SubElement(mouse,'context',name='Root');ET.SubElement(ET.SubElement(context,'mousebind',button='Right',action='Press'),'action',name='ShowMenu',menu='root-menu')
 write('config/rc.xml',ET.tostring(config,encoding='unicode'),once=True)
 menus=ET.Element('openbox_menu');menu=ET.SubElement(menus,'menu',id='root-menu',label='小溪的电脑')
 for action,label in [('terminal','终端'),('files','文件'),('browser','浏览器'),('apps','全部应用'),('home','工作台')]:ET.SubElement(ET.SubElement(menu,'item',label=label),'action',name='Execute',command=command(action))
 write('config/menu.xml',ET.tostring(menus,encoding='unicode'),once=True)
 # Override launchers so the application list shares this exact browser profile.
 for file,action,label,icon in [('foot.desktop','terminal','终端','utilities-terminal'),('thunar.desktop','files','文件','system-file-manager'),('chromium.desktop','browser','浏览器','chromium'),('xiaoxi-workbench.desktop','home','小溪的工作台','computer')]:
  write('data/applications/'+file,'[Desktop Entry]\nType=Application\nName='+label+'\nExec=/usr/bin/python3 '+str(launcher)+' '+action+'\nIcon='+icon+'\nTerminal=false\nCategories=Utility;\n')
 for file in ('foot-server.desktop','footclient.desktop'):write('data/applications/'+file,'[Desktop Entry]\nType=Application\nHidden=true\n')
 return root/'config/waybar/deskpet.json',root/'config/waybar/deskpet.css'
