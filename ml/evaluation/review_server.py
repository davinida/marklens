"""Loopback-only HTTP server for the MarkLens human labeling workflow."""

from __future__ import annotations

import json
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from evaluation.review import (
    MAX_NOTES_LENGTH,
    ReviewAccessError,
    ReviewConflictError,
    ReviewStore,
    ReviewValidationError,
)

LOOPBACK_HOST = "127.0.0.1"
MAX_REQUEST_BYTES = 32 * 1024
CSRF_HEADER = "X-MarkLens-CSRF"
CSRF_PLACEHOLDER = "__MARKLENS_CSRF_TOKEN__"
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'none'"
)


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReviewValidationError(f"Duplicate JSON object key: {key!r}")
        result[key] = value
    return result


class ReviewHTTPServer(ThreadingHTTPServer):
    """One loopback server carrying validated store and UI dependencies."""

    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        store: ReviewStore,
        static_dir: Path,
    ) -> None:
        host, _ = server_address
        if host != LOOPBACK_HOST:
            raise ReviewValidationError("Review server must bind to 127.0.0.1")
        try:
            resolved_static_dir = static_dir.resolve(strict=True)
        except OSError as exc:
            raise ReviewValidationError("Review UI assets are unavailable") from exc
        required_assets = ("index.html", "app.js", "styles.css")
        if not all((resolved_static_dir / name).is_file() for name in required_assets):
            raise ReviewValidationError("Review UI assets are incomplete")

        self.store = store
        self.static_dir = resolved_static_dir
        self.csrf_token = secrets.token_urlsafe(32)
        super().__init__(server_address, ReviewRequestHandler)

    @property
    def allowed_hosts(self) -> frozenset[str]:
        port = self.server_address[1]
        return frozenset({f"127.0.0.1:{port}", f"localhost:{port}"})

    @property
    def allowed_origins(self) -> frozenset[str]:
        return frozenset(f"http://{host}" for host in self.allowed_hosts)


