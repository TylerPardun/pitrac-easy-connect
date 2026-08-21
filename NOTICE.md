# Licences and notices

## PiTrac Easy-Connect

Licensed under the [MIT License](LICENSE).

**Why MIT.** Easy-Connect is a separate program from PiTrac. It runs in its own
process and communicates over TCP sockets and a JSON settings file, so it is not
a derivative work of PiTrac and can carry its own licence.

MIT was chosen over Apache-2.0 for one specific reason: **PiTrac is GPL-2.0-only,
and Apache-2.0 is not compatible with GPL-2.0.** If any part of Easy-Connect is
ever contributed upstream into PiTrac, MIT allows it and Apache-2.0 would not.
MIT keeps that door open at the cost of an explicit patent grant, which matters
little for a project of this shape.

This is not legal advice. Anyone selling hardware with GPL software installed
should get a short professional opinion.

## Dependencies

Easy-Connect has **no third-party dependencies**. It uses only the Python
standard library, which is why installing it on a Raspberry Pi needs no pip
packages at all.

The Companion window uses whichever Chromium-based browser is already on the
computer to draw itself; it does not bundle or redistribute one.

Development and packaging use `pytest` and `PyInstaller`, neither of which is
distributed as part of Easy-Connect.

## PiTrac

Easy-Connect requires [PiTrac](https://github.com/PiTracLM/PiTrac), which is
licensed under the **GNU General Public License, version 2**, and carries its own
third-party notices (ED_Lib, rpicam-apps, shedskin, and its detection model).

Easy-Connect does not include, modify, or link against PiTrac. It is installed
separately, from the PiTrac project.

**If you distribute PiTrac itself** — for example by selling an enclosure with a
memory card that has PiTrac installed — the GPL applies to that distribution and
you must:

- keep PiTrac's copyright notices and its licence text,
- record the exact PiTrac version or commit you shipped,
- give recipients the corresponding source, or a written offer valid for three
  years, and
- carry PiTrac's own third-party notices.

Shipping Easy-Connect and PiTrac together on one card or in one download is
"mere aggregation", which GPL-2.0 permits. Combining them into a single program
would not be, so Easy-Connect is deliberately kept as a separate service.

## Fonts

The illustrated setup guide references Bricolage Grotesque, Source Serif 4, and
JetBrains Mono from Google Fonts, all under the SIL Open Font License. They are
linked, not redistributed, and the guide falls back to system fonts without them.
