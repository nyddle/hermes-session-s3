import json
import threading

from hermes_session_s3.plugin import SessionAuditPlugin


def test_pre_and_post_hooks_write_matching_dump_files(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    plugin = SessionAuditPlugin()

    plugin.pre_api_request(
        session_id="s1",
        task_id="t1",
        api_call_count=1,
        model="gpt-5.4",
        provider="openai-codex",
        platform="telegram",
        request_debug={"method": "POST", "url": "https://example.com", "body": {"x": 1}},
    )
    plugin.post_api_request(
        session_id="s1",
        task_id="t1",
        api_call_count=1,
        model="gpt-5.4",
        provider="openai-codex",
        platform="telegram",
        response_model="gpt-5.4",
        response_debug={"finish_reason": "stop", "body": {"output_text": "hi"}},
    )

    sessions_dir = tmp_path / "sessions"
    request_dumps = sorted(sessions_dir.glob("request_dump_s1_*.json"))
    response_dumps = sorted(sessions_dir.glob("response_dump_s1_*.json"))

    assert len(request_dumps) == 1
    assert len(response_dumps) == 1
    assert request_dumps[0].name.replace("request_dump_", "") == response_dumps[0].name.replace("response_dump_", "")

    request_payload = json.loads(request_dumps[0].read_text(encoding="utf-8"))
    response_payload = json.loads(response_dumps[0].read_text(encoding="utf-8"))
    assert request_payload["request"]["url"] == "https://example.com"
    assert response_payload["response"]["body"]["output_text"] == "hi"


def test_on_session_end_forces_s3_scan(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    plugin = SessionAuditPlugin()

    calls = []

    class FakeMirrorService:
        enabled = True

        def scan_once(self, *, force=False):
            calls.append(force)
            return 0

    plugin._mirror_service = FakeMirrorService()
    plugin.on_session_end(session_id="s1", completed=True, interrupted=False)

    assert calls == [True]


def test_post_api_request_triggers_background_sync(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    plugin = SessionAuditPlugin()

    calls = []
    seen = threading.Event()

    class FakeMirrorService:
        enabled = True

        def scan_once(self, *, force=False):
            calls.append(force)
            seen.set()
            return 0

    plugin._mirror_service = FakeMirrorService()
    plugin.pre_api_request(
        session_id="s1",
        task_id="t1",
        api_call_count=1,
        model="gpt-5.4",
        provider="openai-codex",
        platform="telegram",
        request_debug={"method": "POST", "url": "https://example.com", "body": {"x": 1}},
    )
    plugin.post_api_request(
        session_id="s1",
        task_id="t1",
        api_call_count=1,
        model="gpt-5.4",
        provider="openai-codex",
        platform="telegram",
        response_model="gpt-5.4",
        response_debug={"finish_reason": "stop", "body": {"output_text": "hi"}},
    )

    assert seen.wait(1.0)
    assert calls == [True]
