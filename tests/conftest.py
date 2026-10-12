import os
import shutil
import tempfile
import pytest
from aethelnet_node import database


@pytest.fixture(scope="session", autouse=True)
def isolate_session_database():
    """Ensure the entire test suite defaults to an isolated temporary database, protecting local lgnn.db."""
    tmp_dir = tempfile.mkdtemp()
    session_db = os.path.join(tmp_dir, "session_test_lgnn.db")
    orig_env = os.environ.get("AETHELNET_DB_PATH")
    orig_db_path = database.DB_PATH

    os.environ["AETHELNET_DB_PATH"] = session_db
    database.DB_PATH = session_db
    database.init_db()

    yield session_db

    if orig_env is not None:
        os.environ["AETHELNET_DB_PATH"] = orig_env
    else:
        os.environ.pop("AETHELNET_DB_PATH", None)
    database.DB_PATH = orig_db_path
    shutil.rmtree(tmp_dir, ignore_errors=True)
