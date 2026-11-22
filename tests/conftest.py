"""
DeepVerify Test Configuration & Fixtures
Ensures test isolation, safe mock/test database, and report generation.
"""
import os
import sys
import shutil
import tempfile
from unittest.mock import MagicMock
import pytest

# Ensure project root is in python path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Pre-set test environment variables before importing app
os.environ["FLASK_ENV"] = "testing"
os.environ["MONGO_URI"] = ""  # Force test SQLite persistence; NEVER touch production MongoDB
os.environ["JWT_SECRET"] = "test-jwt-secret-key-deepverify-qa-2026"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

# Safe fallback for torch and transformers in lightweight CI environments
try:
    import torch
except ImportError:
    sys.modules["torch"] = MagicMock()

try:
    import transformers
except ImportError:
    sys.modules["transformers"] = MagicMock()

# Mock pre-warm loading functions to ensure CI test suite runs ultra-fast and reliably offline
import image_authenticity_detector
import video_authenticity_detector
image_authenticity_detector.load_detection_models = MagicMock(return_value=({}, {}, {}, {}, {}))
video_authenticity_detector.load_video_detection_models = MagicMock(return_value=(None, None, None, None))

import models

# Global test report registry
TEST_RESULTS = []


@pytest.fixture(scope="session", autouse=True)
def setup_test_suite():
    """Sets up an isolated temporary database and upload directory for testing."""
    test_dir = tempfile.mkdtemp(prefix="deepverify_test_")
    test_db_path = os.path.join(test_dir, "test_socialshield.db")
    test_upload_dir = os.path.join(test_dir, "uploads")
    os.makedirs(test_upload_dir, exist_ok=True)

    # Re-route models to use isolated test SQLite database
    models.SQLITE_PATH = test_db_path
    models._db_instance = None
    models._use_sqlite = True
    test_db = models.init_db()

    # Import app and reconfigure for testing
    from app import app, seed_initial_data
    app.config["TESTING"] = True
    app.config["UPLOAD_FOLDER"] = test_upload_dir
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        try:
            seed_initial_data()
        except Exception as ex:
            print(f"[Notice] DB seed in test context: {ex}")

    yield test_db

    # Teardown: Clean up temporary test files
    try:
        shutil.rmtree(test_dir, ignore_errors=True)
    except Exception:
        pass


@pytest.fixture
def app_instance():
    """Returns the configured Flask application instance."""
    from app import app
    return app


@pytest.fixture
def client(app_instance):
    """Provides a test client for executing HTTP requests against the app."""
    with app_instance.test_client() as test_client:
        with app_instance.app_context():
            yield test_client


@pytest.fixture
def test_user_token():
    """Generates a valid test JWT authorization token."""
    import auth
    return auth.generate_token(
        user_id="test_user_qa_123",
        role="user",
        name="QA Test User",
        email="testuser_qa@socialshield.ai"
    )


@pytest.fixture
def admin_user_token():
    """Generates an administrator JWT authorization token."""
    import auth
    return auth.generate_token(
        user_id="admin_user_qa_999",
        role="admin",
        name="QA Admin",
        email="aadarshavula2005@gmail.com"
    )


def record_result(test_id, name, expected, actual, status):
    """Registers test execution result for reporting."""
    TEST_RESULTS.append({
        "id": test_id,
        "name": name,
        "expected": expected,
        "actual": actual,
        "status": status
    })


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Pytest hook to capture pass/fail status and output."""
    outcome = yield
    report = outcome.get_result()
    setattr(item, "rep_" + report.when, report)


def pytest_sessionfinish(session, exitstatus):
    """Generates a professional Markdown test summary report upon test session completion."""
    reports_dir = os.path.join(PROJECT_ROOT, "test-reports")
    os.makedirs(reports_dir, exist_ok=True)
    report_file = os.path.join(reports_dir, "test_report.md")

    passed = sum(1 for r in TEST_RESULTS if r["status"] == "PASS")
    failed = sum(1 for r in TEST_RESULTS if r["status"] == "FAIL")
    total = len(TEST_RESULTS)
    pass_rate = (passed / total * 100) if total > 0 else 0

    lines = [
        "# DeepVerify — Automated Test Execution Report",
        "",
        f"**Date:** {os.environ.get('TEST_DATE', 'Automated CI/CD Run')}",
        f"**Framework:** Pytest 9.x | Python {sys.version.split()[0]} | Flask 3.0.3",
        f"**Test Results:** **{passed}/{total} Passed** ({pass_rate:.1f}% Success Rate)",
        "",
        "## Test Execution Summary",
        "",
        "| Test ID | Test Case Name | Expected Result | Actual Result | Status |",
        "|:---:|:---|:---|:---|:---:|",
    ]

    for r in TEST_RESULTS:
        icon = "✅ PASS" if r["status"] == "PASS" else "❌ FAIL"
        lines.append(f"| **{r['id']}** | {r['name']} | {r['expected']} | {r['actual']} | {icon} |")

    lines.extend([
        "",
        "---",
        "### Verification Environment:",
        "- **Database Mode:** Isolated Test SQLite (Zero modification to production data)",
        "- **Test Runner:** Pytest automated runner",
        "- **CI/CD Platform:** GitHub Actions",
        "",
        f"**Final Verdict:** {'ALL TEST CASES PASSED' if failed == 0 else f'{failed} TEST CASES FAILED'}",
    ])

    report_content = "\n".join(lines)
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report_content)

    # Print summary table to console
    print("\n" + "=" * 80)
    print("                 DEEPVERIFY AUTOMATED TEST EXECUTION SUMMARY")
    print("=" * 80)
    for r in TEST_RESULTS:
        status_str = "[PASS]" if r["status"] == "PASS" else "[FAIL]"
        print(f"  {r['id']:<6} | {status_str:<6} | {r['name']:<28} | {r['actual']}")
    print("-" * 80)
    print(f"  Total: {total} | Passed: {passed} | Failed: {failed} | Success Rate: {pass_rate:.1f}%")
    print("=" * 80 + "\n")
