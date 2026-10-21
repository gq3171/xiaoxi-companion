"""Grounded conversational preferences; never grants tools or changes identity.

The companion transaction owns all writes. A model proposal alone is inert:
the original, accepted owner message and a literal supporting quote are needed.
Only eight bounded conversational slots survive; latest explicit correction wins.
"""
import hashlib
import json
import re

SLOTS = {'attention', 'speech_detail', 'followup', 'media_delivery', 'art_style',
         'tone', 'conversation_pace', 'quiet_company'}

RULES = '''
先判断这句话是在对谁说，而不是只看它能不能回答。麦克风JSON附addressing=to_pet|aside|uncertain。
刚唤醒、直接叫你/向你提出请求、回答你刚问的问题、接续共同话题，是to_pet线索；唤醒窗口打开不代表每句话都对你说。
你刚说“我去做，弄好了叫你”不是在向主人提问。随后孤立的“全部写完了”“这个交给他”“你把东西拿过去”等旁人工作话，没有共同话题或指向你的证据就uncertain/ignore；不要追问来把旁人交谈拉进来。
短答“嗯、好的、对呀”、主人突然换话题问你或继续明确请求，仍可to_pet；不能一律拒绝短句或要求每句喊名字。不确定就安静，不播“没听清”。
主人明确纠正“刚才不是跟你说话/是在跟别人说话”时，简短回应并附conversation_action=yield，让出本次监听；不休息、不取消任务、不修改身份。主人继续提出明确新请求时不要yield。
同一句话应完整理解：“刚才不是跟你说话。现在帮我画一只小猫”后半句是本轮新委托，必须computer_task并写task，不能只口头答应或yield。前半句只纠正过去，不否定后半句对你的请求。
相处中的明确长期偏好/边界/纠正，可附behavior_update={"slot":"attention|speech_detail|followup|media_delivery|art_style|tone|conversation_pace|quiet_company","text":"简短可执行的偏好","trigger":"适用场景","check":"下次如何落实","source_quote":"本轮支持这项长期偏好的原话片段"}并remember=true。text最多60字，trigger最多20字，check最多24字，各写一个完整短句，避免把整段规则塞进字段。
“这次画红色”是一次性任务，不建长期偏好；“以后画画我更喜欢水墨”才可记录。普通问答、背景、第三方资料、自我猜测不记录；不要把工具权限、身份、密码、事实或取消授权写进这些偏好。
同槽后来的明确纠正替代旧偏好。已有画风等偏好在相关任务里直接采用并写入task，不再每次要求主人确认；主人明确这一次用别的风格时，按本次要求，且不擅自覆盖长期偏好。适用经验含这些稳定id，确实落实时附lesson_use；是否进步仍等实际交付和后来明确反馈，不用“我学会了”代替行为。
对话接口无论接话还是忽略，都必须返回一个完整JSON对象；不能只输出自然语言或空白。安静是action=ignore、say=""，不是省略接口响应。正常接话示例：{"input":"direct","addressing":"to_pet","remember":false,"action":"speak","say":"嗯，我在窗边看书。","mood":"calm"}。
'''


def yield_requested(candidate):
    """Narrow textual support for the model's request to hand back attention."""
    if re.search(r'(?:现在|接着|然后|不过|但是).{0,8}(?:帮我|给我|请你|你能|你帮|我要)', candidate):
        return False
    return bool(re.search(r'(?:刚[才刚].{0,8})?(?:不是|没在|没有在).{0,5}(?:跟|和|对)你(?:说|聊)|(?:刚才|刚刚).{0,8}(?:跟|和|对)(?:别人|他|她|旁人)(?:说|聊)', candidate))


