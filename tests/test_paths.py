import sys
from pathlib import Path

from audio_notes import paths


def _frozen(monkeypatch, exe: Path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))


def test_env_override_wins_even_when_packaged(tmp_path, monkeypatch):
    _frozen(monkeypatch, tmp_path / "app" / "audio-notes.exe")
    monkeypatch.setenv("AUDIO_NOTES_DATA_DIR", str(tmp_path / "custom"))
    assert paths.data_dir() == tmp_path / "custom"


def test_packaged_build_stores_data_next_to_the_program(tmp_path, monkeypatch):
    monkeypatch.delenv("AUDIO_NOTES_DATA_DIR", raising=False)
    app = tmp_path / "Audio Notes"
    app.mkdir()
    _frozen(monkeypatch, app / "audio-notes-tray.exe")
    assert paths.data_dir() == app / "data"
    assert (app / "data").is_dir()
    assert paths.sessions_dir() == app / "data" / "sessions"
    # the tray and the CLI/MCP exe sit in the same folder, so they agree
    _frozen(monkeypatch, app / "audio-notes.exe")
    assert paths.data_dir() == app / "data"


def test_packaged_build_falls_back_to_appdata_when_the_folder_is_not_creatable(tmp_path, monkeypatch):
    monkeypatch.delenv("AUDIO_NOTES_DATA_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    blocker = tmp_path / "app"
    blocker.write_text("a file, so 'app/data' cannot be created")
    _frozen(monkeypatch, blocker / "audio-notes.exe")
    assert paths.data_dir() == tmp_path / "roaming" / "audio-notes"


def test_source_install_uses_appdata(tmp_path, monkeypatch):
    monkeypatch.delenv("AUDIO_NOTES_DATA_DIR", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    assert paths.data_dir() == tmp_path / "roaming" / "audio-notes"
