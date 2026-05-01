"""Unit tests for the mender_server module."""

import logging
import pytest
import requests

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from mender_docker_lifecycle_helper.utils.mender_server import (
    call_mender_host_api,
    get_deployment_status,
    wait_for_deployment,
)


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


class TestGetDeploymentStatus:
    """Tests for the get_deployment_status function."""

    def test_get_deployment_status_success(self, monkeypatch):
        """Test get_deployment_status returns stats on success."""

        class MockResponse:
            status_code = 200

            def json(self):
                return {
                    "status": {
                        "success": 5,
                        "failure": 0,
                        "pending": 0,
                        "installing": 0,
                    }
                }

            @property
            def request(self):
                return SimpleNamespace(url="", headers={})

        def mock_get(*args, **kwargs):
            return MockResponse()

        monkeypatch.setattr(
            "mender_docker_lifecycle_helper.utils.mender_server.requests.get",
            mock_get,
        )

        context = SimpleNamespace(
            mender_pat="test-pat-token",
            mender_host="https://hosted.mender.io",
            logger=logging.Logger("test_logger"),
        )

        result = get_deployment_status(context, "deploy-12345")

        assert result is not None
        assert result["status"]["success"] == 5
        assert result["status"]["failure"] == 0

    def test_get_deployment_status_no_pat(self):
        """Test get_deployment_status returns None when mender_pat is not set."""
        context = SimpleNamespace(
            mender_pat=None,
            mender_host="https://hosted.mender.io",
            logger=logging.Logger("test_logger"),
        )

        result = get_deployment_status(context, "deploy-12345")
        assert result is None

    def test_get_deployment_status_failure(self, monkeypatch):
        """Test get_deployment_status raises error on non-200 status."""

        class MockResponse:
            status_code = 404
            text = "Not Found"

            def raise_for_status(self):
                raise requests.HTTPError("404 Client Error")

            @property
            def request(self):
                return SimpleNamespace(url="", headers={})

        def mock_get(*args, **kwargs):
            return MockResponse()

        monkeypatch.setattr(
            "mender_docker_lifecycle_helper.utils.mender_server.requests.get",
            mock_get,
        )

        context = SimpleNamespace(
            mender_pat="test-pat-token",
            mender_host="https://hosted.mender.io",
            logger=logging.Logger("test_logger"),
        )

        with pytest.raises(requests.HTTPError):
            get_deployment_status(context, "deploy-12345")


class TestWaitForDeployment:
    """Tests for the wait_for_deployment function."""

    def test_wait_for_deployment_success(self, monkeypatch):
        """Test wait_for_deployment returns True on success."""

        call_count = 0

        class MockResponse:
            status_code = 200

            def json(self):
                return {
                    "status": {
                        "success": 1,
                        "failure": 0,
                        "pending": 0,
                        "installing": 0,
                    }
                }

            @property
            def request(self):
                return SimpleNamespace(url="", headers={})

        def mock_get(*args, **kwargs):
            return MockResponse()

        monkeypatch.setattr(
            "mender_docker_lifecycle_helper.utils.mender_server.requests.get",
            mock_get,
        )
        monkeypatch.setattr(
            "mender_docker_lifecycle_helper.utils.mender_server.time.sleep",
            lambda x: None,
        )

        context = SimpleNamespace(
            mender_pat="test-pat-token",
            mender_host="https://hosted.mender.io",
            logger=MagicMock(),
        )

        result = wait_for_deployment(
            context, "deploy-12345", poll_interval=1, timeout=10
        )
        assert result is True

    def test_wait_for_deployment_failure(self, monkeypatch):
        """Test wait_for_deployment returns False on failure."""

        class MockResponse:
            status_code = 200

            def json(self):
                return {
                    "status": {
                        "success": 0,
                        "failure": 1,
                        "pending": 0,
                        "installing": 0,
                    }
                }

            @property
            def request(self):
                return SimpleNamespace(url="", headers={})

        def mock_get(*args, **kwargs):
            return MockResponse()

        monkeypatch.setattr(
            "mender_docker_lifecycle_helper.utils.mender_server.requests.get",
            mock_get,
        )
        monkeypatch.setattr(
            "mender_docker_lifecycle_helper.utils.mender_server.time.sleep",
            lambda x: None,
        )

        context = SimpleNamespace(
            mender_pat="test-pat-token",
            mender_host="https://hosted.mender.io",
            logger=MagicMock(),
        )

        result = wait_for_deployment(
            context, "deploy-12345", poll_interval=1, timeout=10
        )
        assert result is False

    def test_wait_for_deployment_timeout(self, monkeypatch):
        """Test wait_for_deployment returns False on timeout."""

        class MockResponse:
            status_code = 200

            def json(self):
                return {
                    "status": {
                        "success": 0,
                        "failure": 0,
                        "pending": 1,
                        "installing": 0,
                    }
                }

            @property
            def request(self):
                return SimpleNamespace(url="", headers={})

        def mock_get(*args, **kwargs):
            return MockResponse()

        monkeypatch.setattr(
            "mender_docker_lifecycle_helper.utils.mender_server.requests.get",
            mock_get,
        )
        monkeypatch.setattr(
            "mender_docker_lifecycle_helper.utils.mender_server.time.sleep",
            lambda x: None,
        )
        monkeypatch.setattr(
            "mender_docker_lifecycle_helper.utils.mender_server.time.time",
            lambda: 1000,  # Simulate time past timeout
        )

        context = SimpleNamespace(
            mender_pat="test-pat-token",
            mender_host="https://hosted.mender.io",
            logger=MagicMock(),
        )

        # Set start time to 0, so timeout is immediately exceeded
        original_wait = (
            wait_for_deployment.__wrapped__
            if hasattr(wait_for_deployment, "__wrapped__")
            else None
        )

        result = wait_for_deployment(
            context, "deploy-12345", poll_interval=1, timeout=10
        )
        assert result is False

    def test_wait_for_deployment_no_pat(self):
        """Test wait_for_deployment returns False when mender_pat is not set."""
        context = SimpleNamespace(
            mender_pat=None,
            mender_host="https://hosted.mender.io",
            logger=MagicMock(),
        )

        result = wait_for_deployment(context, "deploy-12345")
        assert result is False
