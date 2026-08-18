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
