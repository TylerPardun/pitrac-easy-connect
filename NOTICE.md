# Licenses and notices

## PiTrac Easy-Connect

PiTrac Easy-Connect is licensed under the [MIT License](LICENSE).

Easy-Connect is designed and distributed as a separate program from PiTrac. It
runs in its own process, includes no PiTrac source code, and communicates with
PiTrac through TCP sockets and a JSON settings file. MIT is compatible with GNU
GPL version 2 if code is later contributed upstream or the programs are combined
into a larger GPL-covered work.

MIT was chosen instead of Apache-2.0 because Apache-2.0 is not compatible with
GPL-2.0-only. MIT preserves the option to contribute Easy-Connect code to
PiTrac without adding that incompatibility.

## What each build contains

### Raspberry Pi service, portable app, and source

The Raspberry Pi service and source distribution use only the Python standard
library and install no third-party Python packages. The portable `.pyz` contains
only Easy-Connect source and runs with the user's existing Python installation.

### Native macOS and Windows apps

The native apps bundle Easy-Connect, a CPython interpreter, the PyInstaller
bootloader, pywebview, and the platform-specific libraries needed to create the
window. Each component remains licensed by its respective author.

| Component | License | Purpose |
|---|---|---|
| [CPython](https://www.python.org/) | PSF-2.0 | Bundled Python interpreter and standard library |
| [PyInstaller](https://pyinstaller.org/) bootloader | GPL-2.0-or-later with the PyInstaller bootloader exception | Starts the packaged application; the exception permits distributing the application under MIT |
| [pywebview](https://pywebview.flowrl.com/) | BSD-3-Clause | Creates the native application window |
| [PyObjC](https://pyobjc.readthedocs.io/) (macOS) | MIT | Connects pywebview to macOS frameworks and WKWebView |
| [pythonnet](https://pythonnet.github.io/) and [clr-loader](https://github.com/pythonnet/clr-loader) (Windows) | MIT | Connect pywebview to .NET and WebView2 |
| [proxy-tools](https://pypi.org/project/proxy-tools/) | MIT | Required by pywebview |
| [typing-extensions](https://pypi.org/project/typing-extensions/) | PSF-2.0 | Required by pywebview |
| OpenSSL (`libssl` and `libcrypto`) | Apache-2.0 | HTTPS support used by the bundled Python runtime |
| zlib | Zlib | Compression support used by the bundled Python runtime |
| bzip2 | bzip2-1.0.6 | Compression support used by the bundled Python runtime |
| xz (`liblzma`) | 0BSD | Compression support used by the bundled Python runtime |
| Expat (`libexpat`) | MIT | XML support used by the bundled Python runtime |
| libffi | MIT | Foreign-function support used by the bundled Python runtime |

The browser engines are not bundled. The app uses WKWebView on macOS and
WebView2 on Windows, both supplied by the operating system.

The full text of each licence above is in `THIRD-PARTY-LICENCES.txt`, which is
generated from the installed packages at build time and ships beside every
download and inside the app. This table is a summary and does not replace it.

`packaging/bundled-licences.py` checks PyInstaller's build manifest against
this list, so a component added to the build without being credited here fails
the build.

### Build and test tools

`pytest` and Pillow are used for testing and icon generation and are not bundled
with the application. PyInstaller itself is a build tool; only its bootloader is
included in the native apps under the exception described above.

## PiTrac

Easy-Connect requires [PiTrac](https://github.com/PiTracLM/PiTrac). PiTrac's
source code is licensed under GNU GPL version 2 and carries additional notices
for its third-party components.

Easy-Connect does not include or link against PiTrac code. It is installed as a
separate service and exchanges configuration and shot data with PiTrac. This
separation is intended to keep the two programs independently licensed, but the
legal classification of a combined product depends on how it is distributed
and should be reviewed before commercial sale.

Anyone distributing PiTrac in executable form, including on a memory card in an
assembled enclosure, must comply with PiTrac's GPL and third-party licenses. At
a minimum, the distributor should:

- preserve PiTrac's copyright notices and complete GPL text;
- record the exact PiTrac version or commit shipped;
- provide the complete corresponding source, including distributed changes and
  the scripts used to build and install it, or provide a qualifying written
  offer valid for at least three years; and
- preserve PiTrac's third-party license notices.

### Proprietary trained models

PiTrac's trained model files are not covered by the GPL. They are governed by
PiTracLM's separate
[Proprietary Model License Agreement](https://github.com/PiTracLM/PiTrac/blob/main/LICENSE.MODEL.md),
which currently prohibits redistribution, transfer, and commercial use without
PiTracLM's prior written permission.

Downloading the models directly for an owner after acceptance avoids bundling
them with Easy-Connect, but it does not by itself grant permission to use them
in a commercial product. Do not distribute working commercial units with the
models installed, or rely on first-run downloading as a commercial workaround,
without a written agreement from PiTracLM.

## Web fonts

The project website links to Instrument Serif, IBM Plex Sans, and IBM Plex Mono
through Google Fonts. The font files are not stored in this repository or
bundled with the application. They are available under the SIL Open Font
License through their respective authors.

## Commercial distribution

This notice is an engineering record, not legal advice. Before selling hardware
with PiTrac or Easy-Connect installed, have an attorney review the final device
image, corresponding-source process, third-party notices, and the written
commercial agreement with PiTracLM.
