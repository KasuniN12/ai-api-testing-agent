"""Lightweight standard-library mock HTTP server for testing against sample_openapi.json."""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import re

DATABASE = [
    {"id": 1, "username": "alice", "email": "alice@example.com", "role": "admin"},
    {"id": 2, "username": "bob", "email": "bob@example.com", "role": "member"},
]


class MockAPIHandler(BaseHTTPRequestHandler):
    """Handles mock requests conforming to sample_openapi.json."""

    def _send_json(self, status_code: int, data: dict):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_GET(self):
        if self.path == "/api/reset":
            global DATABASE
            DATABASE.clear()
            DATABASE.extend([
                {"id": 1, "username": "alice", "email": "alice@example.com", "role": "admin"},
                {"id": 2, "username": "bob", "email": "bob@example.com", "role": "member"},
            ])
            self._send_json(200, {"message": "Database reset successful", "count": len(DATABASE)})
            return

        if self.path.startswith("/api/users"):
            match = re.match(r"^/api/users/(\d+)$", self.path)
            if match:
                user_id = int(match.group(1))
                user = next((u for u in DATABASE if u["id"] == user_id), None)
                if user:
                    self._send_json(200, user)
                else:
                    self._send_json(404, {"error": "User not found"})
                return

            self._send_json(200, {"users": DATABASE, "count": len(DATABASE)})
            return

        self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path == "/api/users":
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                self._send_json(400, {"error": "Empty request body"})
                return

            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self._send_json(400, {"error": "Invalid JSON"})
                return

            if not isinstance(data, dict):
                self._send_json(400, {"error": "Request body must be a JSON object"})
                return

            if "username" not in data or "email" not in data:
                self._send_json(400, {"error": "Missing required fields: username, email"})
                return

            if "@" not in str(data.get("email", "")):
                self._send_json(400, {"error": "Invalid email address format"})
                return

            new_user = {
                "id": len(DATABASE) + 1,
                "username": data["username"],
                "email": data["email"],
                "role": data.get("role", "member"),
            }
            DATABASE.append(new_user)
            self._send_json(201, new_user)
            return

        self._send_json(404, {"error": "Not found"})

    def do_DELETE(self):
        if self.path.startswith("/api/users"):
            match = re.match(r"^/api/users/(\d+)$", self.path)
            if match:
                user_id = int(match.group(1))
                user = next((u for u in DATABASE if u["id"] == user_id), None)
                if user:
                    DATABASE.remove(user)
                    self.send_response(204)
                    self.end_headers()
                else:
                    self._send_json(404, {"error": "User not found"})
                return

        self._send_json(404, {"error": "Not found"})

    def log_message(self, format, *args):
        # Suppress noisy standard console logs
        pass


def run_mock_server(port: int = 8000):
    """Run local mock server on specified port."""
    server = HTTPServer(("0.0.0.0", port), MockAPIHandler)
    print(f"Mock API server listening on http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run_mock_server()
