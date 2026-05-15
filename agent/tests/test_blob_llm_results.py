"""Testes para llm_results (blob) com settings isolados."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from alert_agent.infra.blob import llm_results


@pytest.mark.asyncio
async def test_save_analysis_markdown_if_enabled_noop():
    with patch.object(
        llm_results,
        "settings",
        SimpleNamespace(debug_llm_result=False, blob_storage=""),
    ):
        await llm_results.save_analysis_markdown_if_enabled("x")


@pytest.mark.asyncio
async def test_save_analysis_calls_sync_when_enabled():
    with patch.object(
        llm_results,
        "settings",
        SimpleNamespace(
            debug_llm_result=True, blob_storage="AccountName=x;AccountKey=y;"
        ),
    ):
        with patch.object(llm_results, "save_analysis_markdown_sync") as sync:
            await llm_results.save_analysis_markdown_if_enabled("body")
            sync.assert_called_once_with("body")


def test_account_name_and_key_from_connection_string():
    with patch.object(
        llm_results,
        "settings",
        SimpleNamespace(blob_storage="AccountName=acct;AccountKey=secretkey;"),
    ):
        assert llm_results._account_name_and_key_for_sas() == ("acct", "secretkey")


def test_account_name_and_key_incomplete_returns_none():
    with patch.object(
        llm_results,
        "settings",
        SimpleNamespace(blob_storage="DefaultEndpointsProtocol=http;AccountName=only;"),
    ):
        assert llm_results._account_name_and_key_for_sas() is None


@pytest.mark.asyncio
async def test_list_llm_folder_download_urls_empty_when_no_blob():
    with patch.object(llm_results, "settings", SimpleNamespace(blob_storage="")):
        assert await llm_results.list_llm_folder_download_urls() == []
