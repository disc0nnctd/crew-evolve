"""Local, single-operator workspace. Run: python -m crew_evolve.server."""

import argparse
import json
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .app import App
from .model import ModelError
from .store import Store

WEB = Path(__file__).resolve().parent.parent / "web"
MAX_BODY = 8 * 1024 * 1024


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, app):
        self.app = app
        self.token = secrets.token_urlsafe(32)
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "CrewEvolve"

    def log_message(self, fmt, *args):
        pass  # Uploaded data and operator questions do not belong in access logs.

    def allowed_host(self):
        port = self.server.server_address[1]
        return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def send(self, status, body, content_type="application/json; charset=utf-8"):
        wire = body if isinstance(body, bytes) else json.dumps(body, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(wire)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(wire)

    def do_GET(self):
        if not self.allowed_host():
            return self.send(403, {"error": "Open this local workspace using localhost or 127.0.0.1."})
        if self.path == "/api/state":
            return self.send(200, self.server.app.state() | {"token": self.server.token})
        assets = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/style.css": ("style.css", "text/css; charset=utf-8")}
        if self.path in assets:
            filename, mime = assets[self.path]
            return self.send(200, (WEB / filename).read_bytes(), mime)
        self.send(404, {"error": "Not found."})

    def do_POST(self):
        if not self.allowed_host() or not secrets.compare_digest(self.headers.get("X-Workspace-Token", ""), self.server.token):
            return self.send(403, {"error": "Reload the workspace before making changes."})
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + self.headers.get("Host", ""):
            return self.send(403, {"error": "Cross-origin requests are not allowed."})
        started = time.perf_counter()
        try:
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Send a JSON request.")
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= MAX_BODY:
                return self.send(413, {"error": "Request must be between one byte and 8 MB."})
            self.connection.settimeout(10)
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("Incomplete request.")
            data = json.loads(body, parse_constant=lambda x: (_ for _ in ()).throw(ValueError("Non-finite numbers are not supported.")))
            if not isinstance(data, dict):
                raise ValueError("Request must be an object.")
            a = self.server.app
            routes = {
                "/api/import/preview": lambda: a.preview(data.get("kind"), data.get("filename"), data.get("content")),
                "/api/import/analyze": lambda: a.analyze(data.get("id")),
                "/api/import/accept": lambda: a.accept_import(data.get("id"), data.get("mapping"), data.get("revision")),
                "/api/query": lambda: a.execute(data.get("plan")),
                "/api/ask": lambda: a.ask(data.get("question")),
                "/api/teach": lambda: a.teach(data.get("question"), data.get("action")),
                "/api/assign": lambda: a.assign(data.get("crew_id"), data.get("duty_id"), data.get("role"), data.get("revision")),
                "/api/unassign": lambda: a.unassign(data.get("duty_id"), data.get("role"), data.get("revision")),
                "/api/policy/propose": lambda: a.propose_policy(data.get("policy"), data.get("reason")),
                "/api/policy/suggest": lambda: a.suggest_policy(data.get("request")),
                "/api/policy/activate": lambda: a.activate_policy(data.get("id")),
                "/api/learning/rollback": lambda: a.rollback(data.get("id")),
                "/api/demo": a.demo,
                "/api/optimize": a.optimize,
            }
            if self.path not in routes:
                return self.send(404, {"error": "Not found."})
            result = routes[self.path]()
            result["server_ms"] = round((time.perf_counter() - started) * 1000, 3)
            return self.send(200, result)
        except ModelError as exc:
            return self.send(502, {"error": str(exc)})
        except (ValueError, TypeError, KeyError, RecursionError) as exc:
            return self.send(400, {"error": str(exc) or "Invalid request."})
        except Exception:
            return self.send(500, {"error": "The operation failed. No partial change was committed."})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8780)
    parser.add_argument("--data-dir", default=".crew-evolve")
    args = parser.parse_args()
    app = App(Store(Path(args.data_dir) / "workspace.sqlite"))
    server = Server(("127.0.0.1", args.port), app)
    print(f"Crew Evolve: http://127.0.0.1:{server.server_address[1]}", flush=True)
    print("Local workspace. Model actions send the displayed context to your configured provider.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