class ReviewRequestHandler(BaseHTTPRequestHandler):
    """Serve only the small local review API and its static UI."""

    server: ReviewHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format_string: str, *args: object) -> None:
        super().log_message(format_string, *args)

    def _security_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")

    def _write_bytes(
        self,
        status: HTTPStatus,
        content_type: str,
        payload: bytes,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(payload)

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._write_bytes(status, "application/json; charset=utf-8", encoded)

    def _write_error(self, status: HTTPStatus, message: str) -> None:
        self.close_connection = True
        self._write_json(status, {"error": message})

    def _request_is_local(self) -> bool:
        return self.client_address[0].startswith("127.")

    def _host_is_allowed(self) -> bool:
        host = self.headers.get("Host")
        return isinstance(host, str) and host.lower() in self.server.allowed_hosts

    def _authorize_common(self) -> bool:
        if not self._request_is_local():
            self._write_error(HTTPStatus.FORBIDDEN, "Loopback clients only")
            return False
        if not self._host_is_allowed():
            self._write_error(HTTPStatus.FORBIDDEN, "Invalid Host header")
            return False
        return True

    def _authorize_write(self) -> bool:
        if not self._authorize_common():
            return False
        if self.headers.get("Origin") not in self.server.allowed_origins:
            self._write_error(HTTPStatus.FORBIDDEN, "Invalid Origin header")
            return False
        if not secrets.compare_digest(self.headers.get(CSRF_HEADER, ""), self.server.csrf_token):
            self._write_error(HTTPStatus.FORBIDDEN, "Invalid CSRF token")
            return False
        return True

    def _parsed_path(self) -> tuple[str, str] | None:
        parsed = urlsplit(self.path)
        if parsed.query or parsed.fragment:
            self._write_error(HTTPStatus.BAD_REQUEST, "Query strings are not supported")
            return None
        return parsed.path, parsed.query

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorize_common():
            return
        parsed = self._parsed_path()
        if parsed is None:
            return
        path, _ = parsed
        try:
            if path == "/":
                source = (self.server.static_dir / "index.html").read_text(encoding="utf-8")
                if CSRF_PLACEHOLDER not in source:
                    raise ReviewValidationError("Review UI is missing its CSRF marker")
                payload = source.replace(CSRF_PLACEHOLDER, self.server.csrf_token).encode("utf-8")
                self._write_bytes(HTTPStatus.OK, "text/html; charset=utf-8", payload)
                return
            if path == "/app.js":
                self._serve_static("app.js", "text/javascript; charset=utf-8")
                return
            if path == "/styles.css":
                self._serve_static("styles.css", "text/css; charset=utf-8")
                return
            if path == "/api/state":
                self._write_json(HTTPStatus.OK, self.server.store.public_state())
                return
            if path.startswith("/image/"):
                self._serve_image(path)
                return
            self._write_error(HTTPStatus.NOT_FOUND, "Not found")
        except ReviewAccessError as exc:
            self._write_error(HTTPStatus.FORBIDDEN, str(exc))
        except ReviewConflictError as exc:
            self._write_error(HTTPStatus.CONFLICT, str(exc))
        except ReviewValidationError as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, str(exc))
        except OSError:
            self._write_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Local file read failed")

    def _serve_static(self, name: str, content_type: str) -> None:
        payload = (self.server.static_dir / name).read_bytes()
        self._write_bytes(HTTPStatus.OK, content_type, payload)

    def _serve_image(self, path: str) -> None:
        segments = path.split("/")
        if len(segments) != 4 or segments[0] != "" or segments[1] != "image":
            raise ReviewAccessError("Image route is invalid")
        pair_id, side = segments[2], segments[3]
        if (
            not pair_id
            or len(pair_id) > 80
            or not all(
                character.isascii() and (character.isalnum() or character in "_-")
                for character in pair_id
            )
        ):
            raise ReviewAccessError("Image pair identifier is invalid")
        image_path, content_type, expected_size = self.server.store.image_response(pair_id, side)
        payload = image_path.read_bytes()
        if len(payload) != expected_size:
            raise ReviewConflictError("Image changed while it was being read")
        self._write_bytes(HTTPStatus.OK, content_type, payload)

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorize_write():
            return
        parsed = self._parsed_path()
        if parsed is None:
            return
        path, _ = parsed
        if path != "/api/annotation":
            self._write_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        try:
            payload = self._read_json_body()
            response = self._save_annotation(payload)
            self._write_json(HTTPStatus.OK, response)
        except ReviewAccessError as exc:
            self._write_error(HTTPStatus.FORBIDDEN, str(exc))
        except ReviewConflictError as exc:
            self._write_error(HTTPStatus.CONFLICT, str(exc))
        except ReviewValidationError as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, str(exc))
        except OSError:
            self._write_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Atomic save failed")

    def _read_json_body(self) -> dict[str, Any]:
        if self.headers.get("Transfer-Encoding") is not None:
            raise ReviewValidationError("Transfer-Encoding is not supported")
        if self.headers.get_content_type() != "application/json":
            raise ReviewValidationError("Content-Type must be application/json")
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or "")
        except ValueError as exc:
            raise ReviewValidationError("A valid Content-Length is required") from exc
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ReviewValidationError(f"Request body must contain 1-{MAX_REQUEST_BYTES} bytes")
        data = self.rfile.read(length)
        if len(data) != length:
            raise ReviewValidationError("Request body ended early")
        try:
            value = json.loads(
                data.decode("utf-8"), object_pairs_hook=_object_without_duplicate_keys
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReviewValidationError("Request must be valid UTF-8 JSON") from exc
        if not isinstance(value, dict):
            raise ReviewValidationError("Request body must be a JSON object")
        return value

    def _save_annotation(self, payload: dict[str, Any]) -> dict[str, Any]:
        expected_fields = {
            "pair_id",
            "expected_revision",
            "visual_similarity",
            "confidence",
            "notes",
            "clear",
        }
        if set(payload) != expected_fields:
            raise ReviewValidationError("Annotation request fields do not match the contract")
        if not isinstance(payload["pair_id"], str):
            raise ReviewValidationError("pair_id must be a string")
        if not isinstance(payload["expected_revision"], str):
            raise ReviewValidationError("expected_revision must be a string")
        if payload["visual_similarity"] is not None and not isinstance(
            payload["visual_similarity"], str
        ):
            raise ReviewValidationError("visual_similarity must be a string or null")
        if payload["confidence"] is not None and not isinstance(payload["confidence"], str):
            raise ReviewValidationError("confidence must be a string or null")
        if payload["notes"] is not None and not isinstance(payload["notes"], str):
            raise ReviewValidationError("notes must be a string or null")
        if isinstance(payload["notes"], str) and len(payload["notes"]) > MAX_NOTES_LENGTH:
            raise ReviewValidationError(f"notes must not exceed {MAX_NOTES_LENGTH} characters")
        if not isinstance(payload["clear"], bool):
            raise ReviewValidationError("clear must be a boolean")
        return self.server.store.save_annotation(
            pair_id=payload["pair_id"],
            expected_revision=payload["expected_revision"],
            visual_similarity=payload["visual_similarity"],
            confidence=payload["confidence"],
            notes=payload["notes"],
            clear=payload["clear"],
        )

    def do_HEAD(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_PUT(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_DELETE(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_PATCH(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def _method_not_allowed(self) -> None:
        if not self._authorize_common():
            return
        self._write_error(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")


def create_review_server(
    store: ReviewStore,
    *,
    port: int,
    static_dir: Path | None = None,
) -> ReviewHTTPServer:
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise ReviewValidationError("Port must be an integer between 0 and 65535")
    ui_dir = static_dir or Path(__file__).with_name("review_ui")
    try:
        return ReviewHTTPServer((LOOPBACK_HOST, port), store, ui_dir)
    except OSError as exc:
        raise ReviewValidationError(f"Cannot bind local review server on port {port}") from exc


def review_url(server: ReviewHTTPServer) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}/"


def serve_review(server: ReviewHTTPServer) -> None:
    """Run until interrupted; the caller owns startup messaging and browser launch."""
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()


__all__ = [
    "CSRF_HEADER",
    "LOOPBACK_HOST",
    "ReviewHTTPServer",
    "create_review_server",
    "review_url",
    "serve_review",
]
