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

from pitrac_easy_connect.common import link, release_manifest  # noqa: E402
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
    if alive:
        psutil.wait_procs(alive, timeout=10)


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


def _descendant_names(pid):
    try:
        root = psutil.Process(pid)
        return [str(process.name()).lower() for process in root.children(recursive=True)]
    except psutil.Error:
        return []


def _signed_manifest(args, archive_bytes, digest, state):
    """Build the exact authenticated local release the current app requires."""

    if args.signing_key is None:
        return None, None
    keys = release_manifest._PINNED_KEYS
    if len(keys) != 1:
        raise RuntimeError(
            "packaged smoke needs exactly one active release signing key, found {}"
            .format(len(keys))
        )
    key_id = next(iter(keys))
    platform_entry = next(
        (dict(entry) for entry in release_manifest.DESKTOP_PLATFORMS
         if entry["system"] == args.system and entry["machine"] == args.arch),
        None,
    )
    if platform_entry is None:
        raise RuntimeError("no manifest platform declaration matches this build")
    manifest = {
        "manifestVersion": release_manifest.MANIFEST_VERSION,
        "channel": "stable",
        "signingKeyId": key_id,
        "application": {
            "version": args.target_version,
            "tag": "v" + args.target_version,
        },
        "protocol": {
            "version": link.PROTOCOL_VERSION,
            "minimum": link.PROTOCOL_VERSION,
            "maximum": link.PROTOCOL_VERSION,
        },
        "packageLayoutVersion": self_update.PACKAGE_LAYOUT_VERSION,
        "minimumCompatible": {
            "desktop": release_manifest.MINIMUM_COMPATIBLE_DESKTOP,
            "piService": release_manifest.MINIMUM_COMPATIBLE_PI_SERVICE,
        },
        "assets": [{
            "name": args.asset,
            "size": len(archive_bytes),
            "sha256": digest,
        }],
        "desktop": {"platforms": [platform_entry]},
        "pi": {
            "asset": "",
            "hardware": list(release_manifest.PI_HARDWARE),
            "os": list(release_manifest.PI_OPERATING_SYSTEMS),
            "python": {"minimum": release_manifest.PI_MINIMUM_PYTHON},
        },
        "pitrac": {"minimumVersion": release_manifest.PITRAC_MINIMUM_VERSION},
    }
    manifest_path = state / release_manifest.MANIFEST_ASSET
    signature_path = state / release_manifest.SIGNATURE_ASSET
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    subprocess.run([
        sys.executable,
        str(ROOT / "packaging" / "sign-release-manifest.py"),
        str(manifest_path),
        "--key", str(args.signing_key),
        "--out", str(signature_path),
    ], check=True)
    return manifest_path.read_bytes(), signature_path.read_bytes()


