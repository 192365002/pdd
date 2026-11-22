"""
DeepVerify — Comprehensive Automated Test Suite (TC01 to TC15)
Covers Application Lifecycle, Authentication, Image/Audio Processing,
Database Persistence, Security, and File Validation.
"""
import io
import time
import pytest
from unittest.mock import patch
from PIL import Image
from tests.conftest import record_result
import models


# Helper function to generate valid PNG image bytes using PIL
def create_test_png():
    img = Image.new("RGB", (64, 64), color=(30, 144, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


# Helper function to generate standard valid PCM 16-bit 16kHz mono WAV audio bytes
def create_test_wav():
    # 44-byte standard PCM 16-bit 16kHz mono WAV header
    return (
        b'RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00'
        b'\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00'
    )


# ══════════════════════════════════════════════════════════════════════════════
# TC01: Application Startup
# ══════════════════════════════════════════════════════════════════════════════
def test_tc01_application_startup(app_instance):
    """TC01: Verify that the Flask application initializes successfully with valid configurations."""
    test_id = "TC01"
    name = "Application startup"
    expected = "Application starts successfully with valid configurations"
    try:
        assert app_instance is not None
        assert app_instance.name == "app"
        assert "UPLOAD_FOLDER" in app_instance.config
        assert app_instance.config["MAX_CONTENT_LENGTH"] >= 1024 * 1024
        actual = f"Flask app initialized successfully ({app_instance.name})"
        record_result(test_id, name, expected, actual, "PASS")
    except Exception as e:
        record_result(test_id, name, expected, f"Startup failed: {e}", "FAIL")
        raise


# ══════════════════════════════════════════════════════════════════════════════
# TC02: Home Page Loading
# ══════════════════════════════════════════════════════════════════════════════
def test_tc02_home_page_loading(client):
    """TC02: Verify that the home page loads and serves the web frontend (HTTP 200)."""
    test_id = "TC02"
    name = "Home page loading"
    expected = "HTTP 200 with HTML frontend content"
    try:
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.content_type
        actual = f"HTTP {response.status_code} - Frontend index served successfully"
        record_result(test_id, name, expected, actual, "PASS")
    except Exception as e:
        record_result(test_id, name, expected, f"Failed: {e}", "FAIL")
        raise


# ══════════════════════════════════════════════════════════════════════════════
# TC03: Health API
# ══════════════════════════════════════════════════════════════════════════════
def test_tc03_health_api(client):
    """TC03: Verify that the health check API returns active server and database status."""
    test_id = "TC03"
    name = "Health API"
    expected = "HTTP 200 with status=active and database=connected"
    try:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.get_json()
        assert data.get("status") == "active"
        assert data.get("database") == "connected"
        actual = f"HTTP {response.status_code} - status={data.get('status')}, db={data.get('database')}"
        record_result(test_id, name, expected, actual, "PASS")
    except Exception as e:
        record_result(test_id, name, expected, f"Failed: {e}", "FAIL")
        raise


# ══════════════════════════════════════════════════════════════════════════════
# TC04: User Registration
# ══════════════════════════════════════════════════════════════════════════════
def test_tc04_user_registration(client):
    """TC04: Verify that a new user can successfully register with valid details."""
    test_id = "TC04"
    name = "User registration"
    expected = "HTTP 201 with user creation confirmation"
    unique_email = f"qa_reg_{int(time.time() * 1000)}@socialshield.ai"
    try:
        payload = {
            "email": unique_email,
            "password": "SecurePassword123!",
            "name": "QA Register Tester",
            "role": "user"
        }
        response = client.post("/api/auth/register", json=payload)
        assert response.status_code == 201
        data = response.get_json()
        assert "user_id" in data or "token" in data or "message" in data
        assert "Registration successful" in data.get("message", "") or "user_id" in data
        actual = f"HTTP {response.status_code} - User registered successfully: {data.get('message', 'User created')}"
        record_result(test_id, name, expected, actual, "PASS")
    except Exception as e:
        record_result(test_id, name, expected, f"Failed: {e}", "FAIL")
        raise


# ══════════════════════════════════════════════════════════════════════════════
# TC05: User Login (Valid)
# ══════════════════════════════════════════════════════════════════════════════
def test_tc05_user_login(client):
    """TC05: Verify that user authentication succeeds with valid credentials."""
    test_id = "TC05"
    name = "User login"
    expected = "HTTP 200 with valid JWT authorization token"
    email = f"qa_login_{int(time.time() * 1000)}@socialshield.ai"
    password = "StrongPassword789!"
    try:
        # Pre-register user
        reg_res = client.post("/api/auth/register", json={
            "email": email,
            "password": password,
            "name": "QA Login Tester"
        })
        assert reg_res.status_code == 201

        # Perform login
        response = client.post("/api/auth/login", json={
            "email": email,
            "password": password
        })
        assert response.status_code == 200
        data = response.get_json()
        assert "token" in data
        actual = f"HTTP {response.status_code} - Authentication successful, token generated"
        record_result(test_id, name, expected, actual, "PASS")
    except Exception as e:
        record_result(test_id, name, expected, f"Failed: {e}", "FAIL")
        raise


# ══════════════════════════════════════════════════════════════════════════════
# TC06: Invalid Login
# ══════════════════════════════════════════════════════════════════════════════
def test_tc06_invalid_login(client):
    """TC06: Verify that authentication is rejected when invalid credentials are provided."""
    test_id = "TC06"
    name = "Invalid login"
    expected = "HTTP 401 Unauthorized rejection"
    try:
        response = client.post("/api/auth/login", json={
            "email": "nonexistent_hacker@socialshield.ai",
            "password": "WrongPassword999!"
        })
        assert response.status_code == 401
        data = response.get_json()
        assert "Invalid" in data.get("message", "") or "error" in data
        actual = f"HTTP {response.status_code} - {data.get('message', 'Unauthorized')}"
        record_result(test_id, name, expected, actual, "PASS")
    except Exception as e:
        record_result(test_id, name, expected, f"Failed: {e}", "FAIL")
        raise


# ══════════════════════════════════════════════════════════════════════════════
# TC07: Image Upload
# ══════════════════════════════════════════════════════════════════════════════
def test_tc07_image_upload(client):
    """TC07: Verify that a valid image file is accepted and processed through the detection pipeline."""
    test_id = "TC07"
    name = "Image upload"
    expected = "HTTP 200 with detection verdict and scanId"
    try:
        # Mock vision model output for fast, deterministic, offline CI execution
        mock_result = {
            "status": "success",
            "classification": "ORIGINAL IMAGE",
            "category": "likely_original",
            "verdict": "ORIGINAL IMAGE",
            "risk_level": "Safe",
            "model_score": 0.08,
            "confidence": 92.0,
            "status_text": "ORIGINAL IMAGE",
            "explanation": "Authentic camera sensor characteristics verified.",
            "model_name": "DeepVerify Vision Transformer Pipeline",
            "model_version": "3.4.0",
            "processing_time_ms": 45.2,
            "forensic_metrics": {"resolution": "64x64", "noise_std": 2.1}
        }
        with patch("image_authenticity_detector.classify_image_authenticity", return_value=mock_result):
            img_bytes = create_test_png()
            data = {
                "image": (io.BytesIO(img_bytes), "sample_test.png")
            }
            response = client.post("/api/scans/image", data=data, content_type="multipart/form-data")
            assert response.status_code == 200
            res_data = response.get_json()
            assert "verdict" in res_data
            assert "scanId" in res_data
            actual = f"HTTP {response.status_code} - Verdict: {res_data.get('verdict')}, scanId: {res_data.get('scanId')}"
            record_result(test_id, name, expected, actual, "PASS")
    except Exception as e:
        record_result(test_id, name, expected, f"Failed: {e}", "FAIL")
        raise


# ══════════════════════════════════════════════════════════════════════════════
# TC08: Audio Upload
# ══════════════════════════════════════════════════════════════════════════════
def test_tc08_audio_upload(client):
    """TC08: Verify that a valid audio file is accepted and analyzed by the voice engine."""
    test_id = "TC08"
    name = "Audio upload"
    expected = "HTTP 200 with voice analysis verdict and scanId"
    try:
        # Mock audio engine output for fast, deterministic CI execution
        mock_audio_result = {
            "verdict": "ORIGINAL HUMAN VOICE",
            "confidence": 96.5,
            "risk_level": "Safe",
            "score": 3.5,
            "explanation": "Natural human voice pitch patterns and vocal tract dynamics verified.",
            "details": {"duration_s": 1.2, "framerate": 16000}
        }
        with patch("ai_engine.analyze_audio_voice_clone", return_value=mock_audio_result):
            audio_bytes = create_test_wav()
            data = {
                "audio": (io.BytesIO(audio_bytes), "voice_sample.wav")
            }
            response = client.post("/api/scans/audio", data=data, content_type="multipart/form-data")
            assert response.status_code == 200
            res_data = response.get_json()
            assert "verdict" in res_data
            assert "scanId" in res_data
            actual = f"HTTP {response.status_code} - Verdict: {res_data.get('verdict')}, scanId: {res_data.get('scanId')}"
            record_result(test_id, name, expected, actual, "PASS")
    except Exception as e:
        record_result(test_id, name, expected, f"Failed: {e}", "FAIL")
        raise


# ══════════════════════════════════════════════════════════════════════════════
# TC09: Unsupported File Upload
# ══════════════════════════════════════════════════════════════════════════════
def test_tc09_unsupported_file_upload(client):
    """TC09: Verify that unsupported file types (e.g., .exe, .bin) are rejected with HTTP 400."""
    test_id = "TC09"
    name = "Unsupported file upload"
    expected = "HTTP 400 error indicating unsupported file format"
    try:
        fake_binary = io.BytesIO(b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00")
        data = {
            "image": (fake_binary, "suspicious_payload.exe")
        }
        response = client.post("/api/scans/image", data=data, content_type="multipart/form-data")
        assert response.status_code == 400
        res_data = response.get_json()
        assert res_data.get("status") == "error"
        assert "Unsupported" in res_data.get("error", "")
        actual = f"HTTP {response.status_code} - {res_data.get('error')}"
        record_result(test_id, name, expected, actual, "PASS")
    except Exception as e:
        record_result(test_id, name, expected, f"Failed: {e}", "FAIL")
        raise


# ══════════════════════════════════════════════════════════════════════════════
# TC10: Empty File Upload
# ══════════════════════════════════════════════════════════════════════════════
def test_tc10_empty_file_upload(client):
    """TC10: Verify that an empty upload request is rejected with validation error."""
    test_id = "TC10"
    name = "Empty file upload"
    expected = "HTTP 400 validation error"
    try:
        response = client.post("/api/scans/image", data={}, content_type="multipart/form-data")
        assert response.status_code == 400
        res_data = response.get_json()
        assert "verdict" in res_data or "error" in res_data or "message" in res_data
        actual = f"HTTP {response.status_code} - Validation error returned for empty payload"
        record_result(test_id, name, expected, actual, "PASS")
    except Exception as e:
        record_result(test_id, name, expected, f"Failed: {e}", "FAIL")
        raise


# ══════════════════════════════════════════════════════════════════════════════
# TC11: Database Connection
# ══════════════════════════════════════════════════════════════════════════════
def test_tc11_database_connection():
    """TC11: Verify that database connectivity is operational and collections can be queried."""
    test_id = "TC11"
    name = "Database connection"
    expected = "Database instance is connected and responds to queries"
    try:
        db = models.get_db()
        assert db is not None
        # Verify collection access and count operations
        user_count = db["users"].count_documents({})
        scan_count = db["scans"].count_documents({})
        assert isinstance(user_count, int)
        assert isinstance(scan_count, int)
        actual = f"Database connected successfully (users: {user_count}, scans: {scan_count})"
        record_result(test_id, name, expected, actual, "PASS")
    except Exception as e:
        record_result(test_id, name, expected, f"Failed: {e}", "FAIL")
        raise


# ══════════════════════════════════════════════════════════════════════════════
# TC12: Scan History
# ══════════════════════════════════════════════════════════════════════════════
def test_tc12_scan_history(client):
    """TC12: Verify that the scan history endpoint retrieves past scan records."""
    test_id = "TC12"
    name = "Scan history"
    expected = "HTTP 200 with list of scans"
    try:
        response = client.get("/api/scans/history?email=aadarshavula2005@gmail.com")
        assert response.status_code == 200
        data = response.get_json()
        assert "scans" in data
        assert isinstance(data["scans"], list)
        actual = f"HTTP {response.status_code} - Retrieved {len(data['scans'])} scan records"
        record_result(test_id, name, expected, actual, "PASS")
    except Exception as e:
        record_result(test_id, name, expected, f"Failed: {e}", "FAIL")
        raise


# ══════════════════════════════════════════════════════════════════════════════
# TC13: Invalid API Endpoint
# ══════════════════════════════════════════════════════════════════════════════
def test_tc13_invalid_api_endpoint(client):
    """TC13: Verify that requests to non-existent API routes return HTTP 404 Not Found."""
    test_id = "TC13"
    name = "Invalid API endpoint"
    expected = "HTTP 404 Not Found"
    try:
        response = client.get("/api/v1/invalid-route-does-not-exist")
        assert response.status_code == 404
        actual = f"HTTP {response.status_code} - Non-existent route correctly rejected with 404"
        record_result(test_id, name, expected, actual, "PASS")
    except Exception as e:
        record_result(test_id, name, expected, f"Failed: {e}", "FAIL")
        raise


# ══════════════════════════════════════════════════════════════════════════════
# TC14: Authentication Security
# ══════════════════════════════════════════════════════════════════════════════
def test_tc14_authentication_security(client):
    """TC14: Verify that protected API endpoints reject unauthenticated and unauthorized requests."""
    test_id = "TC14"
    name = "Authentication security"
    expected = "HTTP 401/403 for missing tokens and unauthorized actions"
    try:
        # 1. Access protected user profile without token -> 401
        res_unauth = client.get("/api/auth/me")
        assert res_unauth.status_code == 401

        # 2. Access administrator user management with non-admin identity -> 403
        res_forbidden = client.get("/api/admin/users", headers={
            "X-User-Email": "regular_user@socialshield.ai"
        })
        assert res_forbidden.status_code == 403

        actual = f"HTTP 401 on missing token, HTTP 403 on non-admin access correctly enforced"
        record_result(test_id, name, expected, actual, "PASS")
    except Exception as e:
        record_result(test_id, name, expected, f"Failed: {e}", "FAIL")
        raise


# ══════════════════════════════════════════════════════════════════════════════
# TC15: File Size Validation
# ══════════════════════════════════════════════════════════════════════════════
def test_tc15_file_size_validation(client, app_instance):
    """TC15: Verify that files exceeding the maximum allowed upload size are rejected with HTTP 413."""
    test_id = "TC15"
    name = "File size validation"
    expected = "HTTP 413 Payload Too Large when file size exceeds MAX_CONTENT_LENGTH"
    original_max = app_instance.config.get("MAX_CONTENT_LENGTH")
    try:
        # Temporarily set limit to 50 KB for test
        app_instance.config["MAX_CONTENT_LENGTH"] = 50 * 1024
        oversized_data = b"0" * (100 * 1024)  # 100 KB payload
        data = {
            "image": (io.BytesIO(oversized_data), "oversized_image.png")
        }
        response = client.post("/api/scans/image", data=data, content_type="multipart/form-data")
        assert response.status_code == 413
        actual = f"HTTP {response.status_code} - Oversized payload rejected as expected"
        record_result(test_id, name, expected, actual, "PASS")
    except Exception as e:
        record_result(test_id, name, expected, f"Failed: {e}", "FAIL")
        raise
    finally:
        # Restore original MAX_CONTENT_LENGTH
        app_instance.config["MAX_CONTENT_LENGTH"] = original_max