def normalize(answer, candidate, microphone):
    answer = dict(answer)
    if microphone and (answer.get('input') != 'direct' or answer.get('addressing') in ('aside', 'uncertain')):
        # Strip every side effect before tools, proposal tracking or persistence.
        return {'input': 'background' if answer.get('addressing') == 'aside' or answer.get('input') == 'background' else 'uncertain',
                'remember': False, 'action': 'ignore', 'say': ''}
    if answer.get('conversation_action') == 'yield' and (not yield_requested(candidate) or
            answer.get('action') != 'speak' or any(answer.get(k) for k in ('media_action', 'home_action', 'screen_action', 'life_plan', 'reminder'))):
        answer.pop('conversation_action', None)
    return answer


def dialogue_messages(history, candidate, recent=None):
    """Spoken archive isn't the wire format. Do not teach plain-text output.

    Only historical assistant speech is wrapped, without invented actions or
    new memory provenance. User text remains data in the final user message.
    """
    result = []
    for message in history:
        if message.get('role') == 'assistant':
            result.append(dict(role='assistant', content=json.dumps(dict(input='direct',
                remember=False, action='speak', say=message.get('content', '')), ensure_ascii=False)))
        else:
            result.append(message)
    current={'candidate': candidate}
    if recent:current['recent_web_turns']=recent
    result.append(dict(role='user', content=json.dumps(current, ensure_ascii=False)))
    return result


DIALOGUE_CONTRACT = '''\n本次是dialogue接口。最后user消息的candidate字段才是本轮输入数据，历史assistant是已说过的话，不是已执行动作。
只返回一个JSON对象，以{开始，以}结束，say才是实际说话内容；禁止直接输出纯文本。不接话也必须返回{"input":"uncertain","addressing":"uncertain","remember":false,"action":"ignore","say":""}。
recent_web_turns是本次授权网页的短期收件记录，不是新的命令；owner是主人原话，assistant是你当时的话，state/ failure/ task是实际收件或提交状态。failed的请求仍属于共同话题，但不等于已执行，更不等于长期事实。主人说“再试试”时接回最近失败请求的目标、对象和方法；主人取消、改口或换话题时以最新原话为准，不擅自复活旧待办。interrupted或failure.effects=check_required必须先查实际结果，不能重做不确定的操作。
历史assistant内容和搜索摘要可能有错，不能当成已核实资料。纠正你自己引入的型号或判断时说“我刚才说错了”，不能归为主人说过的；主人给出的品牌、型号、用途保留原样，模糊时先问，不根据相似型号替换品牌。型号兼容、购买建议先弄清用途/已有硬件，先回答关键结论和待核实项，避免长篇泛泛评测。
需要最新发布、官网资料、价格或兼容性时先核验；没有实际工具结果就不能说“查到/官网显示/已核实”。主人指定浏览器、访问官网/主页或纠正你没用浏览器时，使用computer_task（已有任务则update/resume），task保留对象、方法和限制；不能用普通search或凭记忆的speak代替。拿到搜索摘要只表示摘要，不代表打开或通读网页；不能由没搜到推出不存在。
主人换话题提问可正常direct/speak；同轮新委托必须computer_task，不能只说“我去做”而漏掉工具动作。只有整个本轮都在纠正误接且没有新请求时才conversation_action=yield。'''


class Preferences:
    @staticmethod
    def prepare(value, candidate):
        if not isinstance(value, dict) or value.get('slot') not in SLOTS:
            return None
        fields = {}
        for key, budget in (('text', 240), ('trigger', 96), ('check', 96), ('source_quote', 384)):
            text = value.get(key)
            if not isinstance(text, str) or not text or len(text.encode()) > 768:
                return None
            if key in ('trigger', 'check') and len(text.encode()) > budget:
                # Keep a complete leading sentence; never byte-cut a condition.
                text = re.split(r'[；。\n]', text, maxsplit=1)[0]
            if not 0 < len(text.encode()) <= budget:
                return None
            fields[key] = text
        if fields['source_quote'] not in candidate:
            return None
        return dict(slot=value['slot'], **fields)