def _manual_update_leg(executable, args, environment, state, base_browsers):
    """Drive the refused-automatic-install path and watch for a browser.

    This is the path that used to hand a releases URL to the operating system.
    It now retains the verified package and reveals it in Finder or File
    Explorer, so the proof that matters is that reaching it -- through the
    real packaged binary, its real native window, and its real page -- starts
    no ordinary browser at all.

    It runs before the update itself, as a separate instance with its own
    port, settings and update state, because only the preceding release is
    behind the release the local server advertises. Preflight is refused by
    injection rather than by an unsupported install location: the refusal has
    to happen after a genuine download, verification and staging, which is
    exactly where the manual package is retained.
    """

    port = args.port + 1
    url = "http://127.0.0.1:{}".format(port)
    manual_state = state / "manual-updates"
    config = state / "manual-companion.json"
    manual_environment = dict(environment)
    manual_environment["PITRAC_UPDATE_STATE_DIR"] = str(manual_state)
    manual_environment["PITRAC_FAILURE_INJECT_PREFLIGHT"] = "1"
    app = subprocess.Popen([
        str(executable), "--smoke-test", "--port", str(port),
        "--config", str(config),
        "--packaged-smoke-installed-version", args.old_version,
    ], env=manual_environment)
    try:
        _wait(
            lambda: _request(url, "/api/status").get("window", {}).get("state") == "native",
            "manual-update instance never created its native window",
        )
        _request(url, "/api/update/check", "POST")
        _wait(lambda: (_request(url, "/api/status")["update"] if
              _request(url, "/api/status")["update"].get("latest") == "v" + args.target_version
              else None), "manual-update instance did not select the exact release")
        response = _request(url, "/api/update/download", "POST")
        if not response.get("started"):
            raise RuntimeError("manual-update download did not start: {}".format(response))
        desktop = _wait(lambda: (_request(url, "/api/status")["update"]["desktop"] if
                        _request(url, "/api/status")["update"]["desktop"]["state"] in
                        ("preflight-failed", "ready-to-restart", "verify-failed",
                         "download-failed", "install-failed") else None),
                        "manual-update instance did not reach a settled state")
        if desktop["state"] != "preflight-failed":
            raise RuntimeError("expected a refused automatic install: {}".format(desktop))
        saved = desktop.get("savedPackagePath") or ""
        if not saved:
            raise RuntimeError("the refused install offered no saved package")
        expected_action = {"Darwin": "Reveal in Finder",
                           "Windows": "Show in File Explorer"}[args.system]
        if desktop.get("revealAction") != expected_action:
            raise RuntimeError("wrong reveal label: {}".format(desktop.get("revealAction")))

        revealed = _request(url, "/api/update/reveal", "POST")
        # Whether a file manager is actually reachable on a CI runner is not
        # the point, and is not asserted. The exact local path being handed
        # back, from inside the private update-state directory, is.
        if revealed.get("path") != saved:
            raise RuntimeError("reveal returned {}, expected {}".format(
                revealed.get("path"), saved))
        if not pathlib.Path(saved).is_file():
            raise RuntimeError("the retained package is not a file: {}".format(saved))
        if manual_state.resolve() not in pathlib.Path(saved).resolve().parents:
            raise RuntimeError("the retained package is outside the update state")

        appeared = _ordinary_browsers() - base_browsers
        if appeared:
            raise RuntimeError(
                "the manual-update path started an ordinary browser: {}".format(appeared)
            )
        print("refused automatic install revealed {} and opened no browser".format(saved))
    finally:
        try:
            _request(url, "/api/quit", "POST")
            app.wait(timeout=20)
        except Exception:
            pass
        _kill_tree(app.pid)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-root", type=pathlib.Path, required=True)
    parser.add_argument("--archive", type=pathlib.Path, required=True)
    parser.add_argument("--old-version", required=True)
    parser.add_argument("--target-version", required=True)
    parser.add_argument("--system", choices=("Darwin", "Windows"), required=True)
    parser.add_argument("--arch", choices=("arm64", "x86_64"), required=True)
    parser.add_argument("--asset", required=True)
    parser.add_argument("--port", type=int, default=8896)
    parser.add_argument(
        "--signing-key", type=pathlib.Path,
        help="release private key; enables the signed current-package manual-recovery leg",
    )
    args = parser.parse_args(argv)
    archive_bytes = args.archive.read_bytes()
    digest = hashlib.sha256(archive_bytes).hexdigest()
    state = pathlib.Path(tempfile.mkdtemp(prefix="pitrac-packaged-update-"))
    manifest_bytes, signature_bytes = _signed_manifest(
        args, archive_bytes, digest, state
    )
    served = {"/asset": archive_bytes}
    release = {
        "tag_name": "v" + args.target_version,
        "assets": [{
            "name": args.asset,
            "digest": "sha256:" + digest,
            "path": "/asset",
        }],
    }
    if manifest_bytes is not None:
        served["/manifest"] = manifest_bytes
        served["/signature"] = signature_bytes
        release["assets"].extend((
            {"name": release_manifest.MANIFEST_ASSET, "path": "/manifest"},
            {"name": release_manifest.SIGNATURE_ASSET, "path": "/signature"},
        ))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.endswith("/releases/latest") or "/releases/tags/" in self.path:
                value = dict(release)
                value["assets"] = [
                    dict(entry, browser_download_url=base + entry["path"])
                    for entry in release["assets"]
                ]
                body = json.dumps(value).encode("utf-8")
            elif self.path in served:
                body = served[self.path]
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
    canary = args.old_root.parent / "outside-install-canary.txt"
    canary.write_text("must survive", encoding="utf-8")
    executable = self_update.executable_path(args.old_root, system=args.system)
    environment = os.environ.copy()
    environment["PITRAC_UPDATE_API"] = base
    environment["PITRAC_UPDATE_STATE_DIR"] = str(state / "updates")
    environment["PITRAC_PACKAGED_UPDATE_SMOKE"] = "1"
    os.environ["PITRAC_UPDATE_STATE_DIR"] = environment["PITRAC_UPDATE_STATE_DIR"]
    config = state / "companion.json"
    before_browsers = _ordinary_browsers()
    if args.signing_key is not None:
        manual_candidate = self_update.stage_update(
            args.archive, state / "manual-candidate", args.target_version,
            system=args.system, machine=args.arch,
        )
        _manual_update_leg(
            manual_candidate.executable, args, environment, state, before_browsers
        )
    else:
        print(
            "manual-recovery packaged leg skipped: no release signing key was supplied"
        )
    app = subprocess.Popen([str(executable), "--smoke-test", "--port", str(args.port),
                            "--config", str(config)], env=environment)
    url = "http://127.0.0.1:{}".format(args.port)
    try:
        old_status = _wait(
            lambda: (
                status if (status := _request(url, "/api/status")).get("window", {}).get("state")
                == "native" else None
            ),
            "old packaged app never created its native window",
        )
        if old_status.get("version") != args.old_version:
            raise RuntimeError(
                "preceding artifact reports {}, expected {}".format(
                    old_status.get("version"), args.old_version
                )
            )
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
        # Ask the old app to stop through its normal guarded route; killing its
        # whole process tree would also kill the deliberately detached helper.
        _request(url, "/api/quit", "POST")
        app.wait(timeout=20)
        update_state = pathlib.Path(environment["PITRAC_UPDATE_STATE_DIR"])

        def transaction_result():
            for path in update_state.glob("transaction-*/result.json"):
                try:
                    return path, json.loads(path.read_text())
                except (OSError, ValueError):
                    pass
            return None

        result_path, result = _wait(
            transaction_result, "helper did not publish a transaction result", 120
        )
        if not result.get("success"):
            raise RuntimeError("real packaged update failed: {}".format(result))
        journal_paths = [result_path.parent / "journal.json"]
        if len(journal_paths) != 1:
            raise RuntimeError("expected one transaction journal")
        journal = self_update.load_journal(journal_paths[0])
        updated_status = _wait(
            lambda: (
                status if (
                    (status := _request(url, "/api/status")).get("version")
                    == args.target_version
                    and status.get("window", {}).get("state") == "native"
                ) else None
            ),
            "candidate never proved its exact version in a native window",
            120,
        )
        page = _wait(
            lambda: (
                check if (
                    (check := _request(url, "/api/page-check")).get("requests", {}).get(
                        "POST /api/search", 0
                    ) >= 1
                    and check.get("requests", {}).get(
                        "POST /api/finish-setup", 0
                    ) >= 1
                ) else None
            ),
            "candidate native page did not complete guarded requests",
            120,
        )
        launched_pid = int(journal.get("launchedPid") or 0)
        if args.system == "Windows":
            names = _wait(
                lambda: (
                    found if "msedgewebview2.exe" in (
                        found := _descendant_names(launched_pid)
                    ) else None
                ),
                "candidate never created its embedded WebView2 process tree",
                60,
            )
            if "msedge.exe" in names:
                raise RuntimeError("candidate launched ordinary Edge")
        else:
            from AppKit import NSWorkspace
            registrations = [
                app for app in NSWorkspace.sharedWorkspace().runningApplications()
                if app.bundleIdentifier() == "com.pitrac.easyconnect"
            ]
            if len(registrations) != 1 or int(registrations[0].activationPolicy()) != 0:
                raise RuntimeError(
                    "candidate is not exactly one foreground macOS application: {}".format(
                        [(app.processIdentifier(), int(app.activationPolicy()))
                         for app in registrations]
                    )
                )

        # A second candidate launch must activate the existing native window
        # and exit, not create a second application instance.
        second = subprocess.Popen([
            str(self_update.executable_path(args.old_root, system=args.system)),
            "--port", str(args.port), "--config", str(config),
        ], env=environment)
        if second.wait(timeout=20) != 0:
            raise RuntimeError("second candidate launch did not exit cleanly")
        activated = _request(url, "/api/page-check").get("requests", {}).get(
            "POST /api/activate", 0
        )
        if activated < 1:
            raise RuntimeError("second candidate launch did not activate the first window")
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
        if _ordinary_browsers() - before_browsers:
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
        os.environ["PITRAC_ALLOW_HEADLESS_UPDATE_ACK"] = "1"
        rollback_helper = self_update.spawn_helper(rollback_journal, wait_pid=999999)
        rollback_result_path = rollback_tx / "result.json"
        rollback_result = _wait(
            lambda: json.loads(rollback_result_path.read_text())
            if rollback_result_path.exists() else None,
            "packaged rollback did not publish a result", 120,
        )
        os.environ.pop("PITRAC_FAILURE_INJECT_NO_ACK", None)
        os.environ.pop("PITRAC_ALLOW_HEADLESS_UPDATE_ACK", None)
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
        # If the harness itself fails after the helper has relaunched the
        # candidate, that candidate is deliberately detached from ``app``.
        # Always recover its recorded PIDs from the durable journals so a
        # failed CI assertion cannot leave a GUI process or occupied port.
        update_state = pathlib.Path(environment["PITRAC_UPDATE_STATE_DIR"])
        for journal_path in update_state.glob("transaction-*/journal.json"):
            try:
                cleanup_journal = self_update.load_journal(journal_path)
            except Exception:
                continue
            for field in ("launchedPid", "rollbackPid"):
                if cleanup_journal.get(field):
                    _kill_tree(int(cleanup_journal[field]))
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
