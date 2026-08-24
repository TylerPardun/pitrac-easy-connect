#!/usr/bin/env python3
"""Serve one deterministic release artifact for physical updater testing."""

import argparse
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--asset", required=True)
    parser.add_argument(
        "--extra-asset",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="additional release asset; may be supplied more than once",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--public-host",
        default="",
        help="host name or address written into asset URLs when --host is a bind-all address",
    )
    parser.add_argument("--port", type=int, default=8896)
    args = parser.parse_args(argv)

    files = {args.asset: args.archive.resolve()}
    for value in args.extra_asset:
        name, separator, raw_path = value.partition("=")
        if not separator or not name or not raw_path:
            parser.error("--extra-asset must use NAME=PATH")
        if name in files:
            parser.error("duplicate asset name: {}".format(name))
        files[name] = Path(raw_path).resolve()
    payloads = {name: path.read_bytes() for name, path in files.items()}
    digests = {
        name: hashlib.sha256(payload).hexdigest() for name, payload in payloads.items()
    }
    routes = {
        name: ("/asset" if name == args.asset else "/assets/" + quote(name, safe=""))
        for name in files
    }
    tag = "v" + args.version.lstrip("v")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            matched = next((name for name, route in routes.items() if self.path == route), None)
            if matched is not None:
                body = payloads[matched]
                content_type = "application/zip"
            elif self.path.endswith("/releases/latest") or self.path.endswith(
                "/releases/tags/{}".format(tag)
            ):
                advertised = args.public_host or self.server.server_address[0]
                base = "http://{}:{}".format(advertised, self.server.server_port)
                body = json.dumps(
                    {
                        "tag_name": tag,
                        "draft": False,
                        "prerelease": False,
                        "assets": [
                            {
                                "name": name,
                                "digest": "sha256:" + digests[name],
                                "browser_download_url": base + routes[name],
                            }
                            for name in files
                        ],
                    }
                ).encode("utf-8")
                content_type = "application/json"
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *values):
            print("{} - {}".format(self.address_string(), format % values), flush=True)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(
        "Serving {} asset(s) as {} at http://{}:{}".format(
            len(files), tag, args.host, server.server_port
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
