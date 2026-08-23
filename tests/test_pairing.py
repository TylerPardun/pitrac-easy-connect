import pytest

from pitrac_easy_connect.common import pairing_exchange as exchange
from pitrac_easy_connect.common.errors import EasyConnectError
from pitrac_easy_connect.pi.pairing import (
    FAILURE_WINDOW_SECONDS,
    MAX_FAILURES,
    PAIRING_WINDOW_SECONDS,
    PairingManager,
)


class FakeClock:
    def __init__(self):
        self.now = 1_700_000_000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def build(tmp_path, clock=None):
    clock = clock or FakeClock()
    return PairingManager(tmp_path / "pairings.json", "P3V2PW2U", clock=clock), clock


def pair_one(manager, name="Sim Room PC"):
    return manager.create_pairing(name)


# --- Who is allowed to pair, and when -------------------------------------


def ask_to_pair(manager, name="Sim Room PC"):
    """Everything a computer does to pair, with nothing typed by a human."""

    hello = manager.begin_exchange()
    private, public = exchange.client_start()
    result = manager.complete_exchange(hello["sessionId"], public, name)
    key = exchange.shared_key(hello["serverPublic"], private)
    # The computer checks the enclosure ran the same exchange before trusting it.
    assert exchange.verify_proof(
        exchange.proof(key, hello["serverPublic"], public, "server"),
        result["serverProof"],
    )
    return exchange.unmask_secret(key, result["maskedSecret"])


def test_the_first_computer_may_pair_with_nothing_asked_of_it(tmp_path):
    """An enclosure with nothing paired to it is one nobody has set up yet."""

    manager, _ = build(tmp_path)
    assert manager.accepting()
    assert ask_to_pair(manager)
    assert manager.count == 1


def test_a_second_computer_is_refused_until_the_owner_opens_a_window(tmp_path):
    manager, _ = build(tmp_path)
    ask_to_pair(manager, "Owner PC")

    assert not manager.accepting()
    with pytest.raises(EasyConnectError) as caught:
        ask_to_pair(manager, "Someone else's laptop")
    assert caught.value.info.code == "PT-PAIR-001"

    manager.open_window()
    assert ask_to_pair(manager, "Kitchen laptop")
    assert manager.count == 2


def test_a_window_lets_in_one_computer_and_then_closes(tmp_path):
    """Otherwise opening it once would leave the enclosure open to everything."""

    manager, _ = build(tmp_path)
    ask_to_pair(manager, "Owner PC")
    manager.open_window()
    ask_to_pair(manager, "Second PC")

    assert not manager.accepting()
    with pytest.raises(EasyConnectError) as caught:
        ask_to_pair(manager, "Third PC")
    assert caught.value.info.code == "PT-PAIR-001"


def test_a_window_left_open_expires_on_its_own(tmp_path):
    manager, clock = build(tmp_path)
    ask_to_pair(manager, "Owner PC")
    manager.open_window()

    clock.advance(PAIRING_WINDOW_SECONDS + 1)
    assert not manager.accepting()
    with pytest.raises(EasyConnectError):
        ask_to_pair(manager, "Much later PC")


def test_unpairing_everything_is_the_way_back_in(tmp_path):
    """Without this an enclosure whose only computer died could not be reached."""

    manager, _ = build(tmp_path)
    ask_to_pair(manager, "Owner PC")
    assert not manager.accepting()

    manager.revoke_all()
    assert manager.accepting()
    assert ask_to_pair(manager, "Replacement PC")


def test_refused_attempts_are_rate_limited(tmp_path):
    manager, _ = build(tmp_path)
    ask_to_pair(manager, "Owner PC")

    for _ in range(MAX_FAILURES):
        with pytest.raises(EasyConnectError):
            ask_to_pair(manager, "Persistent stranger")

    with pytest.raises(EasyConnectError) as caught:
        ask_to_pair(manager, "Persistent stranger")
    assert caught.value.info.code == "PT-PAIR-003"


