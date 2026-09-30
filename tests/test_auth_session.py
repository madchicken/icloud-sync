"""
The pyicloud session (cookies + trust token) must survive reboots and the
periodic purge of $TMPDIR, otherwise every daemon start asks for 2FA again.
Every PyiCloudService we construct has to point at the same persistent dir.
"""
import pytest

from icloud_sync import auth, cli
from icloud_sync.config import SESSION_DIR


class FakeApi:
    requires_2fa = False
    requires_2sa = False
    is_trusted_session = True
    kwargs: dict = {}

    def __init__(self, **kwargs):
        type(self).kwargs = kwargs


@pytest.fixture
def fake_service(monkeypatch):
    monkeypatch.setattr(auth, "PyiCloudService", FakeApi)
    monkeypatch.setattr("pyicloud.PyiCloudService", FakeApi)
    monkeypatch.setattr(auth, "get_password", lambda _u: "pw")
    monkeypatch.setattr(cli, "get_password", lambda _u: "pw")
    FakeApi.kwargs = {}
    return FakeApi


def test_session_dir_is_not_in_tmp():
    assert "/T/" not in str(SESSION_DIR) and not str(SESSION_DIR).startswith("/tmp")
    assert str(SESSION_DIR).endswith(".config/icloud_sync/session")


def test_daemon_authenticate_uses_persistent_session_dir(fake_service):
    auth.authenticate("me@example.com")
    assert fake_service.kwargs["cookie_directory"] == str(SESSION_DIR)


def test_interactive_authenticate_uses_persistent_session_dir(fake_service):
    auth.interactive_authenticate("me@example.com", "pw")
    assert fake_service.kwargs["cookie_directory"] == str(SESSION_DIR)


def test_cli_verify_uses_persistent_session_dir(fake_service):
    with pytest.raises(SystemExit) as exc:
        cli.cmd_verify(["--username", "me@example.com"])
    assert exc.value.code == 0
    assert fake_service.kwargs["cookie_directory"] == str(SESSION_DIR)


class TwoFAApi(FakeApi):
    """Rejects the first code, accepts the second; counts code requests."""
    requires_2fa = True
    security_key_names = None
    two_factor_delivery_method = "trusted_device"
    is_trusted_session = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        type(self).instance = self
        self.requests = 0
        self.codes = []

    def request_2fa_code(self):
        self.requests += 1
        return True

    def validate_2fa_code(self, code):
        self.codes.append(code)
        return len(self.codes) >= 2


def test_daemon_requests_fresh_code_before_each_retry(monkeypatch):
    from icloud_sync import twofa

    monkeypatch.setattr(auth, "PyiCloudService", TwoFAApi)
    monkeypatch.setattr(auth, "get_password", lambda _u: "pw")
    monkeypatch.setattr(auth, "notify", lambda *_: None)
    codes = iter(["111111", "222222"])
    prompts = []
    monkeypatch.setattr(twofa, "request_code", lambda message="": prompts.append(message))
    monkeypatch.setattr(twofa, "wait_for_code", lambda **_: next(codes))

    auth.authenticate("me@example.com")

    api = TwoFAApi.instance
    assert api.codes == ["111111", "222222"]
    assert api.requests == 1, "one fresh code per retry, none before the first attempt"
    assert "not accepted" in prompts[1]
