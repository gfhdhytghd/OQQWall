import json
import unittest

from .helpers import SendcontrolTestEnv


class SendcontrolIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.env = SendcontrolTestEnv()
        self.env.reset_logs()
        self.env.set_cookie(self.env.main_qq, '{"session":"init"}')

    def tearDown(self):
        self.env.cleanup()

    def test_stack_merges_and_sends_when_threshold_reached(self):
        self.env.write_account_config(max_post_stack=2)
        self.env.add_preprocess_entry("1001")
        self.env.add_preprocess_entry("1002")

        server = self.env.start_qzone_server()
        try:
            first = self.env.run_sendcontrol(["--run-tag", "1001", "1", "stacking"])
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(len(server.received_payloads), 0)

            second = self.env.run_sendcontrol(["--run-tag", "1002", "2", "stacking"])
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(len(server.received_payloads), 1)

            payload = json.loads(server.received_payloads[0])
            self.assertEqual(payload["text"], "#1～2")
            self.assertEqual(payload["image"], [""])
            self.assertIn("priv", self.env.read_toolkit_log())
        finally:
            server.stop()

    def test_immediate_send_triggers_single_post(self):
        self.env.write_account_config(max_post_stack=3)
        self.env.add_preprocess_entry("3001")

        server = self.env.start_qzone_server()
        try:
            result = self.env.run_sendcontrol(["--run-tag", "3001", "10", "now"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(server.received_payloads), 1)
            payload = json.loads(server.received_payloads[0])
            self.assertEqual(payload["text"], "#10")
            log = self.env.read_toolkit_log()
            self.assertNotIn("投稿已存入暂存区", log)
        finally:
            server.stop()

    def test_flush_command_sends_stored_posts(self):
        self.env.write_account_config(max_post_stack=5)
        self.env.add_preprocess_entry("4001")

        server = self.env.start_qzone_server()
        try:
            first = self.env.run_sendcontrol(["--run-tag", "4001", "5", "stacking"])
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(len(server.received_payloads), 0)

            flush_payload = '{"action":"flush","group":"TestGroup"}'
            flush = self.env.run_sendcontrol(["--handle-conn"], input_data=flush_payload)
            self.assertEqual(flush.returncode, 0, flush.stderr)
            self.assertIn("success", flush.stdout)

            self.assertEqual(len(server.received_payloads), 1)
            payload = json.loads(server.received_payloads[0])
            self.assertEqual(payload["text"], "#5")
        finally:
            server.stop()

    def test_invalid_cookies_trigger_auto_login_and_succeed(self):
        self.env.write_base_config(max_attempts=2)
        self.env.write_account_config(max_post_stack=2)
        # Start with invalid cookies to force renew.
        self.env.set_cookie(self.env.main_qq, "not json")
        self.env.add_preprocess_entry("5001")

        server = self.env.start_qzone_server()
        try:
            result = self.env.run_sendcontrol(["--run-tag", "5001", "7", "now"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(server.received_payloads), 1)
            payload = json.loads(server.received_payloads[0])
            self.assertEqual(payload["text"], "#7")

            toolkit_log = self.env.read_toolkit_log()
            self.assertIn("renew", toolkit_log)

            crash_log = self.env.read_crash_log()
            self.assertIn("cookies JSON 无效或损坏", crash_log)
        finally:
            server.stop()

    def test_qzone_failed_responses_report_failure(self):
        self.env.write_base_config(max_attempts=2)
        self.env.write_account_config(max_post_stack=2)
        self.env.add_preprocess_entry("6001")

        server = self.env.start_qzone_server(responses=["failed", "failed"])
        try:
            result = self.env.run_sendcontrol(["--run-tag", "6001", "3", "now"])
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(server.received_payloads), 2)

            crash_log = self.env.read_crash_log()
            self.assertIn("空间发送错误", crash_log)
            self.assertIn("execute_send_rules 执行失败", crash_log)

            toolkit_log = self.env.read_toolkit_log()
            self.assertIn("投稿发送失败", toolkit_log)
        finally:
            server.stop()

    def test_qzone_failed_then_success_triggers_renew(self):
        self.env.write_base_config(max_attempts=2)
        self.env.write_account_config(max_post_stack=2)
        self.env.add_preprocess_entry("6101")

        server = self.env.start_qzone_server(responses=["failed", "success"])
        try:
            result = self.env.run_sendcontrol(["--run-tag", "6101", "8", "now"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(server.received_payloads), 2)
            toolkit_log = self.env.read_toolkit_log()
            self.assertIn("renew:", toolkit_log)
        finally:
            server.stop()

    def test_qzone_error_then_success_triggers_renew(self):
        self.env.write_base_config(max_attempts=2)
        self.env.write_account_config(max_post_stack=2)
        self.env.add_preprocess_entry("6102")

        server = self.env.start_qzone_server(responses=["error", "success"])
        try:
            result = self.env.run_sendcontrol(["--run-tag", "6102", "12", "now"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(server.received_payloads), 2)
            toolkit_log = self.env.read_toolkit_log()
            self.assertIn("renew:", toolkit_log)
        finally:
            server.stop()

    def test_cookie_missing_triggers_auto_login(self):
        # Do not set initial cookie file: remove the default from setUp
        self.env.write_base_config(max_attempts=2)
        self.env.write_account_config(max_post_stack=2)
        self.env.add_preprocess_entry("9101")
        import os
        cookie_path = self.env.root / f"cookies-{self.env.main_qq}.json"
        if cookie_path.exists():
            os.unlink(cookie_path)

        server = self.env.start_qzone_server()
        try:
            result = self.env.run_sendcontrol(["--run-tag", "9101", "22", "now"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(server.received_payloads), 1)
            toolkit_log = self.env.read_toolkit_log()
            self.assertIn("renew:", toolkit_log)
        finally:
            server.stop()

    def test_handle_conn_missing_tag_returns_failed(self):
        payload = '{"numb":"1","initsendstatue":"now"}'
        result = self.env.run_sendcontrol(["--handle-conn"], input_data=payload)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stdout.strip().endswith("failed"), result.stdout)

    def test_success_clears_storage_and_cache_dirs(self):
        self.env.write_account_config(max_post_stack=2)
        # Create images directory to ensure cleanup occurs
        self.env.create_image_files("9201", 1)
        self.env.add_preprocess_entry("9201")
        server = self.env.start_qzone_server()
        try:
            result = self.env.run_sendcontrol(["--run-tag", "9201", "33", "now"])
            self.assertEqual(result.returncode, 0, result.stderr)
            # After success, storage cleared
            self.assertEqual(self.env.fetch_storage_tags(), [])
            # Cache dir removed
            import os
            from pathlib import Path
            self.assertFalse((self.env.prepost_dir / "9201").exists())
        finally:
            server.stop()

    def test_at_unprived_sender_generates_at_mentions(self):
        self.env.write_base_config(at_unprived_sender="true")
        self.env.write_account_config(max_post_stack=2)
        # needpriv=false should allow @ mention
        self.env.add_preprocess_entry("9301", senderid="20111", afterlm='{"needpriv": false}')
        self.env.add_preprocess_entry("9302", senderid="20222", afterlm='{"needpriv": false}')
        server = self.env.start_qzone_server()
        try:
            # Push two tags to trigger send
            self.assertEqual(self.env.run_sendcontrol(["--run-tag", "9301", "1", "stacking"]).returncode, 0)
            self.assertEqual(self.env.run_sendcontrol(["--run-tag", "9302", "2", "stacking"]).returncode, 0)
            self.assertEqual(len(server.received_payloads), 1)
            payload = json.loads(server.received_payloads[0])
            text = payload["text"]
            self.assertIn("@{uin:20111", text)
            self.assertIn("@{uin:20222", text)
        finally:
            server.stop()

    def test_post_with_comment_sets_immediate_and_appends(self):
        self.env.write_account_config(max_post_stack=3)
        self.env.add_preprocess_entry("7001", comment="comment content")

        server = self.env.start_qzone_server()
        try:
            result = self.env.run_sendcontrol(["--run-tag", "7001", "11", "stacking"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(server.received_payloads), 1)
            payload = json.loads(server.received_payloads[0])
            self.assertEqual(payload["text"], "#11 comment content")
        finally:
            server.stop()

    def test_images_exceed_limit_triggers_chunked_sends(self):
        self.env.write_account_config(max_post_stack=2, max_image_number_one_post=2)
        # Prepare images for two tags.
        self.env.create_image_files("8001", 1)
        self.env.create_image_files("8002", 3)
        self.env.add_preprocess_entry("8001")
        self.env.add_preprocess_entry("8002")

        server = self.env.start_qzone_server()
        try:
            first = self.env.run_sendcontrol(["--run-tag", "8001", "1", "stacking"])
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(len(server.received_payloads), 0)

            second = self.env.run_sendcontrol(["--run-tag", "8002", "2", "stacking"])
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(len(server.received_payloads), 2)

            lengths = [len(json.loads(payload)["image"]) for payload in server.received_payloads]
            self.assertTrue(all(length <= 2 for length in lengths))
            self.assertEqual(sum(lengths), 4)
        finally:
            server.stop()

    def test_flush_empty_returns_no_pending_without_toolkit_calls(self):
        extra_env = {"TOOLKIT_EXPECT_NO_CALLS": "1"}
        flush_payload = '{"action":"flush","group":"TestGroup"}'
        result = self.env.run_sendcontrol(
            ["--handle-conn"], input_data=flush_payload, extra_env=extra_env
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "no pending posts")
        self.assertEqual(self.env.read_toolkit_log().strip(), "")
        self.assertEqual(self.env.read_unexpected_toolkit_log().strip(), "")

    def test_max_retry_exhaustion_logs_and_fails(self):
        self.env.write_base_config(max_attempts=1)
        self.env.write_account_config(max_post_stack=2)
        self.env.add_preprocess_entry("8101")

        server = self.env.start_qzone_server(responses=["failed"])
        try:
            result = self.env.run_sendcontrol(["--run-tag", "8101", "3", "now"])
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(server.received_payloads), 1)
            crash_log = self.env.read_crash_log()
            self.assertIn("空间发送错误", crash_log)
            self.assertIn("已达最大重试次数", crash_log)
        finally:
            server.stop()

    def test_flush_unknown_group_logs_error_without_qzone(self):
        extra_env = {"TOOLKIT_EXPECT_NO_CALLS": "1"}
        payload = '{"action":"flush","group":"UnknownGroup"}'
        result = self.env.run_sendcontrol(
            ["--handle-conn"], input_data=payload, extra_env=extra_env
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "failed")
        crash_log = self.env.read_crash_log()
        self.assertIn("未找到组", crash_log)
        self.assertEqual(self.env.read_unexpected_toolkit_log().strip(), "")

    def test_at_unprived_sender_fallback_to_private_message(self):
        self.env.write_base_config(at_unprived_sender="true")
        self.env.write_account_config(max_post_stack=5)
        self.env.add_preprocess_entry("8201", afterlm='{"needpriv": true}')

        result = self.env.run_sendcontrol(["--run-tag", "8201", "9", "stacking"])
        self.assertEqual(result.returncode, 0, result.stderr)
        log_lines = self.env.read_toolkit_log().splitlines()
        self.assertTrue(any(line.startswith("priv:20001") for line in log_lines))
        self.assertEqual(self.env.fetch_storage_tags(), ["8201"])

    def test_socat_transport_error_preserves_storage(self):
        self.env.write_account_config(max_post_stack=2)
        self.env.add_preprocess_entry("8301")
        self.env.set_cookie(self.env.main_qq, '{"session":"init"}')

        server = self.env.start_qzone_server()
        try:
            result = self.env.run_sendcontrol(
                ["--run-tag", "8301", "4", "now"], extra_env={"FAKE_SOCAT_FAIL": "1"}
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(server.received_payloads), 0)
            crash_log = self.env.read_crash_log()
            self.assertIn("投稿传输失败", crash_log)
            stored_tags = self.env.fetch_storage_tags()
            self.assertIn("8301", stored_tags)
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
