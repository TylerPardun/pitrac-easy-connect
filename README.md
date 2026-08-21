# PiTrac Easy-Connect

**Wi-Fi provisioning, pairing, and shot relay for the PiTrac golf launch monitor — no terminal, no SSH, and no IP addresses.**

PiTrac Easy-Connect is a two-part system: a background service on the Raspberry Pi inside the enclosure, and a desktop app for macOS and Windows. The service puts the enclosure on your home Wi-Fi, announces itself on the network, and forwards every measured shot; the app finds the enclosure by itself, pairs with it in one click, relays the shots into GSPro or E6 Connect, and shows PiTrac's own dashboard in a tab. Setup is a five-step wizard, and moving the enclosure to a different residence means picking a new network off a list — nothing about PiTrac's own configuration changes.

- **Status:** private while it settles; build from source below
- **Version:** 0.2.0, running on real hardware
- **Dependencies:** none — Python standard library only
- **Licence:** [MIT](LICENSE)

---

## What Easy-Connect Does

| Capability | Details |
|---|---|
| **Wi-Fi setup** | Country selection, live network scan, hidden networks, and a padlock beside anything needing a password; networks the Pi already knows are grouped first |
| **Setup hotspot** | An enclosure that has never been on a network broadcasts its own at `10.42.0.1` with DHCP, so it can be configured from a phone or laptop, and restores the previous state afterwards |
| **Cannot be locked out** | Every network change writes a journal and takes a NetworkManager checkpoint first; if the new network does not work within 150 seconds the old one is restored automatically, and pulling the power mid-change is survivable |
| **Discovery** | UDP beacon plus a static Avahi mDNS record, so the app locates the enclosure without being told an address |
| **Pairing** | One click. An ephemeral Diffie-Hellman exchange gives each computer its own secret, derived at both ends rather than transmitted; the enclosure accepts the first computer and refuses the rest until its owner opens a window |
| **Shot relay** | GSPro and E6 Connect protocols passed through byte-for-byte in both directions; shots are never retried, since a duplicate scored shot is worse than a missing one |
| **Guided first run** | Five steps, one action per screen, with the simulator choice and a "cannot find it" path built in; it does not appear again once setup is finished |
| **Self-test** | Fifteen checks across cameras, calibration, detection models, temperature, power supply, storage, clock, and services; recomputed every time and never latched, so readiness is never claimed without proof |
| **Shot history** | Every shot retained with its club, with average, best, worst, and spread per club, alongside PiTrac's captured still images |
| **Embedded dashboard** | PiTrac's own web dashboard in a tab, rather than a reimplementation of it |
| **Backup and restore** | Checksummed archive of calibration and settings, with identity as an explicit opt-in for memory-card replacement |
| **Ownership transfer** | Removes saved networks, paired computers, preferences, and the proprietary trained models along with the source clone and its git history |
| **Updates** | Checked on launch; installed in place for source builds, pointed at the download otherwise |
| **Native app** | A real window with its own Dock or taskbar icon and its own menu bar, not a browser in disguise |

---

## How It Works

`pitrac_lm` connects outward to a simulator rather than listening for one. Easy-Connect uses that: at install time it points PiTrac at `127.0.0.1` on the Pi itself and stands in for the simulator.

```
pitrac_lm  →  Pi relay  ══ paired link ══>  Desktop app  →  GSPro / E6 Connect
              127.0.0.1:9210 / :9248         (Wi-Fi)         127.0.0.1:921 / :2483
```

1. **The relay address is loopback**, so it is correct in every house. Moving the enclosure never touches PiTrac's configuration.
2. **The app dials out to the enclosure**, never the reverse. Windows needs no firewall rule, and the PC's IP address can change freely.
3. **The link is authenticated per computer.** Each side proves it holds the shared secret by answering a fresh challenge, so a listener on the network learns nothing reusable.

---

## Setup

Two pieces, installed in this order. PiTrac itself must already be installed and working — see [PiTracLM/PiTrac](https://github.com/PiTracLM/PiTrac).

### 1. Install the service on the Raspberry Pi

Copy this repository to the Pi and run:

```bash
sudo ./packaging/pi/install.sh
```

The installer checks the hardware, installs and starts the service, points PiTrac's shot output at the relay, and prints the **owner card**.

> **Photograph the owner card.** The setup Wi-Fi password on it is generated for that Pi alone and is the only way back in if the enclosure cannot reach a network.

Re-run the same installer to upgrade. Identity, saved networks, paired computers, and camera calibration are preserved.

### 2. Build the app for your computer

While this repository is private there are no published downloads, so the app
is built from source. That is one command:

Requires Python 3.9+. PyInstaller bundles the interpreter of the machine it runs on, so a Windows executable must be built on Windows and a macOS app on macOS. There is no cross-compiling.

```bash
git clone https://github.com/TylerPardun/pitrac-easy-connect
cd pitrac-easy-connect
./packaging/build-app.sh
```

The result is written to `dist/` — `PiTrac Easy-Connect.app` on macOS,
`PiTrac Easy-Connect.exe` on Windows. PyInstaller and pywebview are installed
automatically if missing; both are build-time only and are not runtime
dependencies.

Neither native build is code signed, so both operating systems warn on first
launch: on macOS right-click the app and choose **Open** rather than
double-clicking; on Windows choose **More info**, then **Run anyway**.

| Flag | Description |
|---|---|
| *(none)* | Native app — `.app` on macOS, `.exe` on Windows |
| `--pyz` | Portable single file, runs anywhere Python 3.9+ is installed |
| `--all` | Both |

### 3. First run

Open the app and follow the five steps: find the enclosure, choose your simulator, open it, send one test shot, play. The wizard does not return after that; **Advanced → Run setup again** brings it back if needed.

---

## Development

### Running Without Hardware

A simulated Raspberry Pi, a stand-in simulator, and the real app, all on one machine:

```bash
PYTHONPATH=src python3 -m pitrac_easy_connect.demo gspro
```

Against a real enclosure with a stand-in simulator, to exercise the shot path without opening GSPro:

```bash
PYTHONPATH=src python3 -m pitrac_easy_connect.tryit gspro
```

### Tests

```bash
python3 -m pytest -q
```

---

## Licensing

**Easy-Connect is MIT.** PiTrac itself is GPL-2.0 and belongs to [PiTracLM](https://github.com/PiTracLM/PiTrac).
PiTrac is the hard part, and it is not my work. Easy-Connect only handles the setup and connectivity around it, making it an easier user experience.
