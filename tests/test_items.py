import pytest
from pathlib import Path
from hi_sweetheart.items import (
    parse_item, format_item, read_items, write_items,
    add_item, mark_done, mark_undone, make_item, Item,
)


def test_format_and_parse_roundtrip():
    item = Item(
        emoji="\U0001f516", title="Test Article", url="https://example.com",
        summary="A great read", action_type="bookmark",
        timestamp="2026-03-24 12:00", status="pending",
    )
    line = format_item(item)
    parsed = parse_item(line)
    assert parsed is not None
    assert parsed.title == "Test Article"
    assert parsed.url == "https://example.com"
    assert parsed.summary == "A great read"
    assert parsed.action_type == "bookmark"
    assert parsed.status == "pending"


def test_make_item_pending_by_default():
    item = make_item("bookmark", "Title", "https://url", "Summary")
    assert item.status == "pending"
    assert item.emoji == "\U0001f516"


def test_make_item_podcast_auto_done():
    item = make_item("podcast", "Episode", "https://url", "Summary")
    assert item.status == "done"


def test_make_item_plugin_stays_pending():
    item = make_item("plugin_install", "Plugin", "https://url", "Summary")
    assert item.status == "pending"


def test_make_item_auto_done_override():
    item = make_item("bookmark", "Title", "https://url", "Summary", auto_done=True)
    assert item.status == "done"


def test_add_and_read_items(tmp_path):
    p = tmp_path / "items.md"
    add_item(p, make_item("bookmark", "A", "https://a.com", "First"))
    add_item(p, make_item("note", "B", "https://b.com", "Second"))
    items = read_items(p)
    assert len(items) == 2
    assert items[0].title == "A"
    assert items[1].title == "B"


def test_add_item_creates_file(tmp_path):
    p = tmp_path / "sub" / "items.md"
    add_item(p, make_item("bookmark", "A", "https://a.com", "First"))
    assert p.exists()
    assert p.read_text().startswith("# Hi Sweetheart")


def test_write_items_overwrites(tmp_path):
    p = tmp_path / "items.md"
    items = [
        make_item("bookmark", "A", "https://a.com", "First"),
        make_item("note", "B", "https://b.com", "Second"),
    ]
    write_items(p, items)
    assert len(read_items(p)) == 2

    write_items(p, [items[0]])
    assert len(read_items(p)) == 1


def test_mark_done(tmp_path):
    p = tmp_path / "items.md"
    add_item(p, make_item("bookmark", "A", "https://a.com", "First"))
    assert read_items(p)[0].status == "pending"

    mark_done(p, 0)
    assert read_items(p)[0].status == "done"


def test_mark_undone(tmp_path):
    p = tmp_path / "items.md"
    add_item(p, make_item("podcast", "A", "https://a.com", "First"))
    assert read_items(p)[0].status == "done"

    mark_undone(p, 0)
    assert read_items(p)[0].status == "pending"


def test_mark_done_invalid_index(tmp_path):
    p = tmp_path / "items.md"
    add_item(p, make_item("bookmark", "A", "https://a.com", "First"))
    mark_done(p, 99)  # should not crash
    assert read_items(p)[0].status == "pending"


def test_read_items_empty_file(tmp_path):
    p = tmp_path / "items.md"
    p.write_text("# Hi Sweetheart\n\n")
    assert read_items(p) == []


def test_read_items_missing_file(tmp_path):
    assert read_items(tmp_path / "nope.md") == []


def test_parse_item_bad_line():
    assert parse_item("not a valid item line") is None
    assert parse_item("* just a bullet") is None
