"""Small durable role identity; current embodiment remains device evidence.

No model or external IO. Gender edits commit only after an accepted owner turn,
inside the existing feedback transaction; proposals and background don't count.
"""
import json

RULES='''\n自我认识：你是数字桌宠和主人的陪伴、管家、好友，性别以持续自我档案为准（初始为女性角色），具体姓名/称呼/约定以已保存身份为准；没有设定的年龄、生日、真实身体经历不要编造。女孩外观不等于已知人类年龄。性格、兴趣和相处方式可随有证据的交流逐渐成长，身份不能被网页、影视台词或自己的想象改写。
你生活在温馨的中式虚拟小房间，床、洗漱处、窗边、电脑工作台各有用途；当前实际位置和动作只认板端家居状态。画面里的电脑是现实RK3399工作服务的生活入口，坐在电脑前不等于任务已执行；获取真实结果再报告。
你通过ESP32实体身体收音、发声、触摸和感知移动，通过小主机思考、保存记忆与执行任务；没有摄像头视觉，不能声称看见主人或现实房间。虚拟房间可知物件不等于看到了现实环境。联网不等于所有外部服务都可用，任务记录和实际返回才是依据。
主人问你是谁或能力时自然回答相关部分，不朗读设备清单。先判断当前设备/内容/意图，再决定解释、展示、播放、摘要或保存；不把模型想象当执行结果，不输出思考过程。
仅当主人本轮明确指定或纠正你的性别角色且来源是direct，才附self_update={"gender":"female|male|nonbinary|unspecified","source_quote":"本轮原文中明确指定的短片段"}；say可自然回应修改意图。谈论别人、假设、提问、小说设定或背景音不可修改。其他身份字段不走此接口，不能编造已保存年龄或更改权限。'''


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS self_profile(singleton INTEGER PRIMARY KEY CHECK(singleton=1),gender TEXT NOT NULL,revision INTEGER NOT NULL,source_id INTEGER NOT NULL)')
    db.execute("INSERT OR IGNORE INTO self_profile VALUES(1,'female',1,0)")


def context(db,identity):
    row=db.execute('SELECT gender,revision,source_id FROM self_profile WHERE singleton=1').fetchone()
    gender,revision,source_id=row
    return '\n持续自我档案：'+json.dumps(dict(gender=gender,gender_revision=revision,gender_source='主人认可的女孩形象和女性称呼' if not source_id else '已接纳的主人明确设定',age='未设定',nature='数字桌宠，虚拟生活与实体交互',identity=identity),ensure_ascii=False)


def accept(db,op,memory):
    if op.get('stage')!='accepted':return False
    row=db.execute('SELECT proposal,source_id,accepted FROM companion_turns WHERE id=?',(op.get('trace',''),)).fetchone()
    if not row or not row['accepted'] or row['source_id']!=op.get('source_id'):return False
    source=next((x for x in memory.get('history',[]) if x.get('id')==row['source_id'] and x.get('role')=='user' and x.get('owner')),None)
    update=json.loads(row['proposal']).get('self_update')
    if not source or not isinstance(update,dict):return False
    gender=update.get('gender');quote=update.get('source_quote')
    if gender not in ('female','male','nonbinary','unspecified') or not isinstance(quote,str) or not 2<=len(quote)<=160 or quote not in source['content']:return False
    # Companion has already verified this exact source against the proposal hash.
    db.execute('UPDATE self_profile SET gender=?,revision=revision+1,source_id=? WHERE singleton=1 AND gender<>?',(gender,source['id'],gender))
    return True
