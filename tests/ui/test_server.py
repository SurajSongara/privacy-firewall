"""Tests for the review UI server (requires the ui extra + httpx)."""

from pathlib import Path

import fitz
import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from privacy_firewall.policy import BUILTIN_POLICIES  # noqa: E402
from privacy_firewall.ui.server import create_app  # noqa: E402
from privacy_firewall.ui.session import ReviewSession  # noqa: E402


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    path = tmp_path / "doc.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 100), "PAN: AAAAA1111A", fontsize=12)
    page.insert_text((50, 140), "Email: user@example.com", fontsize=12)
    page.insert_text((50, 180), "Customer: Ramesh Kumar", fontsize=12)
    doc.save(str(path))
    doc.close()
    session = ReviewSession(path, BUILTIN_POLICIES["share-with-ai"])
    return TestClient(create_app(session))


def _wait_ready(client: TestClient, timeout: float = 30.0) -> str:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get("/api/status").json()["status"]
        if status in ("ready", "error"):
            return str(status)
        time.sleep(0.1)
    return "timeout"


class TestUnlockEndpoint:
    @pytest.fixture
    def locked_client(self, tmp_path: Path) -> TestClient:
        path = tmp_path / "locked.pdf"
        doc = fitz.open()
        doc.new_page().insert_text((50, 100), "PAN: ABCPE1234F", fontsize=12)
        doc.save(
            str(path), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="secret"
        )
        doc.close()
        session = ReviewSession(path, BUILTIN_POLICIES["share-with-ai"], lazy=True)
        from privacy_firewall.parsers.pdf_open import EncryptedPDFError

        with pytest.raises(EncryptedPDFError):
            session.run()
        return TestClient(create_app(session))

    def test_status_reports_needs_password(self, locked_client: TestClient) -> None:
        status = locked_client.get("/api/status").json()
        assert status["status"] == "error"
        assert status["needs_password"] is True

    def test_unlock_with_correct_password_becomes_ready(self, locked_client: TestClient) -> None:
        resp = locked_client.post("/api/unlock", json={"password": "secret"})
        assert resp.status_code == 200
        assert _wait_ready(locked_client) == "ready"
        plan = locked_client.get("/api/plan").json()
        assert any(e["text"] == "ABCPE1234F" for e in plan["entries"])

    def test_unlock_with_wrong_password_still_needs_password(
        self, locked_client: TestClient
    ) -> None:
        locked_client.post("/api/unlock", json={"password": "wrong"})
        assert _wait_ready(locked_client) == "error"
        assert locked_client.get("/api/status").json()["needs_password"] is True


