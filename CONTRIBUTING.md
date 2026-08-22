# Contributing

Thanks for looking. This is a small project with one maintainer, so the most
useful thing you can do is tell me what broke.

## Reporting a problem

Open an issue with:

- what you did, what happened, and what you expected instead
- the version, from **Advanced → Details** in the app
- your operating system, and whether the enclosure was on Wi-Fi or its own
  setup network
- any error code you saw. They look like `PT-NET-004`, and each one has a
  meaning rather than being a number

If the enclosure will not come back after a power cut, that is the failure this
project cares about most. Say so plainly and it will go to the front.

**Please do not report a security problem in a public issue.** See
[SECURITY.md](SECURITY.md).

## Changing something

- Open an issue first for anything larger than a fix. It may already be on the
  list, or deliberately out of scope.
- `python3 -m pytest -q` must pass. The suite runs without hardware, against a
  simulated Raspberry Pi.
- New behaviour needs a test. Failure paths especially: most of this codebase
  exists to handle things going wrong.
- The Python that ships has **no third-party dependencies** and must stay that
  way. It has to install on a Raspberry Pi with no pip packages. Build and test
  tooling is exempt.
- Comments should say *why*, not restate the code.

## What is deliberately out of scope

- Anything PiTrac itself does — shots, calibration, configuration, its
  dashboard. This project handles the setup and connection around it.
- Signing into GSPro or E6, or launching them. They are separate licensed
  products with their own accounts.
- Bundling PiTrac's trained models. They are proprietary and their licence is
  non-transferable. See [NOTICE.md](NOTICE.md).
