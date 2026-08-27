from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_evaluate_valid_input():
    payload = {
        "question": "What is the capital of France?",
        "ai_response": "The capital of France is Paris.",
    }
    response = client.post("/evaluate", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["question"] == payload["question"]
    assert "overall_score" in body
    assert body["verdict"] in ("PASS", "PARTIAL", "FAIL")


def test_evaluate_missing_required_field():
    payload = {"question": "What is the capital of France?"}
    response = client.post("/evaluate", json=payload)
    assert response.status_code == 422  # Pydantic validation error


def test_evaluate_empty_question():
    payload = {"question": "", "ai_response": "Paris."}
    response = client.post("/evaluate", json=payload)
    assert response.status_code == 422
