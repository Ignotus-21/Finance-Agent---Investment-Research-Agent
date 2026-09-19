"""Tests for API bearer-token authentication.

What these guard against is a specific regression. ``verify_auth_token`` used to
accept any bearer string of five characters or more and return
``f"analyst-user-{token[:6]}"`` as the caller's identity, so ``Bearer hunter2``
was recorded in the audit log as ``analyst-user-hunter``. Nothing in the suite
noticed, because every test sent a well-formed-looking token and every
well-formed-looking token was accepted.
"""

import pytest
from fastapi import HTTPException
from google.auth.exceptions import GoogleAuthError
from pydantic import ValidationError

from src.api import dependencies
from src.config import SAMPLE_GCP_PROJECT_ID, Settings

pytestmark = pytest.mark.asyncio

# A custom audience and the service's own URL. Cloud Run accepts a token minted
# for either, so the application has to as well - see the module docstring on
# ``allowed_audiences``.
AUDIENCE = "ira-service-production"
RUN_URL = "https://ira-service-production-000000000000.us-central1.run.app"
CONFIGURED = f"{AUDIENCE},{RUN_URL}"


@pytest.fixture
def verifying(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put the dependency into its verifying mode."""
    monkeypatch.setattr(dependencies.settings, "auth_allowed_audiences", CONFIGURED)


def _stub_claims(monkeypatch: pytest.MonkeyPatch, claims: dict[str, object]) -> list[dict]:
    """Replace token verification with a stub, recording how it was called."""
    calls: list[dict] = []

    def _fake(token: str, transport: object, audience: object = None) -> dict[str, object]:
        calls.append({"token": token, "audience": audience})
        return claims

    monkeypatch.setattr(dependencies.id_token, "verify_oauth2_token", _fake)
    return calls


# ---------------------------------------------------------------------------
# Header parsing
# ---------------------------------------------------------------------------


async def test_missing_header_is_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        await dependencies.verify_auth_token(None)
    assert exc.value.status_code == 401


@pytest.mark.parametrize(
    "header",
    [
        "test-valid-analyst-token",  # no scheme
        "Basic dXNlcjpwYXNz",        # wrong scheme
        "Bearer",                    # no credential
        "Bearer a b",                # three parts
        "Bearer ",                   # empty credential
    ],
)
async def test_malformed_authorization_headers_are_rejected(header: str) -> None:
    with pytest.raises(HTTPException) as exc:
        await dependencies.verify_auth_token(header)
    assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


async def test_identity_comes_from_the_verified_email_claim(
    verifying: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _stub_claims(monkeypatch, {"email": "analyst@example.com", "sub": "1234567890"})

    identity = await dependencies.verify_auth_token("Bearer a.real.looking.jwt")

    assert identity == "analyst@example.com"
    # The audience must be checked, and both configured values must reach the
    # verifier. A token minted for some other Cloud Run service in the same
    # project is signed by Google and passes every other claim; the audience is
    # the only thing that makes it not valid here. Equally, dropping one of the
    # two would reject a token Cloud Run had already admitted.
    assert calls == [{"token": "a.real.looking.jwt", "audience": [AUDIENCE, RUN_URL]}]


async def test_identity_falls_back_to_sub_when_no_email_claim(
    verifying: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_claims(monkeypatch, {"sub": "108743219876543210987"})

    assert await dependencies.verify_auth_token("Bearer jwt") == "108743219876543210987"


async def test_token_without_any_identity_claim_is_rejected(
    verifying: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_claims(monkeypatch, {"iss": "https://accounts.google.com"})

    with pytest.raises(HTTPException) as exc:
        await dependencies.verify_auth_token("Bearer jwt")
    assert exc.value.status_code == 401


@pytest.mark.parametrize("error", [ValueError("Token expired"), GoogleAuthError("bad signature")])
async def test_failed_verification_is_rejected(
    verifying: None, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    def _raise(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise error

    monkeypatch.setattr(dependencies.id_token, "verify_oauth2_token", _raise)

    with pytest.raises(HTTPException) as exc:
        await dependencies.verify_auth_token("Bearer forged")
    assert exc.value.status_code == 401
    # The reason is logged, not returned. Telling an unauthenticated caller
    # which claim failed tells them which value to change next.
    assert exc.value.detail == "Bearer token failed verification."


async def test_arbitrary_string_is_rejected_when_verifying(verifying: None) -> None:
    """The regression itself. This used to return 'analyst-user-hunter'."""
    with pytest.raises(HTTPException) as exc:
        await dependencies.verify_auth_token("Bearer hunter2")
    assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# The development path, and the thing that keeps it out of production
# ---------------------------------------------------------------------------


async def test_development_identity_is_labelled_unverified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no audience configured nothing can be verified, and the identity says so.

    The prefix is the point: it reaches the audit log, so a record written on
    this path cannot be mistaken later for an authenticated one.
    """
    monkeypatch.setattr(dependencies.settings, "auth_allowed_audiences", "")

    identity = await dependencies.verify_auth_token("Bearer test-valid-analyst-token")

    assert identity.startswith("unverified-")


@pytest.mark.parametrize("configured", ["", "   ", ",", " , "])
async def test_blank_audience_configurations_do_not_enable_verification(
    monkeypatch: pytest.MonkeyPatch, configured: str
) -> None:
    """A string of separators parses to nothing, and nothing means development.

    Worth pinning because the failure mode is silent: if ``" , "`` parsed to
    ``["", ""]`` the service would look configured, take the verifying branch,
    and reject every token with an audience mismatch it never had.
    """
    monkeypatch.setattr(dependencies.settings, "auth_allowed_audiences", configured)

    assert (await dependencies.verify_auth_token("Bearer anything")).startswith("unverified-")


# ---------------------------------------------------------------------------
# Parsing the comma-separated setting
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("", ()),
        ("one", ("one",)),
        ("one,two", ("one", "two")),
        (" one , two ", ("one", "two")),  # Cloud Run env vars pick up stray spaces
        ("one,,two,", ("one", "two")),  # and stray separators
    ],
)
def test_allowed_audiences_parsing(configured: str, expected: tuple[str, ...]) -> None:
    settings = Settings(
        environment="development",
        auth_allowed_audiences=configured,
        offline_mode=True,
    )
    assert settings.allowed_audiences == expected