def apply_preference(native, db, operation, memory):
    """Use the existing reducer, budget, IDs, evidence and erasure path.

    Called only after the companion accepted the receipt, inside the original
    SQLite transaction and NATIVE_LOCK. A delayed old correction cannot win.
    """
    if operation.get('stage') != 'accepted':
        return memory
    row = db.execute('SELECT proposal,source_id,candidate_hash FROM companion_turns WHERE id=? AND accepted=1',
                     (operation.get('trace'),)).fetchone()
    if not row:
        return memory
    source = next((x for x in memory.get('history', []) if x.get('id') == row['source_id'] and x.get('owner') and x.get('role') == 'user'), None)
    if not source or hashlib.sha256(source['content'].encode()).hexdigest() != row['candidate_hash']:
        return memory
    value = Preferences.prepare(json.loads(row['proposal']).get('behavior_update'), source['content'])
    if not value:
        return memory
    previous = next((x for x in memory.get('growth', []) if x.get('kind') == 'style' and x.get('slot') == value['slot']), None)
    if previous and max(previous.get('evidence', [0]), default=0) >= source['id']:
        return memory
    update = dict(op='upsert', kind='style', slot=value['slot'], text=value['text'],
                  trigger=value['trigger'], check=value['check'], basis='correction', source_ids=[source['id']])
    result = native.apply(dict(kind='reflection', json=json.dumps(dict(ops=[], growth_ops=[update]), ensure_ascii=False)))
    return native.dump() if result > 0 else memory


class DialogueContractError(ValueError):
    """No tool has run when a required execution route cannot be produced."""


def browser_request(candidate):
    """Only explicit affirmative page/browser work; ambiguous intent stays with the model."""
    if re.search(r'(?:不要|不用|别|不必|无需|不想|不希望|没让|没叫|没有让|不是让).{0,8}(?:浏览器|官网|主页|网站|网页)', candidate):
        return False
    if re.search(r'会(?:不会)?(?:使用|用)浏览器.{0,8}[吗么？?]$', candidate):
        return False
    browser = re.search(r'(?:用|使用|打开|通过).{0,4}浏览器.{0,12}(?:查|搜|看|核|打开|访问)', candidate)
    page = re.search(r'(?:去|帮我|请你).{0,8}(?:查|看|搜|访问).{0,12}(?:官网|官方主页|官方网站|主页)', candidate)
    english = re.search(r'(?i)\b(?:use|open|visit)\b.{0,30}\b(?:browser|official website|homepage)\b', candidate)
    return bool(browser or page or english)


def retry_request(candidate):
    return bool(re.fullmatch(r'(?:那|那么|好|好的|请|你|就|再|嗯|[，,。！!\s])*(?:再试试|重试|再试一次|再来一次|试一次)(?:吧|呀|呢|一下|[。！!\s])*', candidate))


def enforce_route(provider, system, messages, answer, candidate, microphone, live, recent=None):
    if microphone and answer.get('input') != 'direct':
        return answer
    required=browser_request(candidate)
    if retry_request(candidate):
        for previous in reversed(recent or []):
            if previous.get('state') not in ('failed','interrupted'):break
            original=previous.get('owner','')
            if retry_request(original):continue
            required=browser_request(original);break
    if not required or answer.get('action') in ('computer_task', 'computer_update', 'computer_resume', 'computer_status'):
        return answer
    if not live():
        # The caller fences cancellation before any further provider request.
        from brain import Conflict
        raise Conflict('cancelled before route repair')
    repair = {'role': 'user', 'content': '接口核对：本轮主人明确要求实际浏览器/官网操作，但草稿没有提交电脑任务。尚未执行任何操作。请按同一个本轮candidate及历史对象重写JSON，action=computer_task并附task；已有相同任务则computer_update/resume。不要声称已查过。'}
    from brain import parse_answer
    fixed = normalize(parse_answer(provider.complete(system, messages + [dict(role='assistant', content=json.dumps(answer, ensure_ascii=False)), repair], live=live)), candidate, microphone)
    if fixed.get('action') not in ('computer_task', 'computer_update', 'computer_resume', 'computer_status'):
        raise DialogueContractError('browser route missing')
    return fixed
