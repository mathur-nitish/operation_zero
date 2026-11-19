import uuid
from datetime import UTC

from pydantic import BaseModel, SecretStr

from app.core.errors import AppError
from app.core.ids import new_id, utc_now
from app.core.indexes import IndexRegistry
from app.main import create_app


async def test_liveness(app_client):
    async with app_client() as client:
        response = await client.get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {}}
    assert response.headers["X-Request-ID"]


async def test_readiness_ok_against_test_database(app_client):
    async with app_client() as client:
        response = await client.get("/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"mongodb": "ok"}}


async def test_readiness_reports_503_when_mongodb_is_unreachable(app_client, test_settings):
    unreachable = test_settings.model_copy(
        update={
            "mongodb_uri": SecretStr("mongodb://127.0.0.1:1/"),
            "mongodb_timeout_ms": 300,
            "readiness_timeout_seconds": 2.0,
        }
    )
    # No indexes to create, so startup itself does not need the database.
    async with app_client(app=create_app(unreachable, IndexRegistry())) as client:
        response = await client.get("/v1/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "checks": {"mongodb": "unavailable"}}


async def test_unknown_route_uses_error_envelope(app_client):
    async with app_client() as client:
        response = await client.get("/v1/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["request_id"] == response.headers["X-Request-ID"]


async def test_wellformed_request_id_is_echoed_and_malformed_one_replaced(app_client):
    async with app_client() as client:
        echoed = await client.get("/v1/health", headers={"X-Request-ID": "unreal-client-42"})
        replaced = await client.get("/v1/health", headers={"X-Request-ID": "bad id with spaces\t!"})
    assert echoed.headers["X-Request-ID"] == "unreal-client-42"
    assert replaced.headers["X-Request-ID"] != "bad id with spaces\t!"
    assert len(replaced.headers["X-Request-ID"]) == 32


def _app_with_test_routes(test_settings):
    app = create_app(test_settings, IndexRegistry())

    class Credentials(BaseModel):
        email: str
        password: str
        age: int

    @app.post("/v1/_test/validate")
    async def validate(body: Credentials) -> dict:
        return {}

    @app.get("/v1/_test/app-error")
    async def app_error() -> dict:
        raise AppError(status_code=409, code="name_taken", message="That name is already taken.")

    @app.get("/v1/_test/crash")
    async def crash() -> dict:
        raise RuntimeError("internal detail: connection to secret-host failed")

    return app


async def test_validation_errors_do_not_echo_submitted_values(app_client, test_settings):
    async with app_client(app=_app_with_test_routes(test_settings)) as client:
        response = await client.post(
            "/v1/_test/validate", json={"email": "a@b.c", "password": "hunter2-secret", "age": "not-a-number"}
        )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"][0]["loc"] == ["body", "age"]
    assert "hunter2-secret" not in response.text
    assert "not-a-number" not in response.text


async def test_app_error_is_rendered_with_its_code(app_client, test_settings):
    async with app_client(app=_app_with_test_routes(test_settings)) as client:
        response = await client.get("/v1/_test/app-error")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "name_taken"


async def test_unhandled_error_returns_generic_500_without_internal_details(app_client, test_settings):
    async with app_client(app=_app_with_test_routes(test_settings)) as client:
        response = await client.get("/v1/_test/crash", headers={"X-Request-ID": "crash-trace-1"})
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["request_id"] == "crash-trace-1"
    assert response.headers["X-Request-ID"] == "crash-trace-1"
    assert "secret-host" not in response.text


def test_new_id_is_uuid7_and_time_ordered():
    ids = [new_id() for _ in range(100)]
    assert all(isinstance(i, uuid.UUID) and i.version == 7 for i in ids)
    assert ids == sorted(ids)


def test_utc_now_is_timezone_aware_utc():
    assert utc_now().tzinfo is UTC
