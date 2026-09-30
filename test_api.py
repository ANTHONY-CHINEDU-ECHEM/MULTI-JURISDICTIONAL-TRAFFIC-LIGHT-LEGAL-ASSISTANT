from fastapi.testclient import TestClient

from trafficlegal.api import app

client = TestClient(app)


def test_health():
    assert client.get("/health").json()["status"] == "ok"


def test_evaluation_endpoint():
    body = client.get("/crashes/CR00001/evaluation", params={"evidence": "false"}).json()
    assert body["crash_id"] == "CR00001" and body["verdict"]


def test_unknown_crash_returns_404():
    assert client.get("/crashes/CR99999/evaluation").status_code == 404


def test_sql_is_read_only():
    assert client.post("/sql", json={"sql": "DROP TABLE crash_events"}).status_code == 400
    rows = client.post("/sql", json={"sql": "SELECT COUNT(*) AS n FROM hcs_streets_export"}).json()
    assert rows[0]["n"] >= 15000


def test_ask_routes_regulatory_questions():
    body = client.post("/ask", json={"question": "What is the maximum red clearance interval?"}).json()
    assert body["route"] == "REGULATORY" and body["evidence"]
