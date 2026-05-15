"""Upload e listagem de resultados LLM no Azure Blob Storage (incl. Azurite)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from azure.core.credentials import AzureNamedKeyCredential
from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    ContentSettings,
    generate_blob_sas,
)

from alert_agent.config import settings

logger = logging.getLogger(__name__)

# Container e prefixo virtual "llm_results/"
CONTAINER_NAME = "weather-agent"
BLOB_FOLDER_PREFIX = "llm_results/"

# Chave da conta de desenvolvimento (Azurite / devstoreaccount1)
_AZURITE_DEV_ACCOUNT_KEY = (
    "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/"
    "K1SZFPTOtr/KBHBeksoGMGw=="
)


def _blob_service_client() -> BlobServiceClient | None:
    raw = (settings.blob_storage or "").strip()
    if not raw:
        return None
    if raw.startswith("DefaultEndpointsProtocol=") or "AccountKey=" in raw:
        return BlobServiceClient.from_connection_string(raw)
    account_url = raw.rstrip("/")
    parsed = urlparse(account_url)
    path = (parsed.path or "").strip("/")
    account_name = path.rsplit("/", 1)[-1] if path else "devstoreaccount1"
    key = _AZURITE_DEV_ACCOUNT_KEY
    return BlobServiceClient(
        account_url=account_url,
        credential=AzureNamedKeyCredential(account_name, key),
    )


def _account_name_and_key_for_sas() -> tuple[str, str] | None:
    raw = (settings.blob_storage or "").strip()
    if not raw:
        return None
    if raw.startswith("DefaultEndpointsProtocol=") or "AccountKey=" in raw:
        parts: dict[str, str] = {}
        for part in raw.split(";"):
            part = part.strip()
            if not part:
                continue
            k, _, v = part.partition("=")
            parts[k] = v
        name = parts.get("AccountName")
        key = parts.get("AccountKey")
        if name and key:
            return name, key
        return None
    parsed = urlparse(raw.rstrip("/"))
    path = (parsed.path or "").strip("/")
    account_name = path.rsplit("/", 1)[-1] if path else "devstoreaccount1"
    return account_name, _AZURITE_DEV_ACCOUNT_KEY


def ensure_llm_results_storage_sync() -> None:
    """Garante container e prefixo virtual llm_results/ (marcador .keep)."""
    client = _blob_service_client()
    if client is None:
        return
    try:
        cc = client.get_container_client(CONTAINER_NAME)
        if not cc.exists():
            cc.create_container()
        keep = f"{BLOB_FOLDER_PREFIX}.keep"
        bc = cc.get_blob_client(keep)
        if not bc.exists():
            bc.upload_blob(b"", overwrite=True)
    except Exception as e:
        logger.warning(
            "Could not init blob storage llm_results folder",
            extra={"error": str(e), "error_class": type(e).__name__},
        )


def save_analysis_markdown_sync(content: str) -> None:
    ensure_llm_results_storage_sync()
    client = _blob_service_client()
    if client is None:
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    blob_name = f"{BLOB_FOLDER_PREFIX}{ts}-analisys.md"
    blob = client.get_blob_client(container=CONTAINER_NAME, blob=blob_name)
    blob.upload_blob(
        (content or "").encode("utf-8"),
        overwrite=True,
        content_settings=ContentSettings(content_type="text/markdown; charset=utf-8"),
    )


async def save_analysis_markdown_if_enabled(content: str) -> None:
    if not settings.debug_llm_result or not (settings.blob_storage or "").strip():
        return
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, save_analysis_markdown_sync, content)
    except Exception as e:
        logger.warning(
            "Failed to save LLM analysis to blob",
            extra={"error": str(e), "error_class": type(e).__name__},
        )


def list_llm_folder_download_urls_sync() -> list[dict[str, str]]:
    """Lista blobs em llm_results/ (pasta virtual no container) com SAS de leitura."""
    client = _blob_service_client()
    if client is None:
        return []
    creds = _account_name_and_key_for_sas()
    if not creds:
        return []
    account_name, account_key = creds
    container = client.get_container_client(CONTAINER_NAME)
    if not container.exists():
        return []
    expires_on = datetime.now(timezone.utc) + timedelta(hours=1)
    out: list[dict[str, str]] = []
    for blob in container.list_blobs(name_starts_with=BLOB_FOLDER_PREFIX):
        name = blob.name
        if name == f"{BLOB_FOLDER_PREFIX}.keep":
            continue
        sas = generate_blob_sas(
            account_name=account_name,
            container_name=CONTAINER_NAME,
            blob_name=name,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=expires_on,
        )
        base = container.get_blob_client(name).url
        url = f"{base}?{sas}"
        out.append({"path": name, "download_url": url})
    return out


async def list_llm_folder_download_urls() -> list[dict[str, str]]:
    if not (settings.blob_storage or "").strip():
        return []
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, list_llm_folder_download_urls_sync)
