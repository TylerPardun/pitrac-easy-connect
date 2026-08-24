"""Exercise a real packaged N -> N+1 update against a local release server."""

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import psutil

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pitrac_easy_connect.companion import self_update  # noqa: E402


def _request(url, path, method="GET"):
    data = b"{}" if method == "POST" else None
    request = urllib.request.Request(
        url + path, data=data, method=method,
        headers={"X-PiTrac-App": "1", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait(predicate, detail, seconds=90):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
            if last:
                return last
        except Exception:
            pass
        time.sleep(0.25)
    raise RuntimeError("{}; last value: {!r}".format(detail, last))


def _kill_tree(pid):
    try:
        root = psutil.Process(pid)
        processes = root.children(recursive=True) + [root]
    except psutil.Error:
        return
    for process in reversed(processes):
        try:
            process.terminate()
        except psutil.Error:
            pass
    _gone, alive = psutil.wait_procs(processes, timeout=10)
    for process in alive:
        try:
            process.kill()
        except psutil.Error:
            pass


def _ordinary_browsers():
    names = {"safari", "google chrome", "chrome", "firefox", "msedge.exe",
             "chromium", "chromium-browser", "google-chrome"}
    found = set()
    for process in psutil.process_iter(["pid", "name"]):
        try:
            if str(process.info["name"] or "").lower() in names:
                found.add((process.info["pid"], str(process.info["name"])))
        except psutil.Error:
            pass
    return found


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-root", type=pathlib.Path, required=True)
    parser.add_argument("--archive", type=pathlib.Path, required=True)
    parser.add_argument("--old-version", required=True)
    parser.add_argument("--target-version", required=True)
    parser.add_argument("--system", choices=("Darwin", "Windows", "Linux"), required=True)
    parser.add_argument("--arch", choices=("arm64", "x86_64"), required=True)
    parser.add_argument("--asset", required=True)
    parser.add_argument("--port", type=int, default=8896)
    args = parser.parse_args(argv)
    archive_bytes = args.archive.read_bytes()
    digest = hashlib.sha256(archive_bytes).hexdigest()
    release = {
        "tag_name": "v" + args.target_version,
        "assets": [{"name": args.asset, "digest": "sha256:" + digest}],
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.endswith("/releases/latest") or "/releases/tags/" in self.path:
                value = dict(release)
                value["assets"] = [dict(release["assets"][0], browser_download_url=base + "/asset")]
                body = json.dumps(value).encode("utf-8")
            elif self.path == "/asset":
                body = archive_bytes
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    base = "http://127.0.0.1:{}".format(server.server_port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state = pathlib.Path(tempfile.mkdtemp(prefix="pitrac-packaged-update-"))
    canary = args.old_root.parent / "outside-install-canary.txt"
    canary.write_text("must survive", encoding="utf-8")
    executable = self_update.executable_path(args.old_root, system=args.system)
    environment = os.environ.copy()
    environment["PITRAC_UPDATE_API"] = base
    environment["PITRAC_UPDATE_STATE_DIR"] = str(state / "updates")
    os.environ["PITRAC_UPDATE_STATE_DIR"] = environment["PITRAC_UPDATE_STATE_DIR"]
    config = state / "companion.json"
    before_browsers = _ordinary_browsers()
    app = subprocess.Popen([str(executable), "--headless", "--port", str(args.port),
                            "--config", str(config)], env=environment)
    url = "http://127.0.0.1:{}".format(args.port)
    try:
        _wait(lambda: _request(url, "/api/status"), "old packaged app never served")
        _request(url, "/api/update/check", "POST")
        _wait(lambda: (_request(url, "/api/status")["update"] if
              _request(url, "/api/status")["update"].get("latest") == "v" + args.target_version
              else None), "packaged app did not select the exact release")
        response = _request(url, "/api/update/download", "POST")
        if not response.get("started"):
            raise RuntimeError("download did not start: {}".format(response))
        ready = _wait(lambda: (_request(url, "/api/status")["update"]["desktop"] if
                      _request(url, "/api/status")["update"]["desktop"]["state"] in
                      ("ready-to-restart", "preflight-failed", "verify-failed",
                       "download-failed", "install-failed") else None),
                      "packaged update did not finish staging")
        if ready["state"] != "ready-to-restart":
            raise RuntimeError("packaged update was not ready: {}".format(ready))
        applied = _request(url, "/api/update/apply", "POST")
        if not applied.get("applied"):
            raise RuntimeError("helper did not start: {}".format(applied))
        # Headless CI has no native-window close callback. Ask the old app to
        # stop through its normal guarded route; killing its whole process tree
        # would also kill the deliberately detached helper we are testing.
        _request(url, "/api/quit", "POST")
        app.wait(timeout=20)
        result_path = pathlib.Path(environment["PITRAC_UPDATE_STATE_DIR"]) / "last-install-result.json"
        result = _wait(lambda: json.loads(result_path.read_text()) if result_path.exists() else None,
                       "helper did not publish a result", 120)
        if not result.get("success"):
            raise RuntimeError("real packaged update failed: {}".format(result))
        journal_paths = list(pathlib.Path(environment["PITRAC_UPDATE_STATE_DIR"]).glob("transaction-*/journal.json"))
        if len(journal_paths) != 1:
            raise RuntimeError("expected one transaction journal")
        journal = self_update.load_journal(journal_paths[0])
        _wait(lambda: not pathlib.Path(journal["helperPath"]).exists(),
              "independent helper remained after acknowledgement", 30)
        reported = subprocess.check_output(
            [str(self_update.executable_path(args.old_root, system=args.system)), "--version"],
            text=True, timeout=20,
        ).strip()
        if reported != args.target_version:
            raise RuntimeError("updated app reports {}, expected {}".format(reported, args.target_version))
        if pathlib.Path(journal["previousInstallPath"]).exists():
            raise RuntimeError("previous install remained after acknowledgement")
        if canary.read_text(encoding="utf-8") != "must survive":
            raise RuntimeError("a file outside the install root changed")
        if not config.exists():
            raise RuntimeError("settings outside the install root did not survive")
        if _ordinary_browsers() != before_browsers:
            raise RuntimeError("an ordinary external browser process appeared")
        if journal.get("launchedPid"):
            _kill_tree(int(journal["launchedPid"]))

        # Promote the same real candidate again, but inject a missing restart
        # acknowledgement. The helper must restore the acknowledged install.
        rollback_tx = self_update.new_transaction_dir()
        rollback_archive = rollback_tx / args.archive.name
        shutil.copy2(args.archive, rollback_archive)
        staged = self_update.stage_update(
            rollback_archive, rollback_tx, args.target_version,
            system=args.system, machine=args.arch,
        )
        rollback_journal = self_update.prepare_transaction(
            archive_path=rollback_archive,
            staged=staged,
            install_root=args.old_root,
            installed_version=args.target_version,
            target_version=args.target_version,
            expected_tag="v" + args.target_version,
            asset_name=args.asset,
            asset_sha256=digest,
            transaction_root=rollback_tx,
            system=args.system,
            machine=args.arch,
            relaunch_arguments=["--port", str(args.port), "--config", str(config),
                                "--headless"],
        )
        os.environ["PITRAC_FAILURE_INJECT_NO_ACK"] = "1"
        rollback_helper = self_update.spawn_helper(rollback_journal, wait_pid=999999)
        rollback_result_path = rollback_tx / "result.json"
        rollback_result = _wait(
            lambda: json.loads(rollback_result_path.read_text())
            if rollback_result_path.exists() else None,
            "packaged rollback did not publish a result", 120,
        )
        os.environ.pop("PITRAC_FAILURE_INJECT_NO_ACK", None)
        if not rollback_result.get("rolledBack") or rollback_result.get("success"):
            raise RuntimeError("failed target was not rolled back: {}".format(rollback_result))
        rollback_data = self_update.load_journal(rollback_journal)
        if rollback_data["phase"] != "rolled-back":
            raise RuntimeError("rollback journal ended in {}".format(rollback_data["phase"]))
        if pathlib.Path(rollback_data["previousInstallPath"]).exists():
            raise RuntimeError("previous path remained occupied after rollback")
        if pathlib.Path(rollback_data["brokenInstallPath"]).exists():
            raise RuntimeError("failed promoted install remained after verified rollback")
        restored_status = _wait(
            lambda: _request(url, "/api/status"),
            "restored packaged app did not resume serving", 30,
        )
        if restored_status.get("version") != args.target_version:
            raise RuntimeError("restored app reports the wrong version: {}".format(
                restored_status.get("version")
            ))
        _wait(lambda: not pathlib.Path(rollback_data["helperPath"]).exists(),
              "rollback helper remained after completion", 30)
        if rollback_data.get("rollbackPid"):
            _kill_tree(int(rollback_data["rollbackPid"]))
        try:
            rollback_helper.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _kill_tree(rollback_helper.pid)
            raise RuntimeError("rollback helper did not exit")
        if canary.read_text(encoding="utf-8") != "must survive":
            raise RuntimeError("rollback changed the outside canary")
        print("real packaged {} update {} -> {} passed".format(
            args.system, args.old_version, args.target_version))
    finally:
        _kill_tree(app.pid)
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
