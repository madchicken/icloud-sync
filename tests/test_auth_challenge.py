"""
Never prompt for a verification code Apple did not send.

pyicloud reports requires_2fa whenever the session is untrusted — including the
common case where a stored session token still validates. On that path no fresh
login happens, so Apple issues no challenge and sends no code, yet the daemon
used to block on a prompt and reject whatever was typed. Trusting the session
clears the requirement with no code at all, so that must be tried first.
"""
import pytest

from icloud_sync import auth


class FakeAPI:
    """Mirrors the pyicloud state machine the daemon actually branches on."""

    def __init__(self, *, trusted=False, pending_challenge=False,
                 trust_succeeds=True, refresh_issues_challenge=True):
        self.is_trusted_session = trusted
        self._auth_data = {"mode": "trusteddevice"} if pending_challenge else {}
        self._requires_mfa = pending_challenge
        self._trust_succeeds = trust_succeeds
        self._refresh_issues_challenge = refresh_issues_challenge

        self.trust_calls = 0
        self.refresh_calls = 0
        self.validated_codes = []

    # --- pyicloud surface the daemon uses ---

    @property
    def requires_2fa(self):
        return not self.is_trusted_session or self._requires_mfa

    @property
    def requires_2sa(self):
        return self.requires_2fa

    security_key_names = None

    def trust_session(self):
        self.trust_calls += 1
        # Real trust_session() clears this flag even when it then fails.
        self._requires_mfa = False
        if self._trust_succeeds:
            self.is_trusted_session = True
            return True
        return False

    def authenticate(self, force_refresh=False):
        self.refresh_calls += 1
        if self._refresh_issues_challenge:
            self._auth_data = {"mode": "trusteddevice"}
            self._requires_mfa = True

    def validate_2fa_code(self, code):
        self.validated_codes.append(code)
        return True


@pytest.fixture
def wiring(monkeypatch):
    """Install a FakeAPI and record whether the daemon ever prompts."""
    state = {"prompted": 0, "api": None}

    monkeypatch.setattr(auth, "get_password", lambda u: "pw")
    monkeypatch.setattr(auth, "notify", lambda *a, **k: None)

    def fake_wait(kind="2fa"):
        state["prompted"] += 1
        return "123456"

    monkeypatch.setattr(auth, "_wait_for_code_file", fake_wait)

    def install(api):
        state["api"] = api
        monkeypatch.setattr(auth, "PyiCloudService", lambda **kw: api)
        return state

    state["install"] = install
    return state


# --------------------------------------------------------------------------- #
# The reported bug
# --------------------------------------------------------------------------- #

def test_untrusted_session_without_challenge_is_trusted_not_prompted(wiring):
    """The exact failing case: valid token, untrusted session, no code in flight."""
    api = FakeAPI(trusted=False, pending_challenge=False, trust_succeeds=True)
    wiring["install"](api)

    result = auth.authenticate("someone@icloud.com")

    assert wiring["prompted"] == 0, "prompted for a code Apple never sent"
    assert api.trust_calls >= 1, "never tried to trust the session"
    assert api.is_trusted_session
    assert result is api


def test_no_code_is_submitted_when_none_was_issued(wiring):
    api = FakeAPI(trusted=False, pending_challenge=False, trust_succeeds=True)
    wiring["install"](api)

    auth.authenticate("someone@icloud.com")

    assert api.validated_codes == [], "submitted a code against no challenge"


# --------------------------------------------------------------------------- #
# Genuine 2FA must still work
# --------------------------------------------------------------------------- #

def test_live_challenge_still_prompts(wiring):
    """When Apple really did send a code, prompt — and don't pre-empt it."""
    api = FakeAPI(trusted=False, pending_challenge=True)
    wiring["install"](api)

    auth.authenticate("someone@icloud.com")

    assert wiring["prompted"] == 1
    assert api.validated_codes == ["123456"]


def test_live_challenge_is_not_short_circuited_by_trust(wiring):
    api = FakeAPI(trusted=False, pending_challenge=True)
    wiring["install"](api)

    auth.authenticate("someone@icloud.com")

    # Trusting before validating would throw away a live challenge.
    assert api.validated_codes == ["123456"]


def test_fresh_challenge_requested_when_trust_fails(wiring):
    """If the session cannot be trusted, force a real login so a code exists."""
    api = FakeAPI(trusted=False, pending_challenge=False, trust_succeeds=False,
                  refresh_issues_challenge=True)
    wiring["install"](api)

    auth.authenticate("someone@icloud.com")

    assert api.refresh_calls >= 1, "never asked Apple for a fresh challenge"
    assert wiring["prompted"] == 1
    assert api.validated_codes == ["123456"]


def test_already_trusted_session_is_left_alone(wiring):
    api = FakeAPI(trusted=True, pending_challenge=False)
    wiring["install"](api)

    auth.authenticate("someone@icloud.com")

    assert wiring["prompted"] == 0
    assert api.trust_calls == 0
    assert api.refresh_calls == 0
