# PiTrac Easy Connect

A PC app for [PiTrac](https://github.com/PiTracLM/PiTrac). It gets the enclosure
onto your Wi-Fi, connects it to your computer, and puts PiTrac's own dashboard in
the same window — so there is no terminal, no SSH, no IP address, and no browser
tabs.

PiTrac already measures the ball and has a good dashboard. Easy Connect adds the
part that was missing: **getting the thing on the network and talking to your
PC.** It deliberately does not reimplement anything PiTrac already does.

- **Status:** working on real hardware, not yet released
- **Version:** 0.2.0 · **Tests:** 356, passing on macOS and on the Raspberry Pi
- **Dependencies:** none — Python standard library only
- **Licence:** [MIT](LICENSE) · see [NOTICE.md](NOTICE.md) for how this relates
  to PiTrac's GPL

---

## Try it

No hardware needed — a stand-in simulator, a simulated Raspberry Pi, and the real app:

```bash
PYTHONPATH=src python3 -m pitrac_easy_connect.demo gspro
```

Against your own enclosure, with a stand-in simulator:

```bash
PYTHONPATH=src python3 -m pitrac_easy_connect.tryit gspro
```

As the app window it will actually ship as:

```bash
PYTHONPATH=src python3 -m pitrac_easy_connect.companion.app --window
```

On a Mac, the `.command` files do the same by double-click.

## Install on the enclosure

```bash
sudo ./packaging/pi/install.sh
```

Checks the Pi, installs the service, starts it, and prints the owner card. Safe
to re-run to upgrade: identity, networks, pairings, and calibration are kept.

---

## How it works

`pitrac_lm` is a TCP client, so Easy Connect points it at `127.0.0.1` once, at
install time, and stands in for the simulator:

```text
pitrac_lm ──► Pi relay ══ paired link ══► the app ──► GSPro / E6 on your PC
              127.0.0.1:9210 / :9248      (Wi-Fi)     127.0.0.1:921 / :2483
```

Two consequences that shape everything else:

- **Moving house never touches PiTrac's configuration**, because the relay
  address is loopback and is correct everywhere.
- **The app dials out to the enclosure**, never the reverse, so Windows never
  needs a firewall rule and the PC's address can change freely.

More in [docs/architecture.md](docs/architecture.md).

---

## What is built

### Working, and verified on the real Pi

| | |
| --- | --- |
| Wi-Fi setup | Country, network list, hidden networks, Direct Mode |
| Never locked out | Journal, NetworkManager checkpoint, confirm-or-roll-back |
| Setup hotspot | AP mode at 10.42.0.1 with DHCP, restores afterwards |
| Discovery | UDP beacon and a static avahi mDNS record |
| Pairing | Six-digit code over an authenticated Diffie-Hellman exchange |
| Shot relay | GSPro and E6 carried untouched, both directions |
| Self-test | 14 checks; readiness recomputed, never latched |
| Backup | Checksummed, with identity as an opt-in for card replacement |
| App window | One window, three tabs, PiTrac's dashboard embedded |
| Software delivery | The enclosure hands out the PC app over its own signal |
| Shot history | Every shot kept with the club, and averages per club |
| Updates | Checks on launch, installs for source builds, points to the download otherwise |

### Proven end to end

A shot injected at `127.0.0.1:9210` on the Pi — exactly where `pitrac_lm` sends —
travelled through the relay, over the link across a real house network, into a
simulator on another machine, and the reply came back unchanged.

---

## What is left

### Next up

- [ ] **Windows and macOS builds.** A native window and a real signed installer,
      rather than the current application-mode window. Needs a Windows machine
      to build the `.exe`; see [docs/distribution.md](docs/distribution.md).
- [ ] **Shot images in the Shots tab.** PiTrac announces each shot's images
      over its WebSocket and serves them from `/api/images/{filename}`. The tab
      shows camera status and club history today; the images are the next piece.
      **Swing video is not possible** — PiTrac is a ball tracker using strobed
      stills and has no video or playback endpoint.
- [ ] **Public repo and download page.** GitHub Pages for the site, Releases for
      the download.

### Blocked on hardware

- [ ] Cameras attached, calibration completed, and the camera self-test passing
- [ ] Real GSPro and real E6, including restart behaviour
- [ ] Whether a test shot scores into an open round
- [ ] Windows 10 and 11, with Defender on
- [ ] Two enclosures on one network

### Later

- [ ] Update the enclosure from the app, not just the PC
- [ ] Signed update packages with staged installation and rollback
- [ ] Redacted support-report export
- [ ] Keyboard navigation and display-scaling testing
- [ ] Someone who did not build it completing setup from the guide alone
- [ ] **Virtual course rendering in the app.** A large piece of work and a real
      change in scope — worth treating as its own project once the above is done.

### Deliberately not doing

- **GSPro and E6 sign-in or launching.** They are separate licensed products
  with their own accounts. Easy Connect detects whether they are running and
  says what to do; it does not manage them.
- **Anything PiTrac already does.** Shots, calibration, configuration, logs and
  updates are PiTrac's, and the app embeds its dashboard rather than copying it.

---

## Guides

| | |
| --- | --- |
| [Setting up PiTrac](docs/beginner-guide.html) | Illustrated, printable, for whoever owns an enclosure ([plain text](docs/beginner-guide.md)) |
| [Operator guide](docs/operator-guide.md) | Installing on a new Pi 5, simulator PCs, upgrading, diagnosis |
| [Distribution](docs/distribution.md) | Getting the app onto a PC, what to build, what ships in the box |
| [Architecture](docs/architecture.md) | How the pieces fit and why |
| [Requirements](docs/requirements.md) | What a finished release has to do |
| [Test plan](docs/test-plan.md) | What is covered, and what is not yet |
| [Pi baseline audit](docs/pi-baseline-audit.md) | What the target Pi looks like, and the constraints that follow |
| [Risks](docs/risks.md) | Known constraints and open questions |
| [Definition of finished](docs/definition-of-finished.md) | The bar for a release |

## Tests

```bash
python3 -m pytest -q
```

Runs on macOS, Linux, Windows, and the Raspberry Pi itself. Every failure that
would otherwise strand a user — wrong password, no DHCP, an isolating guest
network, the power cut mid-change — is driven from a simulated Raspberry Pi
rather than by hand.

## Security

- The app binds to loopback only.
- The setup page has no route that runs a command and cannot read a Wi-Fi
  password back out. State-changing requests need a custom header, a matching
  `Origin`, and a recognised `Host`.
- **The pairing secret is never transmitted.** It is derived on both sides from
  an authenticated Diffie-Hellman exchange, and afterwards each side proves it
  holds the secret by answering a fresh challenge.
- Every paired computer gets its own secret; there is no fleet-wide password.
- The setup hotspot is never open and its password is unique per enclosure.

Known limitation: someone already on your network who guesses the six-digit code
within its five-minute life could pair. Five wrong attempts stop the enclosure
answering for ten minutes.