def test_the_rate_limit_lifts_after_the_window(tmp_path):
    manager, clock = build(tmp_path)
    ask_to_pair(manager, "Owner PC")
    for _ in range(MAX_FAILURES):
        with pytest.raises(EasyConnectError):
            ask_to_pair(manager, "Stranger")

    # The owner comes back later and opens a window. The lockout must not
    # outlive its own duration, or their own computer would be stranded.
    clock.advance(FAILURE_WINDOW_SECONDS + 1)
    manager.open_window()
    assert ask_to_pair(manager, "Owner's second PC")


def test_a_successful_pairing_clears_earlier_refusals(tmp_path):
    manager, clock = build(tmp_path)
    ask_to_pair(manager, "Owner PC")
    for _ in range(MAX_FAILURES - 1):
        with pytest.raises(EasyConnectError):
            ask_to_pair(manager, "Stranger")

    manager.open_window()
    ask_to_pair(manager, "Second PC")

    # Someone who was refused a few times and then let in is not left one
    # attempt away from a lockout next time.
    manager.open_window()
    assert ask_to_pair(manager, "Third PC")


def test_a_stale_link_pairing_cannot_lock_out_a_new_pairing_exchange(tmp_path):
    """Link authentication failures and pairing-exchange failures must be
    counted separately, so a stale computer hammering a revoked or unknown
    link pairing id can never deny the owner's own new-computer pairing."""

    manager, _ = build(tmp_path)
    ask_to_pair(manager, "Owner PC")  # nothing is accepting any more

    for _ in range(MAX_FAILURES + 2):
        with pytest.raises(EasyConnectError) as caught:
            manager.verify("stale-old-pairing-id", manager.new_challenge(), "0" * 64)
        assert caught.value.info.code in ("PT-PAIR-004", "PT-PAIR-003")

    # The link bucket for that one pairing id is now exhausted, but a fresh
    # pairing exchange (a different bucket entirely) is untouched by it.
    manager.open_window()
    assert ask_to_pair(manager, "Legitimate second PC")


def test_a_stale_exchange_source_cannot_lock_out_link_authentication(tmp_path):
    manager, _ = build(tmp_path)
    pairing = pair_one(manager, "Owner PC")

    for _ in range(MAX_FAILURES + 2):
        with pytest.raises(EasyConnectError):
            manager.complete_exchange("no-such-session", "not-a-real-key", "Stranger", source="10.0.0.9")

    # complete_exchange's own failures (a different bucket, keyed by source)
    # must not have touched the already-paired computer's ability to verify.
    challenge = manager.new_challenge()
    manager.verify(
        pairing.pairing_id, challenge, PairingManager.client_proof(pairing.secret, challenge)
    )


def test_two_exchange_sources_do_not_share_a_bucket(tmp_path):
    manager, _ = build(tmp_path)
    ask_to_pair(manager, "Owner PC")  # closes the door

    for _ in range(MAX_FAILURES + 2):
        with pytest.raises(EasyConnectError):
            manager.complete_exchange("no-such-session", "junk", "Attacker", source="10.0.0.66")

    # A different source is refused for the real reason (not accepting), not
    # rate-limited by another address's failures.
    manager.open_window()
    with pytest.raises(EasyConnectError) as caught:
        manager.complete_exchange("no-such-session", "junk", "Someone else", source="10.0.0.77")
    assert caught.value.info.code == "PT-PAIR-002"


def test_rate_limit_errors_carry_a_usable_retry_countdown(tmp_path):
    manager, clock = build(tmp_path)
    ask_to_pair(manager, "Owner PC")

    for _ in range(MAX_FAILURES):
        with pytest.raises(EasyConnectError):
            ask_to_pair(manager, "Stranger")

    clock.advance(120)
    with pytest.raises(EasyConnectError) as caught:
        ask_to_pair(manager, "Stranger")
    assert caught.value.info.code == "PT-PAIR-003"
    body = caught.value.as_dict()
    assert 0 < body["retryAfterSeconds"] <= FAILURE_WINDOW_SECONDS

    clock.advance(body["retryAfterSeconds"])
    manager.open_window()
    assert ask_to_pair(manager, "Owner's second PC")


