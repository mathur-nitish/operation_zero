"""M1 authentication tests, against the real test database (unique indexes and transactions included)."""

import asyncio
import uuid
from datetime import timedelta

import jwt
import pytest

from app.core.ids import utc_now
from app.core.security import create_access_token, hash_refresh_token

PASSWORD = "correct-horse-battery"


def unique_email() -> str:
    return f"player_{uuid.uuid4().hex[:12]}@example.com"


def unique_name() -> str:
    return f"p_{uuid.uuid4().hex[:12]}"  # 14 chars, within the 3–16 rule


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def register(client, email=None, name=None, password=PASSWORD, **extra):
    body = {"email": email or unique_email(), "password": password, "game_user_name": name or unique_name(), **extra}
    return await client.post("/v1/auth/register", json=body)


async def login(client, email, password=PASSWORD):
    return await client.post("/v1/auth/login", json={"email": email, "password": password})


async def refresh(client, refresh_token):
    return await client.post("/v1/auth/refresh", json={"refresh_token": refresh_token})


def error_code(response) -> str:
    return response.json()["error"]["code"]


# --- registration --------------------------------------------------------------------------


async def test_register_creates_account_and_returns_working_tokens(app_client, mongo_db):
    email, name = unique_email(), unique_name()
    async with app_client() as client:
        response = await register(
            client, email=email.upper(), name=name, client_info={"platform": "windows", "build": "0.1.0"}
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["token_type"] == "Bearer"
        assert body["expires_in"] == 900
        assert body["refresh_expires_in"] == 30 * 24 * 3600

        me = await client.get("/v1/auth/me", headers=bearer(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["game_user_id"] == body["game_user_id"]
    assert me.json()["account_status"] == "active"

    user_id = uuid.UUID(body["game_user_id"])
    assert user_id.version == 7
    user = await mongo_db.user_data.find_one({"game_user_id": user_id})
    identity = await mongo_db.auth_identities.find_one({"game_user_id": user_id})
    profile = await mongo_db.player_data_profile.find_one({"game_user_id": user_id})
    session = await mongo_db.auth_sessions.find_one({"game_user_id": user_id})

    assert user["account_status"] == "active" and user["session_epoch"] == 0 and user["ban"] is None
    assert identity["provider"] == "classic"
    assert identity["provider_user_id"] == email.lower()  # stored lower-cased
    assert identity["password_hash"].startswith("$argon2id$")
    assert PASSWORD not in identity["password_hash"]
    assert identity["email_verified"] is False
    assert profile["game_user_name"] == name and profile["game_user_name_lower"] == name.lower()
    assert session["token_hash"] == hash_refresh_token(body["refresh_token"])
    assert body["refresh_token"] not in str(session)  # raw refresh token is never stored
    assert session["client_info"] == {"platform": "windows", "build": "0.1.0"}


async def test_duplicate_email_is_rejected_case_insensitively(app_client, mongo_db):
    email = unique_email()
    async with app_client() as client:
        assert (await register(client, email=email)).status_code == 201
        second_name = unique_name()
        response = await register(client, email=email.upper(), name=second_name)
    assert response.status_code == 409
    assert error_code(response) == "email_taken"
    # The failed registration left nothing behind (transaction rolled back).
    assert await mongo_db.player_data_profile.count_documents({"game_user_name": second_name}) == 0


async def test_duplicate_name_is_rejected_case_insensitively_and_rolls_back(app_client, mongo_db):
    name = unique_name()
    async with app_client() as client:
        assert (await register(client, name=name)).status_code == 201
        second_email = unique_email()
        response = await register(client, email=second_email, name=name.upper())
    assert response.status_code == 409
    assert error_code(response) == "name_taken"
    assert await mongo_db.auth_identities.count_documents({"provider_user_id": second_email}) == 0


async def test_concurrent_registrations_for_the_same_name_create_exactly_one_account(app_client, mongo_db):
    name = unique_name()
    async with app_client() as client:
        responses = await asyncio.gather(*(register(client, name=name) for _ in range(5)))
    statuses = sorted(r.status_code for r in responses)
    assert statuses == [201, 409, 409, 409, 409], [r.text for r in responses]
    assert all(error_code(r) == "name_taken" for r in responses if r.status_code == 409)
    assert await mongo_db.player_data_profile.count_documents({"game_user_name_lower": name.lower()}) == 1


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"password": "Zq9!xw"}, "password"),
        ({"password": "x" * 129}, "password"),
        ({"game_user_name": "ab"}, "game_user_name"),
        ({"game_user_name": "has space"}, "game_user_name"),
        ({"game_user_name": "ÜnicodeName"}, "game_user_name"),
        ({"email": "not-an-email"}, "email"),
        ({"account_status": "admin"}, "account_status"),  # unknown fields are rejected
    ],
)
async def test_register_validation(app_client, overrides, field):
    async with app_client() as client:
        response = await register(client, **overrides)
    assert response.status_code == 422
    assert error_code(response) == "validation_error"
    assert any(d["loc"][-1] == field for d in response.json()["error"]["details"])
    assert "Zq9!xw" not in response.text and "x" * 129 not in response.text  # values never echoed


