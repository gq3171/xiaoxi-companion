import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

spec = importlib.util.spec_from_file_location("computer_agent", Path(__file__).with_name("agent.py"))
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)
ID = "a" * 32


class ComputerAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = agent.Store(Path(self.tmp.name) / "jobs.sqlite3")

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def test_duplicates_busy_cancel_tombstone_and_restart_never_rerun_unknown_work(self):
        first = self.store.submit(ID, "检查系统")
        self.assertEqual(self.store.submit(ID, "检查系统")["id"], first["id"])
        with self.assertRaises(ValueError):
            self.store.submit(ID, "另一个任务")
        self.assertEqual(self.store.submit("b" * 32, "队列中的独立任务")["state"],"queued")
        self.store.cancel("b" * 32)
        self.store.cancel(ID)
        self.assertEqual(self.store.submit(ID, "检查系统")["state"], "cancelled")
        tombstone = "c" * 32
        self.store.cancel(tombstone)
        self.assertEqual(self.store.submit(tombstone, "迟到的重试")["state"], "cancelled")
        running = "d" * 32
        self.store.submit(running, "原任务")
        self.store.next()
        restarted = agent.Store(Path(self.tmp.name) / "jobs.sqlite3")
        self.assertEqual(restarted.get(running)["state"], "interrupted")
        self.assertIsNone(restarted.next())
        restarted.db.close()

    def test_real_command_result_and_verification_gate(self):
        calls = iter([
            {"action": "finish", "state": "succeeded", "message": "没有验证的假完成"},
            {"action": "check", "command": "printf verified", "message": "检查实际输出"},
            {"action": "finish", "state": "succeeded", "message": "实际检查已返回verified"},
        ])
        self.store.submit(ID, "检查系统")
        worker = agent.Worker(self.store, lambda _: next(calls))
        worker.run_job(self.store.next())
        job = self.store.get(ID)
        self.assertEqual(job["state"], "succeeded")
        self.assertIn("verified", job["message"])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM steps").fetchone()[0], 1)

    def test_mutation_invalidates_prior_check_and_failures_are_real(self):
        replies = iter([
            {"action": "check", "command": "true"},
            {"action": "run", "command": "exit 7"},
            {"action": "finish", "state": "succeeded", "message": "假成功"},
            {"action": "finish", "state": "failed", "message": "实际执行退出7"},
        ])
        self.store.submit(ID, "测试失败处理")
        agent.Worker(self.store, lambda _: next(replies)).run_job(self.store.next())
        self.assertEqual(self.store.get(ID)["state"], "failed")
        row = self.store.db.execute("SELECT exit_code FROM steps ORDER BY rowid DESC LIMIT 1").fetchone()
        self.assertEqual(row[0], 7)

    def test_cancel_kills_running_process_group_and_late_model_does_not_execute(self):
        self.store.submit(ID, "等待测试")
        job = self.store.next()
        worker = agent.Worker(self.store)
        result = []
        thread = threading.Thread(target=lambda: result.append(worker.command(ID, "sleep 30")))
        thread.start()
        time.sleep(0.15)
        self.store.cancel(ID)
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertNotEqual(result[0][0], 0)
        self.assertIn("停止", result[0][1])
        executed = []
        worker.command = lambda *_: executed.append(True)
        worker.model = lambda _: {"action": "run", "command": "false"}
        worker.run_job(job)
        self.assertFalse(executed)
        self.assertEqual(self.store.get(ID)["state"], "cancelled")

    def test_authenticated_http_submit_retry_status_and_missing_model(self):
        token = "test-pairing-token-" + "z" * 32
        server = ThreadingHTTPServer(("127.0.0.1", 0), agent.handler(self.store, token, lambda: True))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def rpc(operation, payload, auth=token):
            req = Request(f"http://127.0.0.1:{server.server_port}/v1/computer/{operation}",
                          json.dumps(payload).encode(), {"Authorization": "Bearer " + auth})
            with urlopen(req, timeout=3) as response:
                return json.load(response)
        try:
            with self.assertRaises(HTTPError) as denied:
                rpc("health", {}, "wrong")
            self.assertEqual(denied.exception.code, 401)
            denied.exception.close()
            self.assertTrue(rpc("health", {})["ready"])
            first = rpc("submit", {"job_id": ID, "goal": "检查电脑"})
            self.assertEqual(first, rpc("submit", {"job_id": ID, "goal": "检查电脑"}))
            self.assertEqual(rpc("status", {"job_id": ID})["state"], "queued")
            self.assertEqual(rpc("cancel", {"job_id": ID})["state"], "cancelled")
            with self.assertRaises(HTTPError) as invalid:
                rpc("submit", {"job_id": "x", "goal": "bad"})
            invalid.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
