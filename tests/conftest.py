"""
Shared pytest configuration.

Redirects the results database to a throw-away temp location BEFORE any
application module is imported. Without this, every router module creates
its ResultsStore at import time using the default ./data/evaluation_results.db,
so tests that call /evaluate or /evaluate/batch (even with mocked agents)
would write fake records into the same database the dashboard and PDF
report read from.

This must run at conftest import time (not inside a fixture) because
app.config.settings reads the environment when it is first imported.
"""
import atexit
import os
import shutil
import tempfile

_TEST_DB_DIR = tempfile.mkdtemp(prefix="avs_test_db_")
os.environ["RESULTS_DB_PATH"] = os.path.join(_TEST_DB_DIR, "evaluation_results_test.db")
atexit.register(lambda: shutil.rmtree(_TEST_DB_DIR, ignore_errors=True))
