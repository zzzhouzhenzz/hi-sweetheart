import logging
from unittest.mock import patch
from pathlib import Path
from hi_sweetheart.notify import setup_logging, send_notification, RunSummary


def test_setup_logging(tmp_path):
    log_path = tmp_path / "test.log"
    logger = setup_logging(log_path)
    logger.info("test message")
    assert log_path.exists()
    assert "test message" in log_path.read_text()


def test_run_summary_no_messages():
    summary = RunSummary()
    assert summary.format() == "hi-sweetheart: No new messages"


def test_run_summary_with_actions():
    summary = RunSummary()
    summary.add("bookmark", "Saved article about prompting")
    summary.add("plugin_install", "Installed superpowers plugin")
    summary.add_error("Failed to fetch https://example.com")
    text = summary.format()
    assert "bookmark" in text
    assert "plugin_install" in text
    assert "1 error" in text


@patch("hi_sweetheart.notify.subprocess")
def test_send_notification_calls_osascript(mock_subprocess):
    send_notification("Test Title", "Test Body")
    mock_subprocess.run.assert_called_once()
    cmd = mock_subprocess.run.call_args[0][0]
    assert "osascript" in cmd
    assert "Test Title" in " ".join(cmd)


@patch("hi_sweetheart.notify.subprocess")
def test_send_notification_escapes_quotes(mock_subprocess):
    send_notification('Title "with" quotes', 'Body "with" quotes')
    mock_subprocess.run.assert_called_once()
    cmd = mock_subprocess.run.call_args[0][0]
    # Should have escaped quotes
    osascript_str = cmd[2]
    assert '\\"' in osascript_str