def test_production_refuses_to_start_without_an_audience() -> None:
    with pytest.raises(ValidationError, match="AUTH_ALLOWED_AUDIENCES"):
        Settings(
            environment="production",
            auth_allowed_audiences="",
            offline_mode=True,
        )


def test_production_refuses_to_start_on_a_whitespace_only_audience() -> None:
    """`custom_audiences = [""]` in tfvars would otherwise look like configuration."""
    with pytest.raises(ValidationError, match="AUTH_ALLOWED_AUDIENCES"):
        Settings(
            environment="production",
            auth_allowed_audiences="  ,  ",
            offline_mode=True,
        )


def test_production_starts_with_an_audience() -> None:
    settings = Settings(
        environment="production",
        auth_allowed_audiences=CONFIGURED,
        gcp_project_id="a-real-project",
        offline_mode=True,
    )
    assert settings.allowed_audiences == (AUDIENCE, RUN_URL)


def test_production_refuses_to_start_on_the_sample_project_id() -> None:
    """A production deployment that kept the sample project id publishes nowhere.

    Leaving the default in place is not a harmless no-op: Pub/Sub and the audit
    trace links silently address a project this deployment does not own, and the
    only evidence is a contained error on stderr. Fail at startup instead.
    """
    with pytest.raises(ValidationError, match="GCP_PROJECT_ID"):
        Settings(
            environment="production",
            auth_allowed_audiences=CONFIGURED,
            gcp_project_id=SAMPLE_GCP_PROJECT_ID,
            offline_mode=True,
        )
