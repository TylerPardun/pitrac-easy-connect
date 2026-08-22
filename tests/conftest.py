"""Shared helpers for the test suite."""

import threading


def start_serving(server):
    """Run ``server`` on a background thread, and return how to stop it.

    Closing a socket while another thread is still selecting on it is
    undefined. POSIX shrugs; Windows raises WinError 10038 from inside the
    serving thread, which prints a traceback that looks exactly like a real
    failure and is not one. Stopping in order -- leave the loop, join the
    thread, then close -- keeps the run readable on every platform.
    """

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def stop():
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    return stop