def test_the_trusted_computer_list_has_a_documented_ceiling(tmp_path):
    from pitrac_easy_connect.pi.pairing import MAX_TRUSTED_COMPUTERS

    manager, _ = build(tmp_path)
    ask_to_pair(manager, "First PC")
    for index in range(MAX_TRUSTED_COMPUTERS - 1):
        manager.open_window()
        ask_to_pair(manager, "PC {}".format(index))
    assert manager.count == MAX_TRUSTED_COMPUTERS

    manager.open_window()
    with pytest.raises(EasyConnectError):
        ask_to_pair(manager, "One too many")
    assert manager.count == MAX_TRUSTED_COMPUTERS


# --- Secrets --------------------------------------------------------------


def test_each_computer_gets_its_own_secret(tmp_path):
    manager, _ = build(tmp_path)
    first = pair_one(manager, "PC one")
    second = pair_one(manager, "PC two")
    assert first.secret != second.secret
    assert first.pairing_id != second.pairing_id


def test_two_enclosures_never_share_a_secret(tmp_path):
    first, _ = build(tmp_path / "a")
    second, _ = build(tmp_path / "b")
    (tmp_path / "a").mkdir(exist_ok=True)
    (tmp_path / "b").mkdir(exist_ok=True)
    assert pair_one(first).secret != pair_one(second).secret


def test_the_challenge_is_different_every_time(tmp_path):
    manager, _ = build(tmp_path)
    assert len({manager.new_challenge() for _ in range(200)}) == 200


def test_a_paired_computer_proves_itself_without_sending_the_secret(tmp_path):
    manager, _ = build(tmp_path)
    pairing = pair_one(manager)
    challenge = manager.new_challenge()
    proof = PairingManager.client_proof(pairing.secret, challenge)
    manager.verify(pairing.pairing_id, challenge, proof)


def test_the_enclosure_also_proves_itself_to_the_computer(tmp_path):
    manager, _ = build(tmp_path)
    pairing = pair_one(manager)
    challenge = manager.new_challenge()
    assert manager.server_proof(pairing.pairing_id, challenge) == PairingManager.expected_server_proof(
        pairing.secret, challenge
    )


def test_a_proof_for_one_challenge_does_not_work_for_another(tmp_path):
    manager, _ = build(tmp_path)
    pairing = pair_one(manager)
    stolen = PairingManager.client_proof(pairing.secret, manager.new_challenge())
    with pytest.raises(EasyConnectError) as caught:
        manager.verify(pairing.pairing_id, manager.new_challenge(), stolen)
    assert caught.value.info.code == "PT-PAIR-004"


def test_the_client_and_server_proofs_are_not_interchangeable(tmp_path):
    manager, _ = build(tmp_path)
    pairing = pair_one(manager)
    challenge = manager.new_challenge()
    server_side = PairingManager.expected_server_proof(pairing.secret, challenge)
    with pytest.raises(EasyConnectError):
        manager.verify(pairing.pairing_id, challenge, server_side)


def test_an_unknown_computer_is_refused(tmp_path):
    manager, _ = build(tmp_path)
    with pytest.raises(EasyConnectError) as caught:
        manager.verify("not-a-real-id", manager.new_challenge(), "0" * 64)
    assert caught.value.info.code == "PT-PAIR-004"


# --- Managing trusted computers ------------------------------------------


def test_revoking_takes_effect_immediately(tmp_path):
    manager, _ = build(tmp_path)
    pairing = pair_one(manager)
    manager.revoke(pairing.pairing_id)

    challenge = manager.new_challenge()
    proof = PairingManager.client_proof(pairing.secret, challenge)
    with pytest.raises(EasyConnectError):
        manager.verify(pairing.pairing_id, challenge, proof)


def test_revoking_one_computer_leaves_the_others_working(tmp_path):
    manager, _ = build(tmp_path)
    keep = pair_one(manager, "Keep me")
    drop = pair_one(manager, "Drop me")
    manager.revoke(drop.pairing_id)

    challenge = manager.new_challenge()
    manager.verify(keep.pairing_id, challenge, PairingManager.client_proof(keep.secret, challenge))
    assert manager.count == 1


def test_preparing_for_a_new_owner_removes_every_pairing(tmp_path):
    manager, _ = build(tmp_path)
    old_owner = pair_one(manager)
    manager.revoke_all()

    challenge = manager.new_challenge()
    with pytest.raises(EasyConnectError):
        manager.verify(
            old_owner.pairing_id, challenge, PairingManager.client_proof(old_owner.secret, challenge)
        )
    assert manager.count == 0


