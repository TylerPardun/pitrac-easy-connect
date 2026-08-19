# PiTrac Easy Connect

PiTrac Easy Connect lets someone with no Linux, networking, or software
experience move a PiTrac enclosure to a new house, get it onto the Wi-Fi, pair a
Windows simulator PC, and start playing — without a terminal, an SSH session, an
IP address, or a port number.

It is two programs that talk to each other:

- a **service on the Raspberry Pi** inside the enclosure, which owns Wi-Fi
  setup, the recovery hotspot, discovery, pairing, the startup self-test, and a
  relay that carries shots off the Pi;
- a **Companion on the Windows simulator PC**, which finds the enclosure, pairs
  with it, and hands shots to GSPro or E6 Connect.

Easy Connect is a separate service. It does not modify, patch, or link against
PiTrac. It reads PiTrac's state and writes four values into PiTrac's own
settings file to point its simulator output at the local relay.

This README is the product requirements document and the project's source of
truth. A feature listed as a requirement is not necessarily implemented; the
project checkpoint below records the current implementation state.

## How a shot reaches the simulator

`pitrac_lm` is a TCP *client*: it dials out to whatever address is configured as
its simulator. Easy Connect points it at `127.0.0.1` once, at install time, and
then stands in for the simulator:

```text
pitrac_lm  ->  Pi relay        ==  paired link  ==>  Companion  ->  GSPro 127.0.0.1:921
(127.0.0.1:9210 / :9248)          (encrypted Wi-Fi)                 E6    127.0.0.1:2483
```

Two consequences make this the right shape:

- **Moving house never touches PiTrac's configuration.** The relay address is
  loopback, so it is correct in every house, on every network, forever.
- **The Companion dials out to the enclosure, never the reverse.** Windows
  permits outbound connections by default, so no firewall rule is ever needed,
  and the PC's address can change without breaking anything.

The simulator's own protocol travels the link untouched in both directions. The
relay counts messages; it does not rewrite them.

## Try it on a Mac, with no hardware at all

One command starts a fake golf simulator, a simulated Raspberry Pi running the
real Easy Connect service, and the real Companion, then pairs them:

```bash
PYTHONPATH=src python3 -m pitrac_easy_connect.demo gspro
```

Use `e6` instead of `gspro` for the E6 workflow. Two tabs open: the enclosure's
setup page and the Companion. Everything except the fake Pi hardware and the
fake simulator is the code that ships.

To walk through first-run setup by hand instead of having it done for you:

```bash
PYTHONPATH=src python3 -m pitrac_easy_connect.demo gspro --no-network --no-pair
```

The `Run GSPro Demo.command` and `Run E6 Demo.command` files do the same thing
from Finder.

## Guides

- **[Setting up PiTrac](docs/beginner-guide.html)** &mdash; the illustrated guide for
  whoever owns the enclosure. Printable, and written for someone who has never
  used a terminal. A plain-text version is at
  [beginner-guide.md](docs/beginner-guide.md).
- **[Operator guide](docs/operator-guide.md)** &mdash; installing on a new Raspberry Pi 5,
  setting up simulator PCs, building a second enclosure, upgrading, and
  diagnosing a misbehaving unit.
- **[Pi baseline audit](docs/pi-baseline-audit.md)** &mdash; what the target Pi actually
  looks like, and the integration constraints that follow from it.

## Install on the Raspberry Pi

Copy this directory to the Pi, then:

```bash
sudo ./packaging/pi/install.sh
```

The installer checks the Pi model, architecture, Python version, and
NetworkManager, installs the service, starts it, and prints the owner card that
belongs with the enclosure. It is safe to run again to upgrade: the device
identity, saved networks, pairings, and PiTrac's calibration are never touched.

It leaves the hostname alone by default, because renaming would change the
`.local` address the owner already uses. Pass `--set-hostname` when a second
enclosure joins the same network. `--uninstall` removes the service and keeps
the settings.

## Run the Companion on the simulator PC

```bash
python3 -m pitrac_easy_connect.companion.app
```

It opens `http://127.0.0.1:8787`, bound to loopback only. On Windows the
packaged executable is built by `packaging/PiTracCompanion.spec`.

## Tests

```bash
python3 -m pytest -q
```

The suite runs on macOS, Linux, and Windows, and on the Raspberry Pi itself.
Every failure path that would otherwise strand a user — a wrong password, a
router that never hands out an address, an isolated guest network, the power
cut mid-change — is driven through a simulated Raspberry Pi rather than by hand.

