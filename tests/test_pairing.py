import pytest

from pitrac_easy_connect.common.errors import EasyConnectError
from pitrac_easy_connect.pi.pairing import (
    FAILURE_WINDOW_SECONDS,
    MAX_FAILURES,
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
    return manager.redeem(manager.issue_code().code, name)


# --- Codes ----------------------------------------------------------------


def test_a_code_is_six_digits(tmp_path):
    manager, _ = build(tmp_path)
    code = manager.issue_code().code
    assert len(code) == 6 and code.isdigit()


def test_a_code_works_exactly_once(tmp_path):
    manager, _ = build(tmp_path)
    code = manager.issue_code().code
    manager.redeem(code, "First PC")
    with pytest.raises(EasyConnectError) as caught:
        manager.redeem(code, "Second PC")
    assert caught.value.info.code == "PT-PAIR-002"


def test_a_code_expires(tmp_path):
    manager, clock = build(tmp_path)
    code = manager.issue_code().code
    clock.advance(301)
    with pytest.raises(EasyConnectError) as caught:
        manager.redeem(code, "Late PC")
    assert caught.value.info.code == "PT-PAIR-002"


def test_an_expired_code_is_not_shown_as_current(tmp_path):
    manager, clock = build(tmp_path)
    manager.issue_code()
    clock.advance(301)
    assert manager.current_code() is None
    assert manager.code_for_display().seconds_left(clock()) > 0


def test_a_wrong_code_is_rejected(tmp_path):
    manager, _ = build(tmp_path)
    manager.issue_code()
    with pytest.raises(EasyConnectError) as caught:
        manager.redeem("000000" if manager.current_code().code != "000000" else "111111", "PC")
    assert caught.value.info.code == "PT-PAIR-001"


def test_guessing_is_rate_limited(tmp_path):
    manager, clock = build(tmp_path)
    real = manager.issue_code().code
    wrong = "999999" if real != "999999" else "888888"

    for _ in range(MAX_FAILURES):
        with pytest.raises(EasyConnectError):
            manager.redeem(wrong, "Attacker")

    with pytest.raises(EasyConnectError) as caught:
        manager.redeem(wrong, "Attacker")
    assert caught.value.info.code == "PT-PAIR-003"


def test_the_rate_limit_lifts_after_the_window(tmp_path):
    manager, clock = build(tmp_path)
    real = manager.issue_code().code
    wrong = "999999" if real != "999999" else "888888"
    for _ in range(MAX_FAILURES):
        with pytest.raises(EasyConnectError):
            manager.redeem(wrong, "Attacker")

    # The owner comes back later and asks the setup page for a fresh code. The
    # lockout must not outlive the window, or a mistyped code would strand them.
    clock.advance(FAILURE_WINDOW_SECONDS + 1)
    assert manager.redeem(manager.issue_code().code, "Owner PC").pairing_id


def test_a_successful_pairing_clears_earlier_failures(tmp_path):
    manager, _ = build(tmp_path)
    real = manager.issue_code().code
    wrong = "999999" if real != "999999" else "888888"
    for _ in range(MAX_FAILURES - 1):
        with pytest.raises(EasyConnectError):
            manager.redeem(wrong, "Fumbling user")
    manager.redeem(real, "Owner PC")

    # A user who mistyped a few times and then succeeded is not left one
    # attempt away from being locked out next time.
    second = manager.issue_code().code
    assert manager.redeem(second, "Second PC").pairing_id


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
