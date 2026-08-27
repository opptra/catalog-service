"""Local review UI for inbound QC reports. Not mounted on the FastAPI app.

From ``server/``:

    python -m pipelines.inbound_qc.viewer --report ../local-data/inbound-qc/latest

    python -m pipelines.inbound_qc.viewer \\
        --report ../local-data/inbound-qc/latest \\
        --product ../sample_data/one/bedsheet_mandatoryV1.csv \\
        --images ../sample_data/one/images.zip
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from core.exceptions.inbound_qc import InboundQcError
from pipelines.inbound_qc.view import ReviewStore

_PAGE = Path(__file__).with_name("review.html")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open a local page to inspect inbound QC findings against photos."
    )
    parser.add_argument(
        "--report",
        type=Path,
        required=True,
        help="Directory with findings.csv and summary.csv (e.g. local-data/inbound-qc/latest)",
    )
    parser.add_argument("--product", type=Path, help="Product CSV/XLSX (default: sources.json)")
    parser.add_argument("--images", type=Path, help="Images ZIP (default: sources.json)")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the review page in a browser",
    )
    return parser.parse_args(argv)


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _make_handler(store: ReviewStore) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            path = args[0] if args else ""
            if isinstance(path, str) and "/image/" in path:
                return
            super().log_message(fmt, *args)

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, status: int, payload: object) -> None:
            self._send(status, _json_bytes(payload), "application/json; charset=utf-8")

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = unquote(parsed.path)

            if path in {"/", "/index.html"}:
                self._send(200, _PAGE.read_bytes(), "text/html; charset=utf-8")
                return
            if path == "/api/batch":
                self._send_json(200, store.batch_payload())
                return

            sku_image_prefix = "/api/sku/"
            if path.startswith(sku_image_prefix):
                rest = path[len(sku_image_prefix) :]
                if "/image/" in rest:
                    sku_id, filename = rest.split("/image/", 1)
                    try:
                        photo = store.image(sku_id, filename)
                    except InboundQcError as exc:
                        self._send_json(404, {"error": str(exc)})
                        return
                    body = photo.content or b""
                    self._send(200, body, photo.content_type)
                    return
                try:
                    self._send_json(200, store.sku_payload(rest))
                except InboundQcError as exc:
                    self._send_json(404, {"error": str(exc)})
                return

            self._send_json(404, {"error": "not found"})

    return Handler


def serve_review(
    report: Path,
    *,
    product: Path | None = None,
    images: Path | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
) -> int:
    """Serve the review page until interrupted. Called by the QC CLI and this module."""
    if not _PAGE.is_file():
        print(f"error: missing review page {_PAGE}", file=sys.stderr)
        return 2
    try:
        store = ReviewStore.open(report, product=product, images=images)
    except InboundQcError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    handler = _make_handler(store)
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}/"
    print(f"Inbound QC review: {url}", flush=True)
    print(f"report:  {store.report_dir}", flush=True)
    print(f"product: {store.product_path}", flush=True)
    print(f"images:  {store.images_path}", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return serve_review(
        args.report,
        product=args.product,
        images=args.images,
        host=args.host,
        port=args.port,
        open_browser=args.open,
    )


if __name__ == "__main__":
    raise SystemExit(main())