## Security notes

- The Companion binds to loopback only.
- The setup page can set a country, join a network, show a pairing code, and
  perform recovery actions. It has no route that executes a command, and it
  cannot read a Wi-Fi password back out.
- State-changing requests to the setup page require a custom header, a matching
  `Origin`, and a recognised `Host`, which together block cross-site requests
  and DNS rebinding.
- Pairing runs an ephemeral Diffie-Hellman exchange authenticated by the
  six-digit code, so **the pairing secret is never transmitted**. A passive
  listener on the network learns nothing reusable.
- After pairing, each side proves it holds the secret by answering a fresh
  random challenge. The secret itself never crosses the wire again.
- Every paired computer gets its own secret. There is no fleet-wide password.
- The setup hotspot is never open and its password is unique per enclosure.
- The Pi service runs as root because it drives NetworkManager, sets the
  hostname, and halts the machine. The systemd unit narrows what that root can
  reach, and the browser-facing code has no command execution path.

Known limitation: an attacker who is already on the network and who guesses the
six-digit code during its five-minute life could pair. That is what the rate
limit exists for — five wrong attempts stop the enclosure answering for ten
minutes.

## Product requirements document

- **Status:** Draft for the beginner-ready first release
- **Hardware target:** PiTrac V3 enclosure with Raspberry Pi 5
- **Desktop target:** Windows 11 x86-64, plus tested legacy compatibility with
  Windows 10 22H2
- **Simulator target:** GSPro Open Connect and E6 Connect through TruSimAPI
- **Development host:** macOS until assembled hardware and a Windows test PC
  are available

### Product promise

A person with no Linux, networking, or software-development experience can
move a PiTrac enclosure to a new residence, connect it to a Windows simulator
PC, select GSPro or E6, verify the complete connection, and start playing. The
normal workflow must not require a terminal, IP address, port number, router
configuration, or manual microSD-card editing.

When something fails, the product must identify the failed component, present a
specific next action, and preserve a path back to a working state. A generic
`Disconnected` or `Something went wrong` message is not sufficient.

### Goals

- Make first setup and moving residences understandable to a nontechnical user.
- Support both residence Wi-Fi and router-free Direct Mode.
- Distinguish enclosure, network, Companion, and simulator failures.
- Preserve calibration and configuration across restarts and software updates.
- Recover automatically from incorrect Wi-Fi settings, interrupted updates,
  application crashes, and ordinary power loss.
- Maintain one versioned software release across multiple V3 enclosures while
  preserving each enclosure's identity and settings.
- Keep normal operation local and functional without a cloud account.

### First-release non-goals

- Supporting simulators other than GSPro and E6/TruGolf.
- Changing PiTrac's ball-measurement or image-processing algorithms.
- Operating GSPro or E6 licensing, login, installation, or account management.
- Internet-accessible remote administration or permanent remote support access.
- Required cloud accounts, cloud fleet management, or behavioral telemetry.
- Simultaneous hotspot and residence-Wi-Fi operation on the Pi's single radio.
- Automatically installing untested upstream PiTrac versions.
- Hiding advanced network limitations behind a false `READY` status.

### User-visible operating states

The Companion and setup page must use the same state names and explain the next
action. Color may reinforce a state but must never be the only indication.

- `STARTING`: services and hardware checks are still running.
- `SETUP REQUIRED`: no usable network or trusted PC is configured; the setup
  hotspot is available.
- `CONNECTING`: a time-limited network, pairing, or simulator attempt is active.
- `CONNECTED`: the Companion can communicate with the enclosure, but the full
  simulator path has not been validated.
- `SIMULATOR ACTION REQUIRED`: GSPro or E6 needs a specific user action.
- `READY TO PLAY`: the Pi, Companion, selected simulator, and acknowledged test
  path are healthy.
- `UPDATING`: a verified update is being staged or installed; power must remain
  connected.
- `RECOVERY REQUIRED`: automatic recovery did not complete and the interface
  presents a safe recovery action.
- `SHUTTING DOWN`: configuration has been saved and the system is preparing to
  report when power can be removed.

No stale `READY TO PLAY` state may survive a lost camera, stopped PiTrac
process, broken Companion connection, or simulator restart.

### PRD-100: First-run setup and Wi-Fi provisioning

The enclosure must start an encrypted setup network named
`PiTrac-<device-id>` when no saved residence network succeeds. Its unique setup
password and recovery address must be supplied on a label or owner card. A QR
code may be included, but the printed text must remain usable without it.