# --- login -----------------------------------------------------------------------------------


async def test_login_succeeds_with_any_email_case(app_client):
    email = unique_email()
    async with app_client() as client:
        await register(client, email=email)
        response = await login(client, email.upper())
        assert response.status_code == 200
        me = await client.get("/v1/auth/me", headers=bearer(response.json()["access_token"]))
    assert me.status_code == 200


async def test_wrong_password_and_unknown_email_are_indistinguishable(app_client):
    email = unique_email()
    async with app_client() as client:
        await register(client, email=email)
        wrong_password = await login(client, email, "wrong-password-123")
        unknown_email = await login(client, unique_email())
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["error"]["code"] == unknown_email.json()["error"]["code"] == "invalid_credentials"
    assert wrong_password.json()["error"]["message"] == unknown_email.json()["error"]["message"]
    assert wrong_password.headers["WWW-Authenticate"] == "Bearer"


async def test_banned_account_cannot_log_in_or_use_existing_tokens(app_client, mongo_db):
    email = unique_email()
    async with app_client() as client:
        tokens = (await register(client, email=email)).json()
        until = utc_now() + timedelta(days=1)
        await mongo_db.user_data.update_one(
            {"game_user_id": uuid.UUID(tokens["game_user_id"])},
            {"$set": {"account_status": "banned", "ban": {"reason": "cheating", "until": until}}},
        )
        login_response = await login(client, email)
        me = await client.get("/v1/auth/me", headers=bearer(tokens["access_token"]))
        refresh_response = await refresh(client, tokens["refresh_token"])
    for response in (login_response, me, refresh_response):
        assert response.status_code == 403
        assert error_code(response) == "account_banned"
    assert login_response.json()["error"]["details"]["reason"] == "cheating"


async def test_expired_ban_no_longer_blocks_login(app_client, mongo_db):
    email = unique_email()
    async with app_client() as client:
        tokens = (await register(client, email=email)).json()
        await mongo_db.user_data.update_one(
            {"game_user_id": uuid.UUID(tokens["game_user_id"])},
            {"$set": {"account_status": "banned", "ban": {"reason": "x", "until": utc_now() - timedelta(minutes=1)}}},
        )
        response = await login(client, email)
    assert response.status_code == 200


async def test_banned_status_is_not_revealed_without_the_correct_password(app_client, mongo_db):
    email = unique_email()
    async with app_client() as client:
        tokens = (await register(client, email=email)).json()
        await mongo_db.user_data.update_one(
            {"game_user_id": uuid.UUID(tokens["game_user_id"])}, {"$set": {"account_status": "banned", "ban": None}}
        )
        response = await login(client, email, "wrong-password-123")
    assert response.status_code == 401
    assert error_code(response) == "invalid_credentials"


# --- refresh -------------------------------------------------------------------------------


async def test_refresh_rotates_tokens(app_client):
    async with app_client() as client:
        first = (await register(client)).json()
        response = await refresh(client, first["refresh_token"])
        assert response.status_code == 200
        second = response.json()
        assert second["refresh_token"] != first["refresh_token"]
        assert second["game_user_id"] == first["game_user_id"]
        me = await client.get("/v1/auth/me", headers=bearer(second["access_token"]))
        third = await refresh(client, second["refresh_token"])
    assert me.status_code == 200
    assert third.status_code == 200


async def test_reusing_a_rotated_refresh_token_ends_the_whole_login(app_client):
    async with app_client() as client:
        first = (await register(client)).json()
        second = (await refresh(client, first["refresh_token"])).json()

        replay = await refresh(client, first["refresh_token"])  # attacker replays the stolen old token
        assert replay.status_code == 401
        assert error_code(replay) == "refresh_token_reused"

        # The legitimate client's newer tokens are now dead too.
        newer_refresh = await refresh(client, second["refresh_token"])
        newer_access = await client.get("/v1/auth/me", headers=bearer(second["access_token"]))
    assert error_code(newer_refresh) == "session_revoked"
    assert newer_access.status_code == 401 and error_code(newer_access) == "session_revoked"


