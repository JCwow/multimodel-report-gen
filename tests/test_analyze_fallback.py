from app import main as main_mod
from fastapi.testclient import TestClient


def test_falls_back_to_pipeline_on_sdk_initialize_timeout(monkeypatch):
    async def boom(**kwargs):
        raise Exception("Control request timeout: initialize")

    async def pipeline(audio_bytes, image_bytes_list):
        return ("transcript", ["insight"], "# report", ["speech_processor"])

    monkeypatch.setattr(main_mod, "resolve_backend", lambda: "claude")
    monkeypatch.setattr(main_mod, "run_claude_agent", boom)
    monkeypatch.setattr(main_mod, "_run_pipeline", pipeline)
    monkeypatch.setattr(main_mod, "index_report", lambda **kwargs: None)

    client = TestClient(main_mod.app)
    response = client.post(
        "/api/v1/analyze-meeting",
        files={"audio": ("meeting.mp3", b"ID3fake", "audio/mpeg")},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["backend"] == "pipeline"
    assert data["report"] == "# report"
    assert "timeout" in (data.get("warning") or "").lower() or "SDK" in (data.get("warning") or "")