The setup flow must:

1. Ask for the wireless country before enabling normal Wi-Fi operation.
2. Scan for and display nearby networks without exposing technical fields.
3. Support ordinary 2.4 GHz and 5 GHz WPA2/WPA3-Personal networks.
4. Correctly handle spaces, punctuation, and non-ASCII characters in network
   names and passwords.
5. Offer manual entry for a hidden network.
6. Preserve previously working profiles until the new connection is confirmed.
7. Create a NetworkManager checkpoint before applying a disruptive change.
8. Confirm two-way Pi-to-Companion communication on the new network.
9. Commit the change only after confirmation; otherwise restore the previous
   connection or setup hotspot automatically.
10. Return to setup mode after a defined timeout instead of becoming
    unreachable.

Captive-portal and WPA-Enterprise networks are not required in the first
release. They must be detected or rejected with an explanation and a Direct
Mode recommendation. Guest-network client isolation must produce the same
actionable Direct Mode recovery path.

**Acceptance:** entering an incorrect password, losing power during the change,
or joining an isolated network cannot permanently remove the setup hotspot or a
previously working profile.

### PRD-110: Direct Mode

Direct Mode must let the Windows PC join the encrypted PiTrac setup signal and
play without a router. It must use the same pairing and authentication as
residence mode. The UI must warn that the PC's Wi-Fi internet connection may be
temporarily unavailable and that simulator login, licensing, downloads, and
online play remain the simulator vendor's responsibility.

Switching between Direct Mode and residence mode must not delete pairings,
calibration, or simulator preferences.

**Acceptance:** after moving to a location with no known router, a user can
reach `READY TO PLAY` through Direct Mode without entering an address or port.

### PRD-120: Discovery and multiple enclosures

Every enclosure must have a permanent random device ID, a user-editable display
name, and a unique local hostname. The identity must not be derived only from a
changeable IP address.

The Companion must use local service discovery and automatically reconnect to
a paired enclosure after normal address changes. If multiple enclosures are
found, it must show their display names, short IDs, status, and last connection
time rather than selecting one silently. A printed `.local` recovery hostname
or setup address must remain available when discovery fails.

**Acceptance:** two V3 enclosures can operate on the same residence network
without hostname, hotspot-name, pairing, or configuration collisions.

### PRD-130: Pairing, ownership, and trusted PCs

Pairing must require physical access to the enclosure or its owner card plus a
short-lived six-digit code. Pairing codes must expire, be single-use, and be
rate-limited. Each pairing must create unique credentials rather than sharing a
fleet-wide password.

The maintenance screen must list trusted PCs and allow the owner to rename or
revoke each one. Revocation must take effect immediately. A normal update or
network change must not invalidate trusted pairings.

The reset choices must be distinct:

- **Reset network:** remove residence Wi-Fi profiles but preserve calibration,
  pairings, and simulator preferences.
- **Remove this PC:** revoke only the selected pairing.
- **Reset simulator settings:** preserve networking, pairing, and calibration.
- **Prepare for new owner:** remove networks, pairings, owner-created backups,
  and personal settings while preserving the installed software.
- **Full factory reset:** restore documented defaults after two explicit
  confirmations; calibration handling must be stated before confirmation.

**Acceptance:** a former owner's PC cannot reconnect after ownership transfer,
and a network reset cannot erase camera calibration.

### PRD-200: Startup self-test and readiness

On every boot, the Pi service must run a self-test before reporting ready. At a
minimum, it must evaluate:

- Required Raspberry Pi model, operating-system architecture, and hardware
  profile.
- Required cameras and stable camera identities.
- Presence and validity of the selected calibration data.
- PiTrac process and local web-service health.
- Pi bridge and Companion protocol compatibility.
- Selected network mode and two-way Companion communication.
- Selected simulator socket, protocol handshake, and armed/ready behavior.
- Available microSD-card space and configuration-database integrity.
- CPU temperature, throttling, and reported under-voltage conditions.
- System clock sanity before TLS-dependent downloads or update checks.

Checks that are not supported by the installed hardware must be marked `NOT
AVAILABLE`, not falsely reported as passed. The self-test must not energize or
exercise hardware in an unsafe manner.

**Acceptance:** disconnecting a camera, stopping PiTrac, filling the disk below
the defined safe threshold, or restarting the simulator removes
`READY TO PLAY` and identifies the failed check.

### PRD-210: Maintenance screen

