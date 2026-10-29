"""Minimal VIDEPE host app: serves VIDEPE and the given files, then opens them in the browser."""

import http.server
import json
import mimetypes
import secrets
import sys
import tkinter as tk
import urllib.parse
import webbrowser
from pathlib import Path
from tkinter import filedialog

VIDEPE_DIR = Path("videpe-dist").resolve()  # a VIDEPE build (the contents of its dist/ folder)
APP_NAME = "My Host App"
FILES: list[Path] = []  # the files to open in VIDEPE, set by main()
TOKEN = secrets.token_urlsafe(32)  # a new random token for this launch

# The version of the host-app contract this app follows, sent in every session. This is not
# the VIDEPE version: VIDEPE rejects a session with a version it does not support and asks
# the user to update VIDEPE or the host app. Version 1 is supported from VIDEPE 0.22.0 on;
# only change it when the host-app integration guide introduces a new contract version.
SESSION_VERSION = 1

# Replaces VIDEPE's own app-config.js, enabling the host-app mode
APP_CONFIG = (
    "window.videpeConfig = " + json.dumps({"hostApp": {"name": APP_NAME, "apiBase": "/api"}}) + ";"
)


def choose_files() -> list[Path]:
    """Show a file selection popup and return the chosen paths."""
    root = tk.Tk()
    root.withdraw()  # hide the empty main window, show only the file dialog
    names = filedialog.askopenfilenames(
        title="Select files to open in VIDEPE (Ctrl/Shift-click to select more)",
    )
    root.destroy()
    return [Path(name) for name in names]


class Handler(http.server.BaseHTTPRequestHandler):
    """Serves VIDEPE under /videpe/ and the host-app API under /api/.

    This is the web server's request handler: every time the browser asks for a URL,
    Python's http.server creates a Handler and calls its do_GET(). It only handles GET
    requests, since VIDEPE only reads from the host app.

    In (a GET request from the browser):
        /api/session            the files to open; needs "Authorization: Bearer <TOKEN>"
        /api/files/<n>          the n-th file of FILES; needs the same token
        /videpe/app-config.js   the host-app config; no token, VIDEPE loads it at startup
        /videpe/<path>          a file of the VIDEPE build in VIDEPE_DIR; no token

    Out (the response):
        200  the session JSON, the file's bytes, APP_CONFIG, or the VIDEPE file with
             a Content-Type guessed from its extension
        401  an /api/ request with a missing or wrong token
        404  anything else: unknown paths, file numbers out of range, and paths that
             would leave VIDEPE_DIR
    """

    def do_GET(self) -> None:
        """Handle a GET request."""
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)

        # The API: every request must carry this launch's token
        if path.startswith("/api/"):
            expected = f"Bearer {TOKEN}"
            # compare_digest is the standard way to compare secrets such as tokens, passwords and
            # signatures in Python. Unlike '==', 'compare_digest' takes the same time however much
            # of the token matches, so it can't be guessed using a timing attack, where an attacker
            # sends many guesses and measures response times to find the token one character at
            # a time
            if not secrets.compare_digest(self.headers.get("Authorization", ""), expected):
                self.send_error(401)  # return 401 => missing/wrong token
                return
            if path == "/api/session":
                # The session tells VIDEPE what to open (see "The session format" in the README):
                #   version  required: the host-app contract version, see SESSION_VERSION
                #   title    optional: shown next to APP_NAME
                #   files    required: may be empty; VIDEPE then says there is nothing to open
                #     name   required: the file name with extension, which picks the viewer
                #     url    required: a path on this server, starting with "/"; VIDEPE
                #            downloads it sending the same token
                # VIDEPE rejects the whole session if any of this is wrong.
                session = {
                    "version": SESSION_VERSION,
                    "title": "Example launch",
                    "files": [
                        {"name": file.name, "url": f"/api/files/{index}"}
                        for index, file in enumerate(FILES)
                    ],
                }
                self.reply(json.dumps(session).encode(), "application/json")
                return
            # /api/files/<n>: the n-th selected file, so the browser never sees real paths
            index = path.removeprefix("/api/files/")
            if index.isdigit() and int(index) < len(FILES):
                self.reply(FILES[int(index)].read_bytes(), "application/octet-stream")
                return
            self.send_error(404)  # return 404, if file can't be grabbed
            return

        # The VIDEPE app itself (its pages and code); anyone may load these, they hold no data

        # Hand VIDEPE our settings instead of its default ones, telling it to load our files
        # (.encode() turns the text into bytes, the form in which it is sent)
        if path == "/videpe/app-config.js":
            self.reply(APP_CONFIG.encode(), "text/javascript")
            return

        # Find the requested file in the VIDEPE folder; an empty path means the start page.
        # resolve() works out where the path really ends up, e.g. after a "go up a folder" (..)
        if path.startswith("/videpe/"):
            file = (VIDEPE_DIR / (path.removeprefix("/videpe/") or "index.html")).resolve()
            # Only send it if it exists and is inside the VIDEPE folder, never other files
            if file.is_file() and VIDEPE_DIR in file.parents:
                # Tell the browser what kind of file it is (web page, script, ...) by its ending
                content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                self.reply(file.read_bytes(), content_type)
                return

        # Anything else: "not found", also for files that don't exist or are off limits
        self.send_error(404)

    def reply(self, body: bytes, content_type: str) -> None:
        """Send a 200 response with the given body."""
        # A reply is a short label (what's in it and how big it is), then the content itself
        self.send_response(200)  # 200 means "OK, here it is"
        self.send_header("Content-Type", content_type)  # what kind of content this is
        self.send_header("Content-Length", str(len(body)))  # its size, so the browser knows the end
        self.end_headers()  # done with the label, the content follows
        self.wfile.write(body)  # send the content to the browser


def main() -> None:
    """Pick the files, start the server and open VIDEPE in the browser."""
    # The files to open in VIDEPE: from the command line, or else picked in a popup
    FILES[:] = [Path(name) for name in sys.argv[1:]] or choose_files()
    if not FILES:
        sys.exit("Exiting: No files selected.")

    # Start a web server only this computer can reach (127.0.0.1), on any free port (0)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    # Open VIDEPE in the default browser, passing it the token for this launch
    webbrowser.open(f"http://127.0.0.1:{server.server_port}/videpe/?token={TOKEN}")
    # Keep answering requests until the program is stopped (Ctrl+C)
    server.serve_forever()


if __name__ == "__main__":
    main()