def test_pairings_survive_a_restart(tmp_path):
    manager, clock = build(tmp_path)
    pairing = pair_one(manager)

    restarted = PairingManager(tmp_path / "pairings.json", "P3V2PW2U", clock=clock)
    challenge = restarted.new_challenge()
    restarted.verify(
        pairing.pairing_id, challenge, PairingManager.client_proof(pairing.secret, challenge)
    )


def test_a_computer_can_be_renamed(tmp_path):
    manager, _ = build(tmp_path)
    pairing = pair_one(manager, "DESKTOP-4F2K1")
    manager.rename(pairing.pairing_id, "  Garage  PC ")
    assert manager.trusted_computers()[0]["name"] == "Garage PC"


def test_the_trusted_list_records_when_each_pc_was_last_seen(tmp_path):
    manager, clock = build(tmp_path)
    pairing = pair_one(manager)
    clock.advance(3600)
    manager.touch(pairing.pairing_id)
    assert manager.trusted_computers()[0]["lastSeen"] == clock()


def test_the_stored_secret_is_never_in_the_trusted_list(tmp_path):
    manager, _ = build(tmp_path)
    pair_one(manager)
    assert "secret" not in repr(manager.trusted_computers())


def test_a_revoked_computer_is_told_why_rather_than_treated_as_a_stranger(tmp_path):
    manager, _clock = build(tmp_path)
    pairing = pair_one(manager)
    manager.revoke(pairing.pairing_id)

    challenge = manager.new_challenge()
    proof = PairingManager.client_proof(pairing.secret, challenge)
    with pytest.raises(EasyConnectError) as caught:
        manager.verify(pairing.pairing_id, challenge, proof)
    assert caught.value.info.code == "PT-PAIR-005"
    assert "removed" in caught.value.info.failed


def test_a_computer_that_was_never_paired_is_still_just_unknown(tmp_path):
    manager, _clock = build(tmp_path)
    with pytest.raises(EasyConnectError) as caught:
        manager.verify("never-seen", manager.new_challenge(), "0" * 64)
    assert caught.value.info.code == "PT-PAIR-004"


def test_preparing_for_a_new_owner_tells_the_old_owners_computers_why(tmp_path):
    manager, _clock = build(tmp_path)
    pairing = pair_one(manager)
    manager.revoke_all()

    challenge = manager.new_challenge()
    with pytest.raises(EasyConnectError) as caught:
        manager.verify(
            pairing.pairing_id, challenge, PairingManager.client_proof(pairing.secret, challenge)
        )
    assert caught.value.info.code == "PT-PAIR-005"


def test_the_revoked_list_cannot_grow_without_bound(tmp_path):
    manager, _clock = build(tmp_path)
    for _ in range(80):
        manager.revoke(pair_one(manager).pairing_id)
    assert len(manager._store.get("revoked")) <= 50


def test_two_computers_arriving_together_cannot_both_be_admitted(tmp_path):
    """The window admits one. Two requests racing must not both pass.

    The check and the creation were in the same method but not the same locked
    section, so both could decide yes before either consumed the window. The
    real window is microseconds wide, so it is widened here deliberately:
    without that this test passes against the bug and proves nothing.
    """

    import threading
    import time

    manager, _clock = build(tmp_path)
    ask_to_pair(manager, "Owner PC")          # closes the door
    manager.open_window()                     # and opens it for exactly one

    # Widen the gap between deciding and recording. If the two are not in the
    # same locked section, this is where the second request slips through.
    original = manager.create_pairing

    def slow_create(name=""):
        time.sleep(0.25)
        return original(name)

    manager.create_pairing = slow_create

    results, errors = [], []
    start = threading.Barrier(2)

    def race(name):
        start.wait()
        try:
            results.append(ask_to_pair(manager, name))
        except EasyConnectError as exc:
            errors.append(exc.info.code)

    threads = [threading.Thread(target=race, args=("A",)),
               threading.Thread(target=race, args=("B",))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(results) == 1, "exactly one should get in, got {}".format(len(results))
    assert errors == ["PT-PAIR-001"], errors
    assert manager.count == 2, "the owner's, plus exactly one more"