One beginner-facing maintenance screen must provide:

- Enclosure name and device ID.
- PiTrac, Pi bridge, Companion, protocol, and operating-system versions.
- Hardware revision, camera presence, and calibration status.
- Residence/Direct Mode status and selected simulator.
- CPU temperature, throttling or under-voltage warnings, and free storage.
- Last successful boot, connection, test shot, update, and backup.
- Restart PiTrac, restart the Pi bridge, reboot, and safe-shutdown controls.
- Backup, restore, reset, pairing-management, update, and support-report actions.

Dangerous actions must explain what will be preserved and removed before the
user confirms them. Advanced addresses, ports, and logs must remain behind an
explicit advanced or support view.

**Acceptance:** the routine health and recovery actions in this PRD can be
completed without SSH or a terminal.

### PRD-220: Configuration, calibration backup, and restore

Application code, device configuration, secrets, and calibration data must be
stored separately. Configuration changes and schema migrations must be atomic
and versioned. An interrupted write must leave either the previous valid data
or the new valid data, never a partially written file.

The owner must be able to export a checksummed backup containing:

- Camera and launch-monitor calibration.
- Device display name and hardware profile.
- Simulator selection and non-secret preferences.
- Easy Connect configuration version.
- Optional network and pairing information only after a clear warning.

The default backup must exclude Wi-Fi passwords, private pairing keys, logs,
and personal identifiers. Restore must verify the backup, display its device
and schema versions, reject altered or incompatible data safely, and take an
automatic pre-restore backup.

**Acceptance:** a fresh compatible microSD installation can restore calibration
and non-secret settings from an exported backup, and a corrupt backup cannot
overwrite the working configuration.

### PRD-230: Power-loss and storage resilience

Users will sometimes remove mains power without using software shutdown. The
system must minimize microSD corruption and must never perform routine writes
continuously without need.

Required behavior:

- Use atomic configuration writes and a transactional or journaled data store.
- Rotate and size-limit logs.
- Stage updates outside the active installation.
- Preserve the last known-good application and configuration until the updated
  service passes its health check.
- Detect an incomplete update or migration at startup and roll back safely.
- Provide **Shut down safely** and a clear `SAFE TO UNPLUG` indication in the
  interface when the Pi has actually halted.
- Re-run integrity and readiness checks after an unexpected restart.

**Acceptance:** power-interruption tests during idle operation, configuration
save, network change, backup restore, and each update phase do not produce an
unbootable or permanently unreachable enclosure.

### PRD-240: Diagnostics and support report

The user must be able to create one timestamped support package without a
terminal. It should contain:

- Device and software versions.
- Hardware profile and camera-detection results.
- Recent bounded service logs and error codes.
- Self-test results, temperatures, throttling, free space, and service status.
- Network mode and connection state without saved passwords.
- Companion and simulator protocol state without pairing secrets.
- Recent update, migration, backup, and rollback results.

Before saving or sharing the package, the interface must explain what it
contains. Automatic redaction must remove Wi-Fi credentials, private keys,
pairing codes, authentication tokens, and unnecessary personal information.
Diagnostic collection must remain local unless the user deliberately exports
the file.

Every user-facing failure must have a stable error code that can be matched to
the guide and support package.

**Acceptance:** a support package can be shared without revealing the setup
password, residence Wi-Fi password, private pairing material, or simulator
credentials.

### PRD-300: Simulator connection and shot forwarding

The Companion must expose only GSPro and E6 in the normal first-release
selector. Simulator-specific address and port controls are advanced settings.
The complete path must distinguish:

1. PiTrac measurement service available.
2. Pi bridge connected to the Companion.
3. Companion connected to the selected simulator.
4. Simulator handshake or armed state accepted.
5. Test message acknowledged.
6. Live measured shot forwarded and accepted.

A test shot may appear in or affect an active simulator session. The interface
must warn the user and require confirmation before sending it; it must not call
the test harmless unless that behavior has been proven with the installed
simulator version.

The Companion must reconnect after either simulator restarts and must never
silently send a shot to the wrong simulator profile. Live shot messages should
be given a local sequence ID so duplicates and lost acknowledgements can be
diagnosed. Automatic retry must not create duplicate scored shots.

**Acceptance:** the real GSPro and E6 acceptance suites pass with test and
measured shots, return messages, simulator restarts, malformed messages, lost
connections, and duplicate-prevention checks.

### PRD-400: Shared releases and updates

