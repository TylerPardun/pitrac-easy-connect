# PiTrac Easy-Connect

> **Not affiliated with PiTrac.** Easy-Connect is an independent project. It is
> not made, reviewed, endorsed, or supported by the PiTrac project or the people
> who maintain it, and it contains none of their code. The name indicates which
> hardware this software is for, nothing more. PiTrac itself can be found at
> [PiTracLM/PiTrac](https://github.com/PiTracLM/PiTrac)

**Connect your PiTrac enclosure to Wi-Fi and play on a built-in range, in OpenGolfSim, or in GSPro, from one desktop app.**

PiTrac Easy-Connect makes a PiTrac launch monitor easier to set up and use. It
includes a small program that runs on the Raspberry Pi inside the enclosure and
a native desktop app for macOS and Windows. The app always runs in its
own application window. It connects the enclosure to your home Wi-Fi, finds it
automatically, and puts each measured shot on its own range or into GSPro. It also
includes PiTrac's dashboard, shot history, and a practice range.

A five-step guide walks you through the first setup. If you move the enclosure to another home, you only need to choose the new Wi-Fi network. You do not need to reconfigure PiTrac.

- **Version:** 0.10.2
- **License:** [MIT](LICENSE)

![The practice range](media/range.png)

*Each shot follows a path based on its measured launch data, with the shot pattern for each club shown below.*

---


## What Easy-Connect Does

| Capability | Details |
|---|---|
| **Wi-Fi setup** | Scan for nearby networks and connect the enclosure from the app. Known networks appear first and reconnect automatically when the enclosure is turned on |
| **First-time connection** | Before the enclosure is connected to your home Wi-Fi, it creates a temporary network of its own. This lets you complete setup from a phone or laptop |
| **Connection recovery** | If a new Wi-Fi connection fails, the enclosure returns to the previous network within two and a half minutes. It can also recover if power is lost during the change |
| **Find and connect** | The app finds the enclosure automatically. One click links the app and enclosure, and other computers cannot connect unless the owner allows them |
| **Local Range** | A first-person range with nothing else to buy, open or sign in to. Set a target, and the club is chosen from its distance and how far you hit each one; change it with one key. Every shot shows carry, total, distance to the pin, speed, launch, direction and spin, and the session shows where they finished. Works on macOS and Windows |
| **OpenGolfSim** | Plays its range and courses on macOS and Windows. It is free and separate: choose **Developer API** as its launch monitor. Each shot shows whether it was played, and where the simulator says it went |
| **GSPro** | Sends each measured shot to GSPro, which runs on Windows. PiTrac is pointed at Easy-Connect once, when the enclosure is set up, and never again — so a new router, a new address, or a move to another house does not break shot delivery. A **Play mode** page shows which is selected, whether GSPro is answering, and the steps to get it listening |
| **Setup and system checks** | A five-step guide handles the first setup. The app also checks that the cameras, calibration, software, storage, and other essentials are ready, then explains anything that needs attention |
| **Shot history and practice range** | Every shot is saved with the club it was hit with, including shots played through GSPro. Averages build up with or without a simulator. Recent shot images PiTrac has saved are shown separately |
| **Dashboard and settings** | Includes PiTrac's dashboard and tools to back up, restore, update, or reset the enclosure for a new owner |

### What it looks like

| | |
|---|---|
| ![Ready to play](media/home.png) | ![Shot history by club](media/shots.png) |
| **One line and one next step.** The app tells you whether the system is ready and, if not, what needs attention. | **Every shot stays with its club**, along with ball speed, launch, spin, and shot pattern, so you can see what each club is actually doing. |

<img src="media/wifi.png" width="380" align="right" alt="Choosing a Wi-Fi network">

**Wi-Fi setup from the app.** If the enclosure has never joined a network, it
creates a temporary one so you can set it up from a phone or laptop. Known
networks appear first, a padlock marks those that require a password, and signal
strength is easy to see.

If the new network does not work, the enclosure restores the previous one within
two and a half minutes. It can also recover if power is lost during the change.
This prevents a failed network change from leaving you unable to reconnect.

<br clear="right">

---

## How It Works

PiTrac sends each measured shot to Easy-Connect inside the enclosure. The desktop app receives it over your home Wi-Fi and draws it on the range, or passes it to a simulator on the same computer.

```
PiTrac enclosure  →  Home Wi-Fi  →  Easy-Connect app  →  Local Range, OpenGolfSim or GSPro
```

The app finds the enclosure automatically, limits access to computers you have approved, and does not require a Windows firewall rule. Changing homes or Wi-Fi networks does not change PiTrac's setup.

---

## Install on the Raspberry Pi

PiTrac itself must already be installed and working — see
[PiTracLM/PiTrac](https://github.com/PiTracLM/PiTrac). If you are starting with
a blank memory card, install PiTrac first by following
[PiTracLM's own instructions](https://github.com/PiTracLM/PiTrac).
It covers the entire process, from flashing the card to running the launch
monitor.

This release was built and tested against one PiTrac revision. PiTrac has no
numbered releases, so check that revision out before building it:

```bash
git checkout 78f1de60fd21398f34d348f19f55e73029bc95f9
```

A newer PiTrac may work. Easy-Connect checks what PiTrac answers and says so
plainly when it cannot use it, but PiTrac's own update button can move it past
what has been tested.

Once PiTrac is working, copy the kit's source zip to the Pi, then on the Pi:

```bash
unzip "PiTrac Easy-Connect"*source.zip
cd PiTrac-Easy-Connect
sudo bash packaging/pi/install.sh
```

If `pitrac.local` does not answer, use the Pi's IP address instead — your
router lists it. If you have used this Pi before and `ssh` refuses to connect
after the card was rewritten, run `ssh-keygen -R pitrac.local` and try again.

The installer checks the enclosure, installs and starts Easy-Connect, prepares
PiTrac to send shots to the app, and prints the **owner card**.

> **Photograph the owner card.** Its setup Wi-Fi password is generated for that
> Pi alone, and it is the only way to reconnect if the enclosure cannot reach
> a network.

Re-run the same installer to upgrade. Your setup, saved Wi-Fi networks,
connected computers, and camera calibration are all preserved.

The service assigns each enclosure the stable hostname printed in its identity,
`pitrac-<device id>.local`, and publishes `_pitrac._tcp` through Avahi. UDP
discovery remains the primary search path and keeps working when mDNS is
unavailable.

---

## Install the desktop app

Everything comes in one folder, the **kit**, made for a USB stick and for places
with no internet: the Mac and Windows installers, what the Raspberry Pi needs, a
blank owner card, and a short `READ ME FIRST.txt`.

| Computer | File |
|---|---|
| Mac | `PiTrac Easy-Connect <version> (Mac ...).dmg`. Drag the app into Applications |
| Windows 11 | `PiTrac Easy-Connect <version> (Windows).exe` |

Neither is signed with a paid certificate, so each system asks the first time:

| Computer | What to do |
|---|---|
| Mac | Open it once, then **System Settings → Privacy & Security → Open Anyway** |
| Windows | **More info**, then **Run anyway** |

Installing a later kit over the top keeps pairing, Wi-Fi, calibration, settings,
and shot history. Use the same kit for the Pi and for every computer.

If macOS cannot find PiTrac, open **System Settings → Privacy & Security →
Local Network** and allow PiTrac Easy-Connect, then search again.

Wi-Fi is set up in the app too. A new enclosure, or one somewhere new, makes a
Wi-Fi network of its own. Join it from your computer's Wi-Fi menu with the
password on the owner card, and the app asks which network to use. A phone can do
the same at `http://10.42.0.1` if there is no computer to hand.

Open the app, find the enclosure, choose how to play, and play. A simulator adds
two steps: opening it, and one shot to make sure. The guide does not appear again after
the first-time setup, but you can reopen it with **Advanced → Run setup again**.

---

## Build the installers

Each is built on the kind of computer it is for, because it bundles that
computer's Python. Nothing is uploaded, and no GitHub minutes are used.

**On a Mac**, with Python 3.10 to 3.13:

```bash
python3 packaging/make_installer.py
```

Python from [python.org](https://www.python.org/downloads/macos/) makes an app
that runs on older versions of macOS too. Homebrew's makes one only for the
version it was built on. The build says which it made.

**On Windows**, unpack the source and double-click **Build Windows Installer**. It
asks before installing Python or Inno Setup.

Either one installs what it built, opens it, uses it, and removes it again before
putting it in `dist/`. To run the app from source instead:

```bash
python3 -m pip install -e ".[desktop]" && pitrac-easy-connect
```

---

## Licensing

**Easy-Connect is licensed under the MIT License.** PiTrac itself is GPL-2.0 and belongs to [PiTracLM](https://github.com/PiTracLM/PiTrac).
PiTrac does the hard work, and it is not my project. Easy-Connect handles the setup and connectivity around it so the launch monitor is easier to install, move, and use.
