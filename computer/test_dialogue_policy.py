"""Dialogue method guards are narrow; uncertain language stays with the model."""
import json,unittest
from urllib.error import URLError
from interaction import dialogue_messages,browser_request,retry_request,enforce_route,DialogueContractError
from runtime_support import failure_category

class DialoguePolicyTests(unittest.TestCase):
    def test_affirmative_browser_and_official_page_requests(self):
        for text in ('你用浏览器查询看看','请你去看看测试厂商的主页最近有没有新的主机发布','我还以为你会用浏览器搜索呢','Use the browser to check the official website'):
            self.assertTrue(browser_request(text),text)
    def test_negative_and_capability_questions_do_not_force_tasks(self):
        for text in ('不用浏览器，跟我聊聊','不要访问官网','我不想用浏览器查询','我没让你用浏览器查询','你会用浏览器查询吗','你会用浏览器吗？','浏览器是什么？','取消刚才的任务'):
            self.assertFalse(browser_request(text),text)
    def test_retry_match_does_not_capture_topic_changes_or_negation(self):
        for text in ('再试试','那你再试试吧','请重试','再来一次吧'):self.assertTrue(retry_request(text),text)
        for text in ('不要重试','算了，换个话题','重试别的任务','再试试，顺便删除目录'):self.assertFalse(retry_request(text),text)
    def test_wrapped_socket_timeout_remains_timeout(self):
        self.assertEqual(failure_category(URLError(TimeoutError())), 'timeout')
    def test_background_audio_never_turns_into_browser_work(self):
        class NoCall:
            def complete(self,*args,**kwargs):raise AssertionError('background must not infer again')
        answer=dict(input='background',action='ignore',say='')
        self.assertEqual(enforce_route(NoCall(),'',[],answer,'用浏览器查询',True,lambda:True),answer)
    def test_new_topic_does_not_inherit_old_failed_browser_method(self):
        class NoCall:
            def complete(self,*args,**kwargs):raise AssertionError('new topic must not inherit route')
        recent=[dict(owner='用浏览器查询',state='failed')]
        answer=dict(input='direct',action='speak',say='好，聊点别的')
        self.assertEqual(enforce_route(NoCall(),'',[],answer,'换个话题',False,lambda:True,recent),answer)

    def test_current_input_and_inbox_share_one_user_message_for_provider_compatibility(self):
        recent=[dict(owner='合成旧请求',state='failed')]
        messages=dialogue_messages([], '再试试', recent)
        self.assertEqual(len(messages),1)
        self.assertEqual(json.loads(messages[0]['content']),dict(candidate='再试试',recent_web_turns=recent))
