"""Unit tests for the mender_server module."""

import logging
import pytest
import requests

from pathlib import Path
from types import SimpleNamespace

from mender_docker_lifecycle_helper.utils.mender_server import call_mender_host_api


class TestCallMenderHostApi:
    """Tests for the call_mender_host_api function."""

    def test_call_with_no_pat(self, monkeypatch):
        """Test that call_mender_host_api returns None when mender_pat is not set."""
        context = SimpleNamespace(
            mender_pat=None,
            mender_host="https://hosted.mender.io",
            logger=logging.Logger("test_logger"),
        )

        result = call_mender_host_api(context, "artifacts", {})
        assert result is None

    def test_call_success(self, monkeypatch):
        """Test that call_mender_host_api returns response on success (status 201)."""

        class MockResponse:
            status_code = 201

            @property
            def request(self):
                return SimpleNamespace(
                    url="https://hosted.mender.io/api/management/v1/artifacts",
                    headers={},
                )

        def mock_post(*args, **kwargs):
            return MockResponse()

        monkeypatch.setattr(
            "mender_docker_lifecycle_helper.utils.mender_server.requests.post",
            mock_post,
        )

        context = SimpleNamespace(
            mender_pat="test-pat-token",
            mender_host="https://hosted.mender.io",
            logger=logging.Logger("test_logger"),
        )

        result = call_mender_host_api(context, "artifacts", {})
        assert result is not None
        assert result.status_code == 201

    def test_call_failure_raises_error(self, monkeypatch):
        """Test that call_mender_host_api raises HTTPError on non-201 status."""

        class MockResponse:
            status_code = 400
            text = "Bad Request"

            @property
            def request(self):
                return SimpleNamespace(
                    url="https://hosted.mender.io/api/management/v1/artifacts",
                    headers={"Authorization": "Bearer test-pat-token"},
                )

            def raise_for_status(self):
                raise requests.HTTPError(f"{self.status_code} Client Error")

        def mock_post(*args, **kwargs):
            return MockResponse()

        monkeypatch.setattr(
            "mender_docker_lifecycle_helper.utils.mender_server.requests.post",
            mock_post,
        )

        context = SimpleNamespace(
            mender_pat="test-pat-token",
            mender_host="https://hosted.mender.io",
            logger=logging.Logger("test_logger"),
        )

        with pytest.raises(requests.HTTPError):
            call_mender_host_api(context, "artifacts", {})

    def test_call_uses_correct_url_and_headers(self, monkeypatch):
        """Test that call_mender_host_api uses the correct URL and headers."""
        captured_args = {}
        captured_kwargs = {}

        class MockResponse:
            status_code = 201

            @property
            def request(self):
                return SimpleNamespace(url=self._url, headers=self._headers)

        def mock_post(*args, **kwargs):
            captured_args["url"] = args[0]
            captured_kwargs.update(kwargs)
            resp = MockResponse()
            resp._url = args[0]
            resp._headers = kwargs.get("headers", {})
            return resp

        monkeypatch.setattr(
            "mender_docker_lifecycle_helper.utils.mender_server.requests.post",
            mock_post,
        )

        context = SimpleNamespace(
            mender_pat="my-secret-pat",
            mender_host="https://custom.mender.io",
            logger=logging.Logger("test_logger"),
        )

        request_args = {
            "json": {"name": "test-artifact"},
            "timeout": 30,
        }

        call_mender_host_api(context, "artifacts", request_args)

        assert (
            captured_args["url"]
            == "https://custom.mender.io/api/management/v1/artifacts"
        )
        assert captured_kwargs["headers"]["Authorization"] == "Bearer my-secret-pat"
        assert captured_kwargs["headers"]["Accept"] == "application/json"
        assert captured_kwargs["json"] == {"name": "test-artifact"}
        assert captured_kwargs["timeout"] == 30

    def test_call_passes_through_request_args(self, monkeypatch):
        """Test that call_mender_host_api passes through all request args."""
        captured_kwargs = {}

        class MockResponse:
            status_code = 201

            @property
            def request(self):
                return SimpleNamespace(url="", headers={})

        def mock_post(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return MockResponse()

        monkeypatch.setattr(
            "mender_docker_lifecycle_helper.utils.mender_server.requests.post",
            mock_post,
        )

        context = SimpleNamespace(
            mender_pat="test-pat-token",
            mender_host="https://hosted.mender.io",
            logger=logging.Logger("test_logger"),
        )

        request_args = {
            "data": "raw data",
            "files": {"file": ("artifact.mender", b"content")},
            "auth": ("user", "pass"),
        }

        call_mender_host_api(context, "artifacts", request_args)

        assert "data" in captured_kwargs
        assert "files" in captured_kwargs
        assert "auth" in captured_kwargs
