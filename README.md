# PiTrac Easy-Connect

**Wi-Fi provisioning, pairing, and shot relay for the PiTrac golf launch monitor — no terminal, no SSH, and no IP addresses.**

PiTrac Easy-Connect is a two-part system: a background service on the Raspberry Pi inside the enclosure, and a desktop app for macOS and Windows. The service puts the enclosure on your home Wi-Fi, announces itself on the network, and forwards every measured shot; the app finds the enclosure by itself, pairs with it in one click, relays the shots into GSPro or E6 Connect, and shows PiTrac's own dashboard in a tab. Setup is a five-step wizard, and moving the enclosure to a different residence means picking a new network off a list — nothing about PiTrac's own configuration changes.

- **Download:** <https://tylerpardun.github.io/pitrac-easy-connect/>
- **Version:** 0.2.0
- **Dependencies:** none — Python standard library only
- **Licence:** [MIT](LICENSE)

![The practice range](media/range.png)

*Every shot flown from its measured launch numbers, with per-club dispersion underneath.*

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
| **Practice range** | A 3D driving range in the app. Every shot is flown from the measured launch numbers and drawn as a tracer, with carry, total, apex and offline, and per-club dispersion. No GSPro, no E6, no account, no internet |
| **Embedded dashboard** | PiTrac's own web dashboard in a tab, rather than a reimplementation of it |
| **Backup and restore** | Checksummed archive of calibration and settings, with identity as an explicit opt-in for memory-card replacement |
| **Ownership transfer** | Removes saved networks, paired computers, preferences, and the proprietary trained models along with the source clone and its git history |
| **Updates** | Checked on launch; installed in place for source builds, pointed at the download otherwise |
| **Native app** | A real window with its own Dock or taskbar icon and its own menu bar, not a browser in disguise |

### What it looks like

| | |
|---|---|
| ![Ready to play](media/home.png) | ![Shot history by club](media/shots.png) |
| **One line, and one thing to do about it.** The app says whether you can play and, if not, what is stopping you. | **Every shot kept with its club**, with ball speed, spread, launch and spin, so you can see what each club is actually doing. |

<img src="media/wifi.png" width="380" align="right" alt="Choosing a Wi-Fi network">

**Wi-Fi without a terminal.** The enclosure makes its own network when it has
never been on one, so it can be set up from a phone or a laptop. Networks it
already knows are grouped first, anything needing a password has a padlock, and
signal strength is a glance rather than a number.

If the new network does not work, the enclosure puts the old one back on its own
within two and a half minutes. Pulling the power halfway through is survivable
too. Getting locked out of a machine you cannot SSH into is the one failure that
has no recovery, so it is the one thing built most carefully.

<br clear="right">

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

## Install on the Raspberry Pi

PiTrac itself must already be installed and working — see
[PiTracLM/PiTrac](https://github.com/PiTracLM/PiTrac). Then copy this repository
to the Pi and run:

```bash
sudo ./packaging/pi/install.sh
```

The installer checks the hardware, installs and starts the service, points
PiTrac's shot output at the relay, and prints the **owner card**.

> **Photograph the owner card.** The setup Wi-Fi password on it is generated for
> that Pi alone and is the only way back in if the enclosure cannot reach a
> network.

Re-run the same installer to upgrade. Identity, saved networks, paired
computers, and camera calibration are all preserved.

Starting from a blank memory card? `docs/new-pi-setup.md` covers flashing
through to a working launch monitor.

---

## Install the app on macOS or Windows

Download the build for your computer from
<https://tylerpardun.github.io/pitrac-easy-connect/>:

| Platform | File |
|---|---|
| macOS 11+, Apple silicon or Intel | `PiTrac-Easy-Connect-macos.zip` |
| Windows 10 and 11 | `PiTrac.Easy-Connect.exe` |
| Linux, or any OS with Python 3.9+ | `PiTrac-Easy-Connect-0.2.0.pyz` |

Neither native build is code signed yet, so both operating systems warn the
first time:

| Platform | What to do |
|---|---|
| macOS | Right-click the app and choose **Open** rather than double-clicking |
| Windows | Choose **More info**, then **Run anyway** |

Open it and follow the five steps: find the enclosure, choose your simulator,
open it, send one test shot, play. The wizard does not return after that;
**Advanced → Run setup again** brings it back if needed.

---

## Or build the app from source

Requires Python 3.9 or newer. PyInstaller bundles the interpreter of the
machine it runs on, so a Windows executable must be built on Windows and a
macOS app on macOS. There is no cross-compiling.

```bash
git clone https://github.com/TylerPardun/pitrac-easy-connect
cd pitrac-easy-connect
./packaging/build-app.sh
```

The result is written to `dist/` — `PiTrac Easy-Connect.app` on macOS,
`PiTrac Easy-Connect.exe` on Windows. PyInstaller and pywebview are installed
automatically if missing; both are build-time only and are not runtime
dependencies.

| Flag | Description |
|---|---|
| *(none)* | Native app — `.app` on macOS, `.exe` on Windows |
| `--pyz` | Portable single file, runs anywhere Python 3.9+ is installed |
| `--all` | Both |

---

## Licensing

**Easy-Connect is MIT.** PiTrac itself is GPL-2.0 and belongs to [PiTracLM](https://github.com/PiTracLM/PiTrac).
PiTrac is the hard part, and it is not my work. Easy-Connect only handles the setup and connectivity around it, making it an easier user experience.
