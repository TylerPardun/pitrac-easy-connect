# PiTrac Easy Connect

PiTrac Easy Connect is a beginner-facing connection layer for PiTrac, GSPro,
and E6 Connect. The current milestone is a desktop prototype: it provides a
local setup screen, simulator profiles, connection checks, test shots, and
mock GSPro/E6 servers that can run on macOS without golf-simulator software.

Nothing in this repository currently modifies a Raspberry Pi or microSD card.

## Run the prototype on macOS

The simplest complete demo starts both the fake simulator and Companion:

```sh
PYTHONPATH=src python3 -m pitrac_easy_connect.demo gspro
```

Use `e6` instead of `gspro` to run the E6 workflow.

On this Mac, the same demos can be opened by double-clicking `Run GSPro
Demo.command` or `Run E6 Demo.command` in Finder.

To run the pieces separately, start a fake GSPro server in one terminal:

```sh
PYTHONPATH=src python3 -m pitrac_easy_connect.mock_simulators gspro
```

Start the Companion in another terminal:

```sh
PYTHONPATH=src python3 -m pitrac_easy_connect --gspro-port 19210
```

The Companion opens `http://127.0.0.1:8787`. Select GSPro, check the
connection, and send a test shot.

For E6, replace `gspro` with `e6` when starting the mock and run the Companion
without the `--gspro-port` override. The real Windows GSPro default remains port
921. macOS development uses 19210 because macOS restricts ports below 1024.

## Tests

```sh
python3 -m pytest
```

## Current boundary

This prototype validates the user flow and simulator message formats. It does
not yet provide Raspberry Pi Wi-Fi provisioning, device pairing, a Windows
installer, or live PiTrac shot forwarding. Those are deliberately gated behind
the documented recovery and integration tests.

See [docs/product-specification.md](docs/product-specification.md) and
[docs/test-plan.md](docs/test-plan.md).

## Project checkpoint — August 18, 2026

Development is intentionally paused until the PiTrac enclosure is assembled and
the Raspberry Pi can be powered safely. The microSD card has not been modified
by this project.

The initial prototype is stored in a local Git repository. Commit `4073e10`
contains the first complete desktop milestone.

### Completed

- Written product specification, architecture, and test plan.
- Beginner-facing Companion screen that runs on macOS.
- GSPro and E6 simulator profiles.
- GSPro Open Connect test-shot formatting.
- E6 handshake, ball-data, club-data, and send-shot sequence.
- Local fake GSPro and E6 servers for development without simulator software.
- Simulator connection check.
- Test-shot acknowledgement.
- Separate `CONNECTED` and `READY` states. `READY` requires an accepted test
  shot.
- Saved simulator selection.
- One-step macOS demo launchers.
- Python package build.
- Windows executable build configuration.
- Nine passing automated tests.
- Visual and interactive browser validation of both simulator workflows.

### Not implemented yet

- Raspberry Pi operating-system and PiTrac installation audit.
- Backup image of the working microSD card.
- Pi-side Easy Connect service.
- Wi-Fi fallback state machine.
- Encrypted `PiTrac-<device-id>` setup hotspot.
- Browser-based residence Wi-Fi selection.
- Automatic rollback after incorrect Wi-Fi credentials.
- Direct Play Mode.
- Pi discovery from the Windows Companion.
- Six-digit device pairing and authentication.
- Persistent Pi-to-Companion connection.
- Forwarding live PiTrac shots through the Companion.
- Windows auto-start behavior.
- Finished Windows installer and code signing.
- Testing on Windows 10 and Windows 11.
- Testing with real GSPro.
- Testing with real E6 Connect and its armed-state behavior.
- Illustrated beginner user guide.

## Resume point after enclosure assembly

Do not install Easy Connect immediately. First establish the Pi's known-good
baseline so any later problem can be separated from the existing PiTrac setup.

1. Finish the enclosure and electrical safety checks.
2. Insert the existing microSD card and power the Raspberry Pi.
3. Confirm that PiTrac still starts and that its dashboard is reachable.
4. Connect the Mac and Pi to the same trusted network.
5. Record the following without changing the system:
   - Raspberry Pi OS release and whether it is 64-bit.
   - PiTrac version or Git commit.
   - NetworkManager version and active connection.
   - Pi hostname and current address.
   - Status of the `pitrac-web` service.
   - Existing PiTrac simulator configuration.
6. Create a backup image of the working microSD card.
7. Run the existing desktop tests on the Mac.
8. Implement and install the Pi bridge as a separate service.
9. Test device discovery and pairing on the current network.
10. Add the setup hotspot and failed-connection rollback.
11. Test moving between saved Wi-Fi networks and Direct Mode.
12. Validate the Windows Companion on a real Windows PC.
13. Validate GSPro first, then E6 Connect.

The first commands to run in this repository when development resumes are:

```sh
git status
git log -1 --oneline
python3 -m pytest -q
```

Expected test result at this checkpoint: `9 passed`.

## Known constraints and open risks

- PiTrac currently supports GSPro and E6/TruGolf. Other simulators are outside
  the first-release scope.
- The fake simulators validate our message flow but do not replace testing with
  the proprietary applications.
- GSPro uses port 921 on Windows. The Mac demo uses port 19210 because macOS
  restricts ordinary applications from opening ports below 1024.
- Direct Play Mode will normally take over the PC's Wi-Fi connection. Simulator
  login, licensing, downloads, or online play may still require internet.
- The Pi 5 has one built-in Wi-Fi radio. The reliable design switches between
  residence Wi-Fi and hotspot mode instead of depending on simultaneous modes.
- A residence guest network may block communication between the Pi and PC. The
  recovery path is Direct Mode.
- The setup hotspot must never be open. It needs a unique per-device password.
- A failed Wi-Fi change must restore the setup hotspot automatically; otherwise
  a nontechnical user could be locked out.
- A truly beginner-ready Windows release should be code-signed to avoid alarming
  Windows security warnings.

## Definition of finished

Easy Connect is not finished merely because the software opens. A release is
ready only when a nontechnical user can complete all of the following without a
terminal, IP address, or port number:

1. Power on PiTrac at a new residence.
2. Find and join the PiTrac setup signal.
3. Connect PiTrac to the residence Wi-Fi or select Direct Mode.
4. Pair the Windows Companion.
5. Select GSPro or E6.
6. Receive specific guidance if the simulator is not configured correctly.
7. Send and receive an acknowledged test shot.
8. Reach a clear `READY TO PLAY` state.
9. Recover from a wrong Wi-Fi password or isolated guest network.
10. Repeat the process after power cycling without reconfiguration.
