import pytest

from app.sandbox import SandboxError, create_job_dir, resolve_sandbox_path, write_bytes


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    root = tmp_path / "sandbox"
    root.mkdir()
    monkeypatch.setattr("app.sandbox.SANDBOX_ROOT", root)
    monkeypatch.setattr("app.config.SANDBOX_ROOT", root)
    return root


def test_relative_path_stays_inside(sandbox):
    target = sandbox / "note.txt"
    target.write_text("ok", encoding="utf-8")
    resolved = resolve_sandbox_path("note.txt", must_exist=True)
    assert resolved == target.resolve()


def test_blocks_dotenv(sandbox):
    (sandbox / ".env").write_text("SECRET=1", encoding="utf-8")
    with pytest.raises(SandboxError):
        resolve_sandbox_path(".env", must_exist=True)


def test_blocks_traversal(sandbox):
    with pytest.raises(SandboxError):
        resolve_sandbox_path("../../etc/passwd", must_exist=False, allow_create=True)


def test_blocks_absolute_escape(sandbox):
    with pytest.raises(SandboxError):
        resolve_sandbox_path("/etc/hosts", must_exist=False, allow_create=True)


def test_write_bytes_roundtrip(sandbox):
    job = create_job_dir()
    path = write_bytes(job, "meeting.mp3", b"ID3fake")
    assert path.exists()
    assert path.stat().st_size == 7
