import json

from hermes_session_s3.mirror import SessionS3MirrorService


class FakeS3Client:
    def __init__(self) -> None:
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)


def _configured_service(tmp_path, monkeypatch, *, settle_seconds=0.0):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    state_file = tmp_path / "cache" / "session_s3_mirror_state.json"

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setenv("FREE_CODE_LOGS_S3_BUCKET", "test-bucket")
    monkeypatch.delenv("HERMES_DISABLE_SESSION_S3_MIRROR", raising=False)

    service = SessionS3MirrorService(
        sessions_dir=sessions_dir,
        state_file=state_file,
        poll_interval_seconds=0.1,
        settle_seconds=settle_seconds,
    )
    fake_client = FakeS3Client()
    monkeypatch.setattr(service, "_make_client", lambda: fake_client)
    monkeypatch.setattr("hermes_session_s3.mirror.getpass.getuser", lambda: "alice")
    return service, fake_client, sessions_dir, state_file


def test_scan_once_uploads_changed_files_and_persists_state(tmp_path, monkeypatch):
    service, fake_client, sessions_dir, state_file = _configured_service(tmp_path, monkeypatch)

    request_file = sessions_dir / "request_dump_s1_2026-04-08T00-20-30-123Z_deadbeef.json"
    request_file.write_text(
        json.dumps(
            {
                "timestamp": "2026-04-08T00:20:30Z",
                "session_id": "s1",
                "platform": "cli",
                "provider": "openai-codex",
                "request": {
                    "method": "POST",
                    "url": "https://example.com/responses",
                    "headers": {"Authorization": "Bearer x"},
                    "body": {"model": "gpt-5.4"},
                },
            }
        ),
        encoding="utf-8",
    )

    uploaded = service.scan_once(force=True)

    assert uploaded == 2
    assert len(fake_client.calls) == 2
    assert fake_client.calls[0]["Bucket"] == "test-bucket"
    assert fake_client.calls[0]["Key"].endswith("/s1/2026-04-08T00-20-30-123Z_deadbeef_request.json")
    assert fake_client.calls[0]["ContentType"] == "application/json"
    payload = json.loads(fake_client.calls[0]["Body"].decode("utf-8"))
    assert payload["sessionId"] == "s1"
    assert payload["url"] == "https://example.com/responses"
    assert payload["source"] == "cli"
    assert fake_client.calls[1]["Key"].endswith("/s1/README.md")

    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert request_file.name in state["files"]
    assert state["readmes"]["s1"]

    uploaded_again = service.scan_once(force=True)
    assert uploaded_again == 0
    assert len(fake_client.calls) == 2


def test_scan_once_reuploads_modified_files_and_skips_hidden_files(tmp_path, monkeypatch):
    service, fake_client, sessions_dir, _ = _configured_service(tmp_path, monkeypatch)

    hidden = sessions_dir / ".ignore-me"
    hidden.write_text("secret", encoding="utf-8")

    transcript = sessions_dir / "chat.jsonl"
    transcript.write_text('{"role":"user","content":"hi"}\n', encoding="utf-8")

    response_file = sessions_dir / "response_dump_s2_20260408_002030_123456.json"
    response_file.write_text(
        json.dumps(
            {
                "timestamp": "2026-04-08T00:20:31Z",
                "session_id": "s2",
                "platform": "telegram",
                "provider": "openai-codex",
                "response_model": "gpt-5.4",
                "response": {
                    "status": 200,
                    "headers": {"x-test": "1"},
                    "body": {"output_text": "updated"},
                },
            }
        ),
        encoding="utf-8",
    )

    assert service.scan_once(force=True) == 2
    assert len(fake_client.calls) == 2
    assert fake_client.calls[0]["Key"].endswith("/s2/2026-04-08T00-20-30-123Z_456_response.json")
    response_payload = json.loads(fake_client.calls[0]["Body"].decode("utf-8"))
    assert response_payload["status"] == 200
    assert response_payload["body"]["output_text"] == "updated"

    response_file.write_text(
        json.dumps(
            {
                "timestamp": "2026-04-08T00:20:32Z",
                "session_id": "s2",
                "platform": "telegram",
                "provider": "openai-codex",
                "response_model": "gpt-5.4",
                "response": {
                    "status": 200,
                    "headers": {"x-test": "1"},
                    "body": {"output_text": "updated again"},
                },
            }
        ),
        encoding="utf-8",
    )

    assert service.scan_once(force=True) == 1
    assert len(fake_client.calls) == 3
    assert all(".ignore-me" not in call["Key"] for call in fake_client.calls)
    assert all("chat.jsonl" not in call["Key"] for call in fake_client.calls)
