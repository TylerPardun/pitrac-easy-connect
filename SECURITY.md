# Security

## Reporting something

Open a [private security advisory](https://github.com/TylerPardun/pitrac-easy-connect/security/advisories/new),
or email the address on the maintainer's GitHub profile. Please do not open a
public issue for a vulnerability.

This is a hobby project maintained by one person, so an acknowledgement may
take a few days. It will not be ignored.

## What this software assumes

**The trust boundary is your home network, before an enclosure is paired.**
Anything on the same Wi-Fi can reach the enclosure's setup page and drive
onboarding — join a network, set the country, open a pairing window, install
models, restart the measurement service. The guards in place on every
state-changing request — a required custom header, an `Origin` check and a
`Host` check — stop a hostile *web page* in a browser from driving the
enclosure. They do not stop a hostile *device* already on the network. That
is a deliberate trade for an appliance with no keyboard and no screen, and it
is stated here so nobody has to infer it.

**After pairing, the same routes need real owner proof, not just Wi-Fi
presence.** Changing the saved network, removing a trusted computer,
factory-resetting for a new owner, shutting down, rebooting, or restoring a
backup all require one of: being physically connected to the enclosure's own
setup hotspot, holding a short-lived owner token the paired computer obtained
over its own authenticated link, or typing the password printed on the
physical owner card. A device that is merely on the same residence Wi-Fi,
with none of those, is refused (`pi/portal.py`'s `_authorize_sensitive`,
`ROUTE_AUTHORIZATION`).

An owner token is requested over the paired computer's own companion link,
not through the portal, so that link's own protection is what closes this
path rather than reopening it. Since protocol version 2, every
command/commandResult/shot/shotResult/enclosureStatus/simulatorStatus/
simulatorMessage frame on an authenticated link carries a monotonic sequence
number and an HMAC tag under a session key derived from the pairing secret
and that connection's fresh handshake challenge (`common/link.py`'s
`SecureFrameStream`, `session_keys`). Somebody positioned to inject into an
*already-established* link connection cannot forge an `issueOwnerToken` or
`prepareForNewOwner` command that way any more: they do not hold the session
key, so an injected frame fails its tag check and the connection is torn
down rather than obeyed. What that does not do is make the link
confidential — see "The link is authenticated and integrity-protected but
not encrypted" below for what an eavesdropper can still read.

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
| **The link is authenticated and integrity-protected but not encrypted** | Both ends prove they hold the pairing secret when they connect. Command, shot, and status frames after that carry a sequence number and an HMAC tag under a key derived from the secret and that connection's fresh challenge (`common/link.py`), so injecting, replaying, reordering, or tampering with one of those frames is refused and tears the connection down; a captured tag from one session is also useless in the next, because a new challenge means new keys. What this does not do is hide the content: frames are still plain JSON on the wire, so anyone who can observe the traffic can read shot data, commands, and status — confidentiality, not just authenticity, would need actual encryption, which this does not add |
| **Platform code-signing certificates are optional and their absence causes first-launch warnings** | The workflow signs and notarizes macOS with a Developer ID Application certificate, and signs Windows with an Authenticode certificate, whenever `packaging/write-signing-status.py` records that the required secrets were present and every verification step passed. A complete, tested release may still be final without those certificates; `packaging/release-signing-gate.py` puts the exact signing state in its notes, and the download instructions state how to pass Gatekeeper or SmartScreen rather than pretending the warnings do not exist. A missing platform status report still forces a pre-release because CI then cannot vouch for what shipped. This is separate from release-manifest signing: every release also publishes a manifest -- exact assets, sizes, digests, supported platforms, and compatible versions -- signed with an Ed25519 key held only in the release environment's secrets, and both the desktop app and the enclosure verify that signature before trusting anything it says, including the digest a download is checked against. A checksum served by the same API as the file it describes proves the bytes arrived intact, not that the project produced them, which is the gap that signature closes. Releases are also attested at build time through Sigstore, recording which workflow and commit produced each file. If both a signing key and the release account were compromised together, an attacker could publish a release that verifies; see `packaging/make-signing-key.py` and the rotation and revocation notes below for what limits that |
| **Manifest signing key rotation and revocation** | The private key lives only in the release environment's `PITRAC_RELEASE_SIGNING_KEY` secret, generated by `packaging/make-signing-key.py`. To rotate: generate a new key, add its public half to `_PINNED_KEYS` in `common/release_manifest.py` *alongside* the old one, ship a release signed with the new key once both are pinned, then remove the old key only after every version still receiving updates has that release installed. To revoke a compromised key immediately: remove it from `_PINNED_KEYS` and ship a release; every application refuses to verify anything signed only with the removed key, including a genuine-looking release an attacker holding the compromised key tries to publish, and refuses cleanly rather than falling back to the unsigned digest check, because that fallback is pinned to versions before signing existed |
| **Trained models are fetched from a mutable branch** | Their contents are recorded after download but not compared against a known-good digest |
| **No at-rest encryption** | Anyone holding the memory card holds the secrets on it. Physical access already means everything on a device like this, but it is worth being explicit |

## Supported versions

Only the latest release. This project is too small to backport.
