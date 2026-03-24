"""Dashboard server — serves the UI and API for items.md.

Run: python -m hi_sweetheart.server
"""
from __future__ import annotations

import json
import os
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from hi_sweetheart.items import read_items, mark_done, mark_undone, to_dicts

PORT = 8788
DEFAULT_ITEMS_PATH = Path.home() / ".hi-sweetheart" / "items.md"


class Handler(SimpleHTTPRequestHandler):
    items_path: Path = DEFAULT_ITEMS_PATH

    def do_GET(self):
        if self.path == "/api/items":
            items = read_items(self.items_path)
            self._json({"items": to_dicts(items)})
        elif self.path in ("/", "/index.html"):
            self.path = "/dashboard.html"
            super().do_GET()
        else:
            super().do_GET()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))

        if self.path == "/api/done":
            mark_done(self.items_path, body["index"])
        elif self.path == "/api/undone":
            mark_undone(self.items_path, body["index"])
        else:
            self.send_error(404)
            return

        self._json({"ok": True})

    def _json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, fmt, *args):
        pass


def main():
    items_path = DEFAULT_ITEMS_PATH
    if not items_path.exists():
        items_path.parent.mkdir(parents=True, exist_ok=True)
        items_path.write_text("# Hi Sweetheart\n\n", encoding="utf-8")

    Handler.items_path = items_path
    os.chdir(Path(__file__).parent)
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"Hi Sweetheart Dashboard -> {url}")
    print(f"Items file: {items_path}")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
