"""Unit tests for the mender_server module."""

import logging
import pytest
import requests

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock, mock_open

from mender_docker_lifecycle_helper.utils.mender_server import (
    call_mender_host_api,
    upload_artifact,
    get_deployment_status,
    wait_for_deployment,
)


@pytest.fixture
def mock_context():
    """Create a mock LifecycleHelperContext."""
    return SimpleNamespace(
        logger=MagicMock(),
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


class TestCallMenderHostApiRetries:
    """Tests for retry logic in call_mender_host_api."""

    def test_retries_on_server_error(self, monkeypatch):
        """Test call_mender_host_api retries on 5xx status codes."""
        call_count = [0]

        class MockResponse:
            status_code = 500
            text = "Internal Server Error"

            @property
            def request(self):
                return SimpleNamespace(url="", headers={})

            def raise_for_status(self):
                raise requests.HTTPError("500 Server Error")

        def make_response(status):
            class R:
                status_code = status
                text = f"Error {status}"

                @property
                def request(self):
                    return SimpleNamespace(url="", headers={})

                def raise_for_status(self):
                    raise requests.HTTPError(f"{status} Error")

            return R

        response_500 = make_response(500)
        response_201 = make_response(201)

        def mock_post(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                return response_500()
            return response_201()

        monkeypatch.setattr(
            "mender_docker_lifecycle_helper.utils.mender_server.requests.post",
            mock_post,
        )
        monkeypatch.setattr(
            "mender_docker_lifecycle_helper.utils.mender_server.time.sleep",
            lambda x: None,
        )

        context = SimpleNamespace(
            mender_pat="test-pat-token",
            mender_host="https://hosted.mender.io",
            logger=logging.Logger("test_logger"),
        )

        result = call_mender_host_api(
            context, "artifacts", {}, max_retries=3, base_delay=1
        )

        assert call_count[0] == 3
        assert result.status_code == 201

    def test_reraises_client_error_immediately(self, monkeypatch):
        """Test call_mender_host_api re-raises 4xx errors without retry."""
        call_count = [0]

        class MockResponse:
            status_code = 400
            text = "Bad Request"

            @property
            def request(self):
                return SimpleNamespace(url="", headers={})

            def raise_for_status(self):
                raise requests.HTTPError("400 Client Error")

        def mock_post(*args, **kwargs):
            call_count[0] += 1
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
            call_mender_host_api(context, "artifacts", {}, max_retries=3)

        assert call_count[0] == 1

    def test_reraises_after_max_retries_on_server_error(self, monkeypatch):
        """Test call_mender_host_api re-raises after max retries on 5xx errors."""
        call_count = [0]

        class MockResponse:
            status_code = 503
            text = "Service Unavailable"

            @property
            def request(self):
                return SimpleNamespace(url="", headers={})

            def raise_for_status(self):
                raise requests.HTTPError("503 Service Unavailable")

        def mock_post(*args, **kwargs):
            call_count[0] += 1
            return MockResponse()

        monkeypatch.setattr(
            "mender_docker_lifecycle_helper.utils.mender_server.requests.post",
            mock_post,
        )
        monkeypatch.setattr(
            "mender_docker_lifecycle_helper.utils.mender_server.time.sleep",
            lambda x: None,
        )

        context = SimpleNamespace(
            mender_pat="test-pat-token",
            mender_host="https://hosted.mender.io",
            logger=logging.Logger("test_logger"),
        )

        with pytest.raises(requests.HTTPError):
            call_mender_host_api(context, "artifacts", {}, max_retries=3)

        assert call_count[0] == 4  # Initial attempt + 3 retries

    def test_no_retry_by_default(self, monkeypatch):
        """Test call_mender_host_api does not retry by default (max_retries=0)."""
        call_count = [0]

        class MockResponse:
            status_code = 500
            text = "Internal Server Error"

            @property
            def request(self):
                return SimpleNamespace(url="", headers={})

            def raise_for_status(self):
                raise requests.HTTPError("500 Server Error")

        def mock_post(*args, **kwargs):
            call_count[0] += 1
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

        assert call_count[0] == 1


class TestUploadArtifact:
    """Tests for the upload_artifact method with retry logic."""

    def test_upload_artifact_calls_api_with_retry_params(self, mock_context):
        """Test upload_artifact passes retry params to call_mender_host_api."""
        mock_context.mender_host = "https://hosted.mender.io"
        mock_context.logger = MagicMock()

        artifact = MagicMock()
        artifact.filename = Path("/tmp/test-artifact.mender")
        artifact.name = "test-manifest-1.0.0"

        with patch(
            "mender_docker_lifecycle_helper.utils.mender_server.call_mender_host_api"
        ) as mock_call_api:
            mock_call_api.return_value = SimpleNamespace(status_code=201)
            with patch("builtins.open", mock_open(read_data=b"fake artifact data")):
                with patch("pathlib.Path.stat") as mock_stat:
                    mock_stat.return_value.st_size = 100

                    upload_artifact(
                        mock_context, artifact, max_retries=5, base_delay=10
                    )

                    assert mock_call_api.call_count == 1
                    call_kwargs = mock_call_api.call_args[1]
                    assert call_kwargs["max_retries"] == 5
                    assert call_kwargs["base_delay"] == 10

    def test_upload_artifact_logs_info(self, mock_context):
        """Test upload_artifact logs appropriate info message."""
        mock_context.logger = MagicMock()

        artifact = MagicMock()
        artifact.filename = Path("/tmp/test-artifact.mender")
        artifact.name = "test-manifest-1.0.0"

        with patch(
            "mender_docker_lifecycle_helper.utils.mender_server.call_mender_host_api"
        ) as mock_call_api:
            mock_call_api.return_value = SimpleNamespace(status_code=201)
            with patch("builtins.open", mock_open(read_data=b"fake artifact data")):
                with patch("pathlib.Path.stat") as mock_stat:
                    mock_stat.return_value.st_size = 100

                    upload_artifact(mock_context, artifact)

                    mock_context.logger.info.assert_called_once_with(
                        f"Uploaded artifact {artifact.filename}"
                    )


class TestGetDeploymentStatus:
    """Tests for the get_deployment_status function."""

    def test_get_deployment_status_success(self, monkeypatch):
        """Test get_deployment_status returns stats on success."""

        class MockResponse:
            status_code = 200

            def json(self):
                return {
                    "success": 5,
                    "failure": 0,
                    "pending": 0,
                    "installing": 0,
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
        assert result["success"] == 5
        assert result["failure"] == 0

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

        class MockResponse:
            status_code = 200

            def json(self):
                return {
                    "success": 1,
                    "failure": 0,
                    "pending": 0,
                    "installing": 0,
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
                    "success": 0,
                    "failure": 1,
                    "pending": 0,
                    "installing": 0,
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
        time_values = [0, 0, 11]  # start_time=0, loop check=0 (enter), then 11 (exit)
        time_index = [0]

        class MockResponse:
            status_code = 200

            def json(self):
                return {
                    "success": 0,
                    "failure": 0,
                    "pending": 1,
                    "installing": 0,
                }

            @property
            def request(self):
                return SimpleNamespace(url="", headers={})

        def mock_get(*args, **kwargs):
            return MockResponse()

        def mock_time():
            idx = time_index[0]
            time_index[0] += 1
            return time_values[min(idx, len(time_values) - 1)]

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
            mock_time,
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

    def test_wait_for_deployment_no_pat(self):
        """Test wait_for_deployment returns False when mender_pat is not set."""
        context = SimpleNamespace(
            mender_pat=None,
            mender_host="https://hosted.mender.io",
            logger=MagicMock(),
        )

        result = wait_for_deployment(context, "deploy-12345")
        assert result is False

    def test_wait_for_deployment_all_stats_zero(self, monkeypatch):
        """Test wait_for_deployment handles all stats being zero (no results yet case)."""
        time_values = [0, 0, 11]  # start_time=0, loop check=0 (enter), then 11 (exit)
        time_index = [0]

        class MockResponse:
            status_code = 200

            def json(self):
                return {
                    "success": 0,
                    "failure": 0,
                    "pending": 0,
                    "installing": 0,
                }

            @property
            def request(self):
                return SimpleNamespace(url="", headers={})

        def mock_get(*args, **kwargs):
            return MockResponse()

        def mock_time():
            idx = time_index[0]
            time_index[0] += 1
            return time_values[min(idx, len(time_values) - 1)]

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
            mock_time,
        )

        context = SimpleNamespace(
            mender_pat="test-pat-token",
            mender_host="https://hosted.mender.io",
            logger=MagicMock(),
        )

        result = wait_for_deployment(
            context, "deploy-12345", poll_interval=1, timeout=10
        )
        assert result is False  # Returns False on timeout

        # Verify the debug log for "no results yet" was called
        context.logger.debug.assert_any_call(
            "Deployment deploy-12345 has no results yet."
        )