class TestReviewServer:
    def test_index_serves_html(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert "Privacy Firewall" in response.text

    def test_plan_endpoint(self, client: TestClient) -> None:
        plan = client.get("/api/plan").json()
        assert plan["policy"] == "share-with-ai"
        assert len(plan["entries"]) >= 2
        assert plan["pages"][0]["width"] > 0

    def test_page_png(self, client: TestClient) -> None:
        response = client.get("/api/page/1")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content[:8] == b"\x89PNG\r\n\x1a\n"

    def test_page_out_of_range_404(self, client: TestClient) -> None:
        assert client.get("/api/page/99").status_code == 404

    def test_decision_round_trip(self, client: TestClient) -> None:
        entry = client.get("/api/plan").json()["entries"][0]
        response = client.post(
            "/api/decision",
            json={"detection_id": entry["detection_id"], "decision": "keep"},
        )
        assert response.status_code == 200
        updated = client.get("/api/plan").json()["entries"][0]
        assert updated["decision"] == "keep"

    def test_decision_unknown_id_404(self, client: TestClient) -> None:
        response = client.post("/api/decision", json={"detection_id": "nope", "decision": "keep"})
        assert response.status_code == 404

    def test_decision_invalid_value_422(self, client: TestClient) -> None:
        entry = client.get("/api/plan").json()["entries"][0]
        response = client.post(
            "/api/decision",
            json={"detection_id": entry["detection_id"], "decision": "maybe"},
        )
        assert response.status_code == 422

    def test_text_endpoint(self, client: TestClient) -> None:
        body = client.get("/api/text/1").json()
        assert any(w["text"] == "Ramesh" for w in body["words"])

    def test_text_out_of_range_404(self, client: TestClient) -> None:
        assert client.get("/api/text/99").status_code == 404

    def test_mark_and_remove_round_trip(self, client: TestClient) -> None:
        response = client.post("/api/mark", json={"text": "Ramesh Kumar", "label": "name"})
        assert response.status_code == 200
        body = response.json()
        assert body["added"] == 1
        assert body["skipped"] == 0
        # Marking the same text again finds the match but adds nothing.
        again = client.post("/api/mark", json={"text": "Ramesh Kumar", "label": "name"}).json()
        assert again["added"] == 0
        assert again["skipped"] == 1
        entry = body["entries"][0]
        assert entry["type"] == "NAME"
        assert entry["detector"] == "manual"
        assert entry["effective_action"] == "redact"

        plan = client.get("/api/plan").json()
        assert any(e["detection_id"] == entry["detection_id"] for e in plan["entries"])

        response = client.post("/api/remove", json={"detection_id": entry["detection_id"]})
        assert response.status_code == 200
        plan = client.get("/api/plan").json()
        assert all(e["detection_id"] != entry["detection_id"] for e in plan["entries"])

    def test_mark_blank_text_422(self, client: TestClient) -> None:
        response = client.post("/api/mark", json={"text": "   ", "label": "NAME"})
        assert response.status_code == 422

    def test_remove_non_manual_404(self, client: TestClient) -> None:
        entry = client.get("/api/plan").json()["entries"][0]
        response = client.post("/api/remove", json={"detection_id": entry["detection_id"]})
        assert response.status_code == 404

    def test_apply(self, client: TestClient, tmp_path: Path) -> None:
        out = tmp_path / "redacted.pdf"
        response = client.post("/api/apply", json={"output_path": str(out)})
        assert response.status_code == 200
        body = response.json()
        assert body["redactions"] >= 1
        assert Path(body["output_path"]).exists()
        assert Path(body["plan_path"]).exists()
        with fitz.open(out) as doc:
            text = doc[0].get_text()
        assert "*****" in text

    def test_apply_black_bar_style(self, client: TestClient, tmp_path: Path) -> None:
        out = tmp_path / "bars.pdf"
        response = client.post(
            "/api/apply", json={"output_path": str(out), "redaction_type": "black_bar"}
        )
        assert response.status_code == 200
        with fitz.open(out) as doc:
            text = doc[0].get_text()
        assert "AAAAA1111A" not in text
        assert "*****" not in text

    def test_apply_invalid_redaction_type_422(self, client: TestClient) -> None:
        response = client.post("/api/apply", json={"redaction_type": "sparkles"})
        assert response.status_code == 422

    def test_output_404_before_apply(self, client: TestClient) -> None:
        assert client.get("/api/output").status_code == 404

    def test_output_serves_redacted_pdf_after_apply(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        out = tmp_path / "redacted.pdf"
        assert client.post("/api/apply", json={"output_path": str(out)}).status_code == 200
        response = client.get("/api/output")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert "inline" in response.headers.get("content-disposition", "")
        assert response.content[:4] == b"%PDF"

    def test_status_ready(self, client: TestClient) -> None:
        assert client.get("/api/status").json() == {
            "status": "ready",
            "detail": "",
            "needs_password": False,
        }

    def test_preview_png(self, client: TestClient) -> None:
        response = client.get("/api/preview/1")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content[:8] == b"\x89PNG\r\n\x1a\n"
        assert client.get("/api/preview/99").status_code == 404

    def test_lazy_session_gates_endpoints(self, tmp_path: Path) -> None:
        path = tmp_path / "doc.pdf"
        doc = fitz.open()
        doc.new_page().insert_text((50, 100), "PAN: AAAAA1111A", fontsize=12)
        doc.save(str(path))
        doc.close()
        session = ReviewSession(path, BUILTIN_POLICIES["share-with-ai"], lazy=True)
        client = TestClient(create_app(session))

        assert client.get("/api/status").json()["status"] == "starting"
        assert client.get("/api/plan").status_code == 425
        assert client.post("/api/save", json={}).status_code == 425
        # A run that has not finished blocks rerun requests.
        session.status = "ocr"
        assert client.post("/api/rerun", json={}).status_code == 409

        session.status = "starting"
        session.run()
        assert client.get("/api/status").json()["status"] == "ready"
        assert client.get("/api/plan").status_code == 200
