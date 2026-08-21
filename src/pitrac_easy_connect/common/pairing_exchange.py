"""Handing the pairing secret to the PC without ever transmitting it.

Pairing is the one moment when a long-lived secret has to get from the enclosure
to the computer. Sending it over plain HTTP on the local network would mean that
anyone who happened to be capturing traffic at that instant owns the enclosure
from then on. The window is short, but it is not acceptable for a device that
may be sold or given away.

So the secret is never sent. Both sides run an ephemeral Diffie-Hellman exchange
over the 2048-bit MODP group from RFC 3526, derive a shared key from it, and the
enclosure returns the pairing secret masked with a key derived from that. A
passive listener sees two public values and a masked blob, and can compute
nothing from them.

Each side also sends a proof: an HMAC over its role and the two public values,
under a key derived from the shared one. That shows the answer came from whoever
holds the private half of the value the exchange started with, so the app knows
it is still talking to the enclosure it began with and not something that joined
partway through, and neither side's proof can be replayed back as the other's.

What this does not do is decide *whether* to pair. Nothing here is a password;
there is no secret a human carries from one side to the other, so an attacker
who can sit in the middle of the connection can run the exchange themselves.
Standing in the way of that is `pairing.accepting`, and the trust boundary is
the local network. See the note at the top of `pi/pairing.py`.

So: forward secrecy against anything merely listening, and no cryptography
package to install — it is built from `pow`, `hmac`, and `secrets` alone.
"""

import hmac
import secrets
from hashlib import sha256
from typing import Tuple

#: RFC 3526 group 14. A published, fixed, well-reviewed group; nothing here
#: depends on it being secret.
PRIME = int(
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E08"
    "8A67CC74020BBEA63B139B22514A08798E3404DDEF9519B3CD3A431B"
    "302B0A6DF25F14374FE1356D6D51C245E485B576625E7EC6F44C42E9"
    "A637ED6B0BFF5CB6F406B7EDEE386BFB5A899FA5AE9F24117C4B1FE6"
    "49286651ECE45B3DC2007CB8A163BF0598DA48361C55D39A69163FA8"
    "FD24CF5F83655D23DCA3AD961C62F356208552BB9ED529077096966D"
    "670C354E4ABC9804F1746C08CA18217C32905E462E36CE3BE39E772C"
    "180E86039B2783A2EC07A28FB5C55DF06F4C52C9DE2BCBF695581718"
    "3995497CEA956AE515D2261898FA051015728E5A8AACAA68FFFFFFFF"
    "FFFFFFFF",
    16,
)
GENERATOR = 2
PRIVATE_BITS = 256
BYTE_LENGTH = 256  # 2048 bits


def generate_private() -> int:
    # A 256-bit exponent gives roughly 128-bit security in this group, which is
    # far more than a value that lives for the few seconds a pairing takes.
    return secrets.randbits(PRIVATE_BITS) | (1 << (PRIVATE_BITS - 1))


def public_for(private: int) -> str:
    return format(pow(GENERATOR, private, PRIME), "x")


def _valid_public(value: int) -> bool:
    # Rejecting 0, 1, and p-1 blocks the small-subgroup values an attacker would
    # send to force a predictable shared key.
    return 1 < value < PRIME - 1


def shared_key(their_public: str, my_private: int) -> bytes:
    try:
        theirs = int(str(their_public), 16)
    except ValueError as exc:
        raise ValueError("The other side sent an invalid public value") from exc
    if not _valid_public(theirs):
        raise ValueError("The other side sent an unusable public value")
    shared = pow(theirs, my_private, PRIME)
    return sha256(shared.to_bytes(BYTE_LENGTH, "big")).digest()


def derive(key: bytes, label: str) -> bytes:
    return hmac.new(key, label.encode("utf-8"), sha256).digest()


def transcript(server_public: str, client_public: str) -> str:
    return "{}|{}".format(server_public, client_public)


def proof(key: bytes, server_public: str, client_public: str, role: str) -> str:
    """Show this side derived the same key from the same two public values.

    It proves the answer came from whoever holds the private half of
    ``server_public`` — that the reply is from the enclosure the app started
    talking to, not something that joined halfway through. Including the role
    stops one side's proof being replayed back as the other's.
    """

    material = "{}|{}".format(role, transcript(server_public, client_public))
    return hmac.new(derive(key, "proof"), material.encode("utf-8"), sha256).hexdigest()


def mask_secret(key: bytes, secret_hex: str) -> str:
    """Hide the pairing secret under a key only the two participants share."""

    secret = bytes.fromhex(secret_hex)
    stream = _keystream(key, len(secret))
    return bytes(a ^ b for a, b in zip(secret, stream)).hex()


def unmask_secret(key: bytes, masked_hex: str) -> str:
    masked = bytes.fromhex(masked_hex)
    stream = _keystream(key, len(masked))
    return bytes(a ^ b for a, b in zip(masked, stream)).hex()


def _keystream(key: bytes, length: int) -> bytes:
    """Enough key material for one secret, from repeated HMAC counters."""

    block = b""
    counter = 0
    while len(block) < length:
        block += hmac.new(key, "mask|{}".format(counter).encode("utf-8"), sha256).digest()
        counter += 1
    return block[:length]


def client_start() -> Tuple[int, str]:
    private = generate_private()
    return private, public_for(private)


def verify_proof(expected: str, offered: str) -> bool:
    return hmac.compare_digest(expected, str(offered or ""))
