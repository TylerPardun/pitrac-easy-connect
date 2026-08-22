# Security

## Reporting something

Open a [private security advisory](https://github.com/TylerPardun/pitrac-easy-connect/security/advisories/new),
or email the address on the maintainer's GitHub profile. Please do not open a
public issue for a vulnerability.

This is a hobby project maintained by one person, so an acknowledgement may
take a few days. It will not be ignored.

## What this software assumes

**The trust boundary is your home network.** Anything on the same Wi-Fi can
reach the enclosure's setup page. The guards in place — a required custom
header, an `Origin` check and a `Host` check — stop a hostile *web page* in a
browser from driving the enclosure. They do not stop a hostile *device* already
on the network. That is a deliberate trade for an appliance with no keyboard
and no screen, and it is stated here so nobody has to infer it.

Concretely, on a network where you do not trust every device, assume someone
could change the enclosure's Wi-Fi, read its settings, and trigger a factory
reset.

## What is protected

- The app binds to loopback only and is not reachable from the network.
- Each paired computer gets its own secret. The enclosure generates it and
  sends it masked with a key both ends derive from an ephemeral Diffie–Hellman
  exchange, so a listener recording the traffic learns nothing usable. The
  secret is transmitted, but never in the clear — and it is never sent again
  afterwards, because each side then proves it holds the secret by answering a
  fresh challenge.
- An attacker positioned to interfere *during* pairing is inside the trust
  boundary described above, and this does not defend against one.
- Pairing is closed by default: an enclosure accepts the first computer, then
  refuses others until its owner opens a short window.
- The setup hotspot is never open and its password is unique per enclosure.
- Secrets are stored root-owned and mode `0600`.
- No route on either page runs a shell command, and no Wi-Fi password can be
  read back out.

## Known limitations

These are real and unfixed. They are listed rather than hidden.

| | |
|---|---|
| **The link is authenticated but not encrypted** | Both ends prove they hold the pairing secret when they connect. After that, frames are plain JSON over TCP with no per-message integrity. Somebody positioned to inject into an established connection could send commands, including a factory reset |
| **Update downloads are not signed** | A release archive is checked for size and structure, not authenticity. Anyone able to serve a different release, or to intercept the download, could replace the software on an enclosure |
| **Trained models are fetched from a mutable branch** | Their contents are recorded after download but not compared against a known-good digest |
| **No at-rest encryption** | Anyone holding the memory card holds the secrets on it. Physical access already means everything on a device like this, but it is worth being explicit |

## Supported versions

Only the latest release. This project is too small to backport.