All compatible enclosures must use the same versioned codebase and release
artifacts. Device-specific configuration must remain separate from application
files. Updates must be signed, compatibility-checked, staged, health-checked,
and automatically rolled back as specified in
[Planned software updates for multiple enclosures](#planned-software-updates-for-multiple-enclosures).

Normal updates must be optional and scheduled by the user rather than starting
immediately before play. A security release may be marked urgent, but the UI
must still explain the interruption. Failure to contact the update service must
not prevent local play.

**Acceptance:** one beta enclosure can install and roll back a release before
the identical artifact is promoted to stable; Direct Mode can update through
the Companion; and a signed USB bundle provides the final offline recovery
path.

### PRD-500: Security and privacy

- The Companion web UI must bind to loopback only.
- The setup portal must expose only the minimum provisioning functions before
  pairing.
- Pi services must run with the least operating-system privileges practical;
  the browser-facing process must not provide arbitrary root commands.
- State-changing browser requests require authentication and cross-site request
  protections.
- Pairing and login attempts must be rate-limited and recorded without logging
  secrets.
- Wi-Fi passwords, private keys, tokens, and pairing credentials must never
  appear in normal logs or support reports.
- Secrets must use operating-system-protected storage and restrictive file
  permissions. Encryption on the same microSD card must not be presented as
  protection against a determined person with physical access.
- Update signing private keys must not be stored on an enclosure or in the
  repository.
- Normal play, setup, and diagnostics must not require inbound internet access.
- Usage analytics, crash uploads, and remote diagnostics are off by default and
  require explicit, revocable consent if ever added.
- Security-relevant dependencies and supported operating-system versions must
  be tracked so obsolete installations receive a clear warning.
- Windows 10 compatibility must not be presented as a secure recommendation.
  Normal Windows 10 support ended October 14, 2025; a Windows 10 installation
  must be fully patched and enrolled in an applicable Extended Security Updates
  program to pass the supported-security check.

**Acceptance:** an unpaired device on the residence network cannot change
settings, retrieve secrets, install software, or forward simulator shots.

### PRD-510: Licensing and distribution

Before software is given or sold with an enclosure, the release must include:

- An explicit license for Easy Connect.
- Required copyright and third-party notices.
- The exact PiTrac version or commit included or supported.
- A documented way for recipients to obtain the corresponding source for any
  distributed GPL-covered binaries and modifications.
- Licenses for packaged Python and Windows dependencies.
- A machine-readable dependency inventory or software bill of materials.
- Release notes, checksums, signatures, and installation/recovery instructions.

Easy Connect should remain a separate service communicating with PiTrac through
documented interfaces unless a deliberate licensing review approves tighter
integration. This requirement is project planning, not legal advice; the final
distribution model needs a license-compliance review.

**Acceptance:** a recipient can identify every distributed software component,
its version and license, and where to obtain the source required by that
license.

### PRD-600: Beginner usability and documentation

- Normal screens use plain language and one primary action.
- No required workflow exposes an IP address, port, command, or log file.
- Status is expressed with text and icons, not color alone.
- Controls are usable with keyboard navigation and normal Windows display
  scaling.
- Progress indicators state what is happening and provide bounded timeouts.
- Errors explain what failed, what remains safe, and exactly what to do next.
- Destructive operations require confirmation and state what they remove.
- The illustrated guide covers first setup, moving residences, Direct Mode,
  GSPro, E6, backups, updates, safe shutdown, resets, and support reports.
- Advanced settings can be opened deliberately but cannot be changed
  accidentally during normal setup.

**Acceptance:** a first-time test participant can reach `READY TO PLAY`, recover
from one intentionally incorrect Wi-Fi password, create a backup, and export a
support report using only the guide and on-screen instructions.

### Provisional performance targets

These targets must be measured and adjusted on the assembled V3 hardware. They
are release targets, not claims about the current prototype.

- Display a meaningful startup or recovery state within 120 seconds of power-on.
- Discover a reachable paired enclosure within 30 seconds.
- Restore the setup hotspot within 120 seconds after failed residence Wi-Fi.
- Reflect a stopped or restarted simulator within 30 seconds.
- Keep the normal Companion interface responsive during diagnostics and update
  downloads.
- Retain enough free storage for one staged update, one rollback package, and
  bounded logs before allowing installation.

### Required validation matrix

The first release must be exercised against:

- Windows 11 with Microsoft Defender enabled, plus Windows 10 22H2 legacy
  compatibility on an applicable, fully patched Extended Security Updates
  installation.
- Residence Wi-Fi, Direct Mode, hidden SSID, incorrect password, isolated guest
  network, no-internet network, and unsupported captive portal.
- At least two enclosures on one network.
- GSPro and E6 separately, including restart and lost-connection behavior.
- First boot, normal reboot, unsafe power removal, and recovery boot.
- Power interruption during network change, configuration write, restore, and
  every update phase.
- Valid, corrupt, older-schema, newer-schema, and wrong-device backups.
- Stable, beta, Companion-mediated offline, and USB update paths.
- Revoked pairing, expired pairing code, repeated incorrect code, and ownership
  transfer.
- Low-storage, high-temperature, throttling, missing-camera, invalid-calibration,
  and stopped-service conditions.
- Keyboard navigation, display scaling, and instructions tested by someone who
  did not build the system.

## Project checkpoint — August 19, 2026

Easy Connect is installed and running on the assembled Raspberry Pi as a systemd
service. The enclosure itself is not finished — no cameras are attached yet — so
the self-test correctly refuses to report `READY TO PLAY` on the hardware.

- **Version:** 0.2.0
- **Tests:** 231 passing on macOS and on the Raspberry Pi (Python 3.13.5, arm64)
- **Dependencies:** none. Standard library only, so the Pi install needs no pip
  packages.

### Verified on the real Raspberry Pi

Recorded against the assembled Pi 5 running Debian 13 and NetworkManager 1.52.1.
See [docs/pi-baseline-audit.md](docs/pi-baseline-audit.md) for the read-only
audit taken before anything was installed.

- The service installs, enables, starts, and survives a restart.
- Re-running the installer upgrades in place and preserves the device ID, the
  setup password, and every saved setting.
- It listens on port 80 (setup page), 39877 (Companion), 39876/udp (discovery),
  and loopback 9210/9248 (the relay).
- It read the real network through the netplan-owned profile without modifying
  it, as required.
- A real Wi-Fi scan returned the surrounding networks with the right bands,
  signal bars, and password/open classification.
- NetworkManager checkpoints are created and destroyed through the real D-Bus
  API.
- The setup hotspot brings `wlan0` up in AP mode at **10.42.0.1** with DHCP
  serving — the exact address printed on the owner card — and restores the
  previous network cleanly afterwards.
- PiTrac's `user_settings.json` was created pointing at the relay, merged
  without disturbing other settings, and left owned by `pitracuser` so PiTrac's
  own dashboard can still write it.
- This Mac discovered the enclosure over the house network, paired with a
  six-digit code, and reached `READY TO PLAY`.
- **The full shot path works.** A shot injected at `127.0.0.1:9210` on the Pi —
  exactly where `pitrac_lm` sends — travelled through the relay, over the
  authenticated link, into a simulator on this Mac, and the simulator's reply
  came back to the Pi unchanged.

### Implemented

- Stable user-facing error catalogue: 39 codes, each with what failed, what is
  still safe, and what to do next.
- Power-loss-safe configuration storage: atomic writes, `fsync`, automatic
  backup, recovery from a damaged file, schema versions and migrations.
- Permanent device identity, per-device setup password, and the printed owner
  card.
- Wi-Fi provisioning with a journal, a NetworkManager checkpoint, and
  confirm-or-roll-back. A wrong password, a router that gives no address, an
  isolated guest network, or a power cut mid-change all leave the enclosure
  reachable and the previous settings intact.
- Direct Mode, hidden networks, the wireless-country gate, and honest refusal of
  WPA-Enterprise and WEP networks.
- Setup portal with cross-site and DNS-rebinding protections.
- Discovery by UDP beacon and by a static avahi mDNS service file.
- Pairing with an authenticated Diffie-Hellman exchange, six-digit codes that
  expire and work once, rate limiting, per-computer secrets, and immediate
  revocation.
- Authenticated, mutually-proved link with automatic reconnection and a
  version-mismatch message that names the side to update.
- Shot relay that carries GSPro and E6 traffic untouched in both directions,
  reports undelivered shots honestly in the simulator's own vocabulary, and
  never replays a missed shot.
- Startup self-test: 14 checks, distinguishing pass, fail, warning, and
  genuinely unavailable, with readiness recomputed rather than latched.
- Companion with discovery, pairing, the four-hop chain, the warned test shot,
  and enclosure maintenance actions.
- Separate reset paths: reset network, revoke one computer, prepare for a new
  owner — each stating what it keeps and what it removes.
- Safe shutdown with a clear safe-to-unplug message.
- Raspberry Pi installer, hardened systemd unit, and Windows executable build.
- An illustrated setup guide for owners and an operator guide for whoever builds
  and maintains enclosures, both tested against the code so a quoted timeout or
  error code cannot silently go stale.

### Hardened against

Found by tests that are now part of the suite, and each fixed:

- Unbounded memory growth from repeated pairing attempts, reachable without
  authentication.
- Shots accumulating forever when a computer connects but stops answering,
  leaving PiTrac waiting on a reply that never comes.
- Shot delivery reporting healthy when nothing was actually listening on the
  relay port, which would lose every shot silently.
- The enclosure claiming `SETUP REQUIRED` while a computer was paired and shots
  were flowing.
- The Companion under-reporting lost shots, because it could only count the ones
  that reached it.
- E6 shots counted four times over, once per message in the sequence.
- Invalid country codes, over-long network names, and control characters
  surfacing as internal errors instead of something a person can act on.

Verified stable and left alone: no thread, socket, or memory growth across 180
shots with simulator and link churn; the relay survives garbage, binary, huge,
and partial input; network names containing apostrophes, emoji, colons,
backslashes, and CJK survive scanning, joining, and display.

### Not implemented yet

- Signed update packages, staged installation, health checks, and automatic
  rollback.
- Stable and beta update channels; offline and USB update paths.
- Calibration backup, restore, and pre-restore snapshots.
- Redacted diagnostic support-package export.
- Camera and calibration verification against real cameras — none are attached
  yet, so those checks have only been exercised in their failing state.
- Testing with real GSPro and real E6 Connect.
- Testing on Windows 10 and Windows 11, and the code-signed installer.
- Two enclosures on one network.
- Keyboard-navigation, display-scaling, and beginner usability testing.
- The illustrated beginner guide.
- Easy Connect licence, third-party notices, and software bill of materials.

## Resume point

The enclosure hardware is the gate on most of what remains.

1. Finish the enclosure and attach both cameras.
2. Re-run the self-test; the camera and calibration checks should turn green.
3. Run PiTrac's calibration wizard, then confirm the calibration check passes.
4. Install the Companion on the Windows PC and pair it there.
5. Validate against real GSPro, then real E6 Connect, including restarting each
   simulator mid-session.
6. Hit real balls and confirm measured shots score correctly.
7. Move the enclosure to a second network and repeat setup from the hotspot.
8. Add calibration backup and restore, then the support-package export.
9. Add signed updates with staged installation and rollback.

The first commands to run when development resumes:

```bash
python3 -m pytest -q
PYTHONPATH=src python3 -m pitrac_easy_connect.demo gspro
```

## Planned software updates for multiple enclosures

Every enclosure should run the same versioned Easy Connect release. Do not
create a separate codebase, branch, or manually edited microSD card for each
unit. Build the software once, test it once, and distribute the same release to
all compatible enclosures.

Code and device-specific configuration must remain separate. An update may
replace application files, but it must preserve each enclosure's:

- Device ID and display name.
- Saved Wi-Fi networks.
- Pairing credentials and trusted PCs.
- Camera and launch-monitor calibration.
- Hardware revision.
- Simulator preferences.
- Selected update channel.

The initial fleet should use one `v3` hardware profile. Future hardware
differences should be represented by documented hardware profiles and
configuration migrations instead of forks of the software.

### Release design

A numbered release such as `v1.2.0` should be created from one Git tag. The
automated release process should run the tests and produce:

- A Raspberry Pi OS ARM64 package.
- A signed Windows Companion installer.
- A release manifest containing versions and compatibility requirements.
- Package hashes and signatures so devices can reject altered downloads.

Release signing credentials must remain in the release system. Enclosures
should receive only the public verification key, never the private signing key.
Upstream PiTrac versions must be pinned and tested with Easy Connect instead of
being updated independently without a compatibility check.

### Update behavior

The default user experience should be an update notification and a single
**Install update** action. Avoid silently starting a normal update immediately
before a golf session.

For each update, the enclosure should:

1. Read the central release manifest.
2. Confirm that the release supports its hardware, PiTrac installation, and
   Windows Companion version.
3. Download the package into a staging area.
4. Verify the package signature and hash before installation.
5. Back up the current application and configuration database.
6. Install the new version and restart the Easy Connect service.
7. Run a local health check.
8. Mark the release successful or automatically restore the previous version.

Use two release channels:

- `beta`: install on one test enclosure first.
- `stable`: publish the exact tested package to the remaining enclosures.

The devices may briefly run different versions during a staged rollout, but all
enclosures on the stable channel should converge on the same release.

### Offline update path

An enclosure may be operating in Direct Mode without internet access. In that
case, the Windows Companion should download the signed Raspberry Pi package,
connect to the paired enclosure over the local PiTrac Wi-Fi signal, and transfer
the package to the same verified installer. A signed USB update bundle should
be retained as the recovery option when neither device has a usable network
connection.

### Compatibility and fleet status

The Pi service and Windows Companion must report their software and protocol
versions during pairing. The release manifest should specify minimum compatible
Pi service, Companion, PiTrac, operating-system, and hardware versions. When the
versions are incompatible, the interface should identify exactly which side
must be updated rather than failing with a generic connection error.

Each enclosure should expose its device ID, installed version, update channel,
last update result, and basic service health. This is sufficient for a small
fleet; a cloud fleet-management service is not required for the first release.
Do not collect usage or diagnostic telemetry without an explicit user choice.

### Implementation order

1. Add a single software version source and display it in the Companion and Pi
   service.
2. Define the persistent configuration schema and tested migrations.
3. Define the signed release-manifest format and compatibility rules.
4. Build the Raspberry Pi package and install it as a separate system service.
5. Implement staged installation, health checking, and automatic rollback.
6. Add **Check for updates** and **Install update** to the beginner interface.
7. Test one enclosure on the beta channel before enabling stable distribution.
8. Add Companion-mediated offline updates and the signed USB recovery bundle.
9. Finish and code-sign the Windows installer and updater.

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
- Local service discovery may be blocked or unreliable on some networks. A
  printed hostname or setup address must remain as the fallback.
- Captive-portal and WPA-Enterprise networks are outside the normal first-release
  path and must fail with a clear Direct Mode recommendation.
- A simulator test shot may appear in or affect an active session. The user must
  be warned until harmless behavior is proven for each supported version.
- Users may remove mains power without software shutdown. Every persistent write
  and update phase must be designed and tested for interruption.
- Software encryption on the same removable microSD card does not fully protect
  secrets from a person with physical possession of the card.
- PiTrac's calibration locations, camera identity behavior, and service
  interfaces must be audited on the assembled installation before integration.
- Distributing PiTrac or modifications requires a documented GPL compliance
  path. Easy Connect also needs its own explicit license before distribution.
- Windows 10 reached normal end of support on October 14, 2025. Compatibility
  testing does not make an unpatched Windows 10 PC a supported or secure
  deployment.
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
11. See which hardware, service, network, or simulator check failed without
    opening a terminal.
12. Export and restore calibration and non-secret configuration safely.
13. Revoke a paired PC, reset networking, and prepare the enclosure for a new
    owner without erasing unrelated settings.
14. Create a redacted support report that contains no passwords or private keys.
15. Safely shut down and receive a clear indication that power can be removed.
16. Recover from interrupted configuration writes, network changes, restores,
    and updates without reflashing the microSD card.
17. Install a signed stable update online, through the Companion, or from the
    documented USB recovery path.
18. Operate two enclosures on one network without discovery or identity
    collisions.
19. Complete the normal workflow using keyboard navigation and normal Windows
    display scaling.
20. Identify the installed software versions, licenses, and corresponding-source
    location for distributed GPL-covered components.

Completion also requires every item in the required validation matrix to have a
recorded result, every release-blocking failure to be resolved, and the beginner
guide to be tested by someone who did not build or program the enclosure.

## Implementation references

- [PiTrac upstream repository](https://github.com/PiTracLM/PiTrac)
- [Raspberry Pi networking documentation](https://www.raspberrypi.com/documentation/configuration/cloud.html)
- [Raspberry Pi local hostname and mDNS documentation](https://www.raspberrypi.com/documentation/computers/remote-access.html)
- [NetworkManager checkpoint and rollback API](https://networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.html)
- [Debian APT package-authentication documentation](https://manpages.debian.org/testing/apt/apt-secure.8.en.html)
- [Microsoft Windows application code-signing guidance](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options)
- [Microsoft Windows 10 lifecycle and ESU information](https://learn.microsoft.com/en-us/windows/whats-new/extended-security-updates)
- [GNU GPL version 2](https://www.gnu.org/licenses/gpl-2.0.html)
- [GNU GPL distribution FAQ](https://www.gnu.org/licenses/gpl-faq.html.en)
