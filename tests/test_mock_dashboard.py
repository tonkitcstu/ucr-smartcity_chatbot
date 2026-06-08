import asyncio
import json
import subprocess
import sys

from jose import jwt

from app.main import app
from app.utils.auth import SECRET_KEY, ALGORITHM
from app.routes.mock_dashboard import mint_dev_token


def test_mock_routes_registered_in_dev():
    # tests run with ENV unset (development), so the mock tool is available
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/mock/token" in paths
    assert "/mock" in paths


def test_mock_not_registered_in_production():
    # the safety property: a production deploy must not expose /mock at all
    code = (
        "import os; os.environ['ENV']='production';"
        "from app.main import app;"
        "paths=[getattr(r,'path',None) for r in app.routes];"
        "assert '/mock/token' not in paths;"
        "assert '/mock' not in paths;"
        "print('OK')"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr + result.stdout


def test_dev_token_is_a_valid_admin_jwt():
    resp = asyncio.run(mint_dev_token())
    token = json.loads(resp.body)["token"]
    claims = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    assert claims["role"] == "admin"
    assert claims["sub"] == "mock-admin"