async def test_concurrent_refreshes_with_one_token_succeed_at_most_once(app_client):
    async with app_client() as client:
        tokens = (await register(client)).json()
        responses = await asyncio.gather(*(refresh(client, tokens["refresh_token"]) for _ in range(3)))
    successes = [r for r in responses if r.status_code == 200]
    assert len(successes) <= 1, [r.text for r in responses]
    assert all(error_code(r) in ("refresh_token_reused", "session_revoked") for r in responses if r.status_code != 200)


async def test_unknown_refresh_token_is_rejected(app_client):
    async with app_client() as client:
        response = await refresh(client, "not-a-real-token")
    assert response.status_code == 401
    assert error_code(response) == "invalid_refresh_token"


async def test_expired_refresh_token_is_rejected(app_client, mongo_db):
    async with app_client() as client:
        tokens = (await register(client)).json()
        await mongo_db.auth_sessions.update_one(
            {"token_hash": hash_refresh_token(tokens["refresh_token"])},
            {"$set": {"expires_at": utc_now() - timedelta(seconds=1)}},
        )
        response = await refresh(client, tokens["refresh_token"])
    assert response.status_code == 401
    assert error_code(response) == "refresh_token_expired"


# --- logout --------------------------------------------------------------------------------


async def test_logout_ends_the_current_login_only(app_client):
    email = unique_email()
    async with app_client() as client:
        device_a = (await register(client, email=email)).json()
        device_b = (await login(client, email)).json()

        assert (await client.post("/v1/auth/logout", headers=bearer(device_a["access_token"]))).status_code == 204

        a_access = await client.get("/v1/auth/me", headers=bearer(device_a["access_token"]))
        a_refresh = await refresh(client, device_a["refresh_token"])
        b_access = await client.get("/v1/auth/me", headers=bearer(device_b["access_token"]))
    assert error_code(a_access) == "session_revoked"
    assert error_code(a_refresh) == "session_revoked"
    assert b_access.status_code == 200


async def test_logout_all_ends_every_login(app_client):
    email = unique_email()
    async with app_client() as client:
        device_a = (await register(client, email=email)).json()
        device_b = (await login(client, email)).json()

        assert (await client.post("/v1/auth/logout-all", headers=bearer(device_b["access_token"]))).status_code == 204

        results = [
            await client.get("/v1/auth/me", headers=bearer(device_a["access_token"])),
            await client.get("/v1/auth/me", headers=bearer(device_b["access_token"])),
            await refresh(client, device_a["refresh_token"]),
            await refresh(client, device_b["refresh_token"]),
        ]
        relogin = await login(client, email)
    assert all(r.status_code == 401 and error_code(r) == "session_revoked" for r in results)
    assert relogin.status_code == 200


# --- access token checks -----------------------------------------------------------------


async def test_missing_token(app_client):
    async with app_client() as client:
        response = await client.get("/v1/auth/me")
    assert response.status_code == 401
    assert error_code(response) == "not_authenticated"
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_expired_access_token(app_client, test_settings):
    async with app_client() as client:
        tokens = (await register(client)).json()
        claims = jwt.decode(tokens["access_token"], options={"verify_signature": False})
        expired = create_access_token(
            game_user_id=uuid.UUID(claims["sub"]),
            session_id=uuid.UUID(claims["sid"]),
            session_epoch=claims["epoch"],
            settings=test_settings,
            now=utc_now() - timedelta(hours=1),
        )
        response = await client.get("/v1/auth/me", headers=bearer(expired))
    assert response.status_code == 401
    assert error_code(response) == "token_expired"


@pytest.mark.parametrize("attack", ["wrong_key", "alg_none", "tampered_payload", "garbage"])
async def test_forged_access_tokens_are_rejected(app_client, attack):
    async with app_client() as client:
        tokens = (await register(client)).json()
        claims = jwt.decode(tokens["access_token"], options={"verify_signature": False})
        if attack == "wrong_key":
            token = jwt.encode(claims, "another-secret-that-is-long-enough-123456", algorithm="HS256")
        elif attack == "alg_none":
            token = jwt.encode(claims, None, algorithm="none")
        elif attack == "tampered_payload":
            header, _, signature = tokens["access_token"].split(".")
            other = jwt.encode({**claims, "sub": str(uuid.uuid7())}, "x" * 32, algorithm="HS256")
            token = ".".join([header, other.split(".")[1], signature])
        else:
            token = "garbage"
        response = await client.get("/v1/auth/me", headers=bearer(token))
    assert response.status_code == 401
    assert error_code(response) == "invalid_token"


async def test_refresh_endpoint_does_not_accept_access_tokens_as_refresh_tokens(app_client):
    async with app_client() as client:
        tokens = (await register(client)).json()
        response = await refresh(client, tokens["access_token"])
    assert response.status_code == 401
    assert error_code(response) == "invalid_refresh_token"
