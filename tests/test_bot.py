from app.config import Settings
from bot.main import backend_headers


def test_backend_api_key_header_is_optional():
    assert backend_headers(Settings(api_access_key="")) == {}
    assert backend_headers(Settings(api_access_key="beta-secret")) == {
        "X-API-Key": "beta-secret"
    }
