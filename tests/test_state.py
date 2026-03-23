import json
from pathlib import Path
from hi_sweetheart.state import State


def test_load_state_fresh(tmp_path):
    state_file = tmp_path / "state.json"
    state = State(state_file)
    assert state.last_message_rowid == 0
    assert state.last_run is None


def test_load_state_existing(tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({
        "last_message_rowid": 42,
        "last_run": "2026-03-23T09:00:00Z",
    }))
    state = State(state_file)
    assert state.last_message_rowid == 42
    assert state.last_run == "2026-03-23T09:00:00Z"


def test_save_state(tmp_path):
    state_file = tmp_path / "state.json"
    state = State(state_file)
    state.update(rowid=99)
    state.save()

    data = json.loads(state_file.read_text())
    assert data["last_message_rowid"] == 99
    assert "last_run" in data


def test_update_advances_rowid(tmp_path):
    state_file = tmp_path / "state.json"
    state = State(state_file)
    state.update(rowid=10)
    state.update(rowid=20)
    assert state.last_message_rowid == 20
