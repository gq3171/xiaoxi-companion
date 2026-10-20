"""Versioned model/body contract. Capabilities never authorize a new task."""
VERSION = 3
BASE_HOME = ('roam', 'rest', 'wake', 'wash', 'work', 'window')
DIALOGUE = ('speak', 'search', 'recall', 'list_reminders', 'cancel_reminder',
            'computer_task', 'computer_cancel', 'computer_status', 'computer_resume', 'computer_update')
TASK_TOOLS = ('run', 'check', 'search', 'browser_open', 'browser_tabs',
              'browser_snapshot', 'browser_click', 'browser_type', 'browser_key',
              'browser_scroll', 'browser_check', 'browser_screenshot',
              'browser_close', 'write_artifact', 'artifact', 'blocked', 'finish')


def describe(feedback=None):
    feedback = feedback if isinstance(feedback, dict) else {}
    home = BASE_HOME + (('read',) if feedback.get('home_protocol') == 2 else ())
    actions = tuple(x for x in DIALOGUE if (x not in ('computer_resume','computer_update') or feedback.get('task_protocol') == 2 or x=='computer_resume' and feedback.get('computer_protocol')==2))
    return dict(version=VERSION, dialogue=actions, home=home,
                autonomous=('wait', 'speak', 'recall'),
                tts_prefetch=feedback.get('tts_protocol') == 2,
                objects={'bed': ['rest', 'wake'], 'basin': ['wash'],
                         'computer': ['work'], 'window': ['window'],
                         'storybook': ['read'] if 'read' in home else []},
                limits={'life_steps': 4, 'active_computer_tasks': 1,
                        'home_actions_are_virtual': True, 'autonomous_computer': False})


def validate(answer, kind, feedback=None):
    if not isinstance(answer, dict):
        raise ValueError('model object required')
    caps = describe(feedback)
    allowed = caps['autonomous'] if kind == 'plan' else caps['dialogue'] + ('ignore',)
    if kind in ('dialogue', 'plan') and answer.get('action') not in allowed:
        raise ValueError('action outside negotiated capabilities')
    if kind == 'dialogue' and answer.get('input', 'direct') not in ('direct', 'background', 'uncertain'):
        raise ValueError('invalid input attribution')
    if answer.get('home_action') and answer['home_action'] not in caps['home']:
        raise ValueError('home action unavailable')
    plan = answer.get('life_plan')
    if plan is not None:
        if not isinstance(plan, dict) or not isinstance(plan.get('goal'), str) or not 0 < len(plan['goal'].encode()) <= 240:
            raise ValueError('invalid life goal')
        steps = plan.get('steps')
        if not isinstance(steps, list) or not 1 <= len(steps) <= 4 or any(not isinstance(s, str) or s not in caps['home'] for s in steps):
            raise ValueError('invalid life steps')
    if answer.get('life_control') not in (None, '', 'pause', 'resume', 'cancel'):
        raise ValueError('invalid life control')
    for key in ('say', 'text'):
        if key in answer and (not isinstance(answer[key], str) or len(answer[key].encode()) > 4096):
            raise ValueError('reply exceeds delivery budget')
    return answer
