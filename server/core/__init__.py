"""Shared server infra.

Load ``.env`` as soon as anything under ``core`` is imported. gRPC (via GCS /
Workflows clients) reads ``GRPC_DNS_RESOLVER`` at import time — too late if
dotenv only runs inside ``core.config`` after those clients are imported.
"""

from dotenv import load_dotenv

load_dotenv()
