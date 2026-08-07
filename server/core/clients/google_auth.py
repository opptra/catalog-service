from typing import Any

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token


class GoogleAuthClient:
    """Verifies Google ID tokens against a configured OAuth client ID."""

    def __init__(self, client_id: str) -> None:
        self.client_id = client_id
        self._request = google_requests.Request()

    def verify_id_token(self, token: str) -> dict[str, Any]:
        return id_token.verify_oauth2_token(token, self._request, self.client_id)
