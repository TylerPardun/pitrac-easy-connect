"""Entry point for the packaged native PiTrac desktop app."""

import os
import sys

import certifi


def configure_tls_certificate_store():
    """Give the frozen interpreter a CA store that exists after installation.

    GitHub Actions' macOS Python records a build-machine OpenSSL default that
    is not present on an owner's Mac.  An explicit override still wins for an
    administrator who needs one; otherwise every packaged HTTPS request uses
    the Mozilla CA bundle shipped with the application.
    """

    os.environ.setdefault("SSL_CERT_FILE", certifi.where())


configure_tls_certificate_store()

from pitrac_easy_connect.companion.app import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
