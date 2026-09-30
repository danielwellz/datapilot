from flask.testing import FlaskClient


def test_health_returns_ok_without_touching_dependencies(client: FlaskClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}
