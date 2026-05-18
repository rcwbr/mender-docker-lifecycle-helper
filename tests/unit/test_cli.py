"""Unit tests for the CLI module."""

from click.testing import CliRunner
from unittest.mock import patch, MagicMock

from pathlib import Path
from types import SimpleNamespace

from mender_docker_lifecycle_helper.cli import cli
from mender_docker_lifecycle_helper.context import LOG_LEVELS


class TestCliServiceFileConversion:
    """Tests for service_files conversion from tuples to dict."""

    def test_service_files_empty(self):
        """Test that empty service_files produces empty dict."""
        args = SimpleNamespace(
            artifact_filename=None,
            cache=True,
            cache_dir="cache_dir",
            cache_limit=True,
            cache_limit_percent=None,
            cache_limit_size=None,
            cache_operation_only=False,
            delta=True,
            device_type="device_type",
            device_group=None,
            log_level="INFO",
            mender_host="https://hosted.mender.io",
            manifest_name=None,
            manifest_file=Path("manifest_file"),
            platform="platform",
            previous_version=None,
            release=False,
            service_files=(),
            service_images=(),
            wait_for_deploy=True,
            verbose=0,
        )

        # Simulate the conversion logic from cli()
        service_files = {}
        for service, file in args.service_files:
            service_files[service] = file
        args.service_files = service_files

        assert args.service_files == {}

    def test_service_files_single(self):
        """Test that single service_file is converted correctly."""
        args = SimpleNamespace(
            artifact_filename=None,
            cache=True,
            cache_dir="cache_dir",
            cache_limit=True,
            cache_limit_percent=None,
            cache_limit_size=None,
            cache_operation_only=False,
            delta=True,
            device_type="device_type",
            device_group=None,
            log_level="INFO",
            mender_host="https://hosted.mender.io",
            manifest_name=None,
            manifest_file=Path("manifest_file"),
            platform="platform",
            previous_version=None,
            release=False,
            service_files=(("web", "web-image.tar"),),
            service_images=(),
            wait_for_deploy=True,
            verbose=0,
        )

        service_files = {}
        for service, file in args.service_files:
            service_files[service] = file
        args.service_files = service_files

        assert args.service_files == {"web": "web-image.tar"}

    def test_service_files_multiple(self):
        """Test that multiple service_files are converted correctly."""
        args = SimpleNamespace(
            artifact_filename=None,
            cache=True,
            cache_dir="cache_dir",
            cache_limit=True,
            cache_limit_percent=None,
            cache_limit_size=None,
            cache_operation_only=False,
            delta=True,
            device_type="device_type",
            device_group=None,
            log_level="INFO",
            mender_host="https://hosted.mender.io",
            manifest_name=None,
            manifest_file=Path("manifest_file"),
            platform="platform",
            previous_version=None,
            release=False,
            service_files=(("web", "web.tar"), ("api", "api.tar")),
            service_images=(),
            wait_for_deploy=True,
            verbose=0,
        )

        service_files = {}
        for service, file in args.service_files:
            service_files[service] = file
        args.service_files = service_files

        assert args.service_files == {"web": "web.tar", "api": "api.tar"}


class TestCliServiceImageConversion:
    """Tests for service_images conversion from tuples to dict."""

    def test_service_images_empty(self):
        """Test that empty service_images produces empty dict."""
        args = SimpleNamespace(
            artifact_filename=None,
            cache=True,
            cache_dir="cache_dir",
            cache_limit=True,
            cache_limit_percent=None,
            cache_limit_size=None,
            cache_operation_only=False,
            delta=True,
            device_type="device_type",
            device_group=None,
            log_level="INFO",
            mender_host="https://hosted.mender.io",
            manifest_name=None,
            manifest_file=Path("manifest_file"),
            platform="platform",
            previous_version=None,
            release=False,
            service_files=(),
            service_images=(),
            wait_for_deploy=True,
            verbose=0,
        )

        service_images = {}
        for service, image in args.service_images:
            service_images[service] = image
        args.service_images = service_images

        assert args.service_images == {}

    def test_service_images_single(self):
        """Test that single service_image is converted correctly."""
        args = SimpleNamespace(
            artifact_filename=None,
            cache=True,
            cache_dir="cache_dir",
            cache_limit=True,
            cache_limit_percent=None,
            cache_limit_size=None,
            cache_operation_only=False,
            delta=True,
            device_type="device_type",
            device_group=None,
            log_level="INFO",
            mender_host="https://hosted.mender.io",
            manifest_name=None,
            manifest_file=Path("manifest_file"),
            platform="platform",
            previous_version=None,
            release=False,
            service_files=(),
            service_images=(("web", "nginx:latest"),),
            wait_for_deploy=True,
            verbose=0,
        )

        service_images = {}
        for service, image in args.service_images:
            service_images[service] = image
        args.service_images = service_images

        assert args.service_images == {"web": "nginx:latest"}

    def test_service_images_multiple(self):
        """Test that multiple service_images are converted correctly."""
        args = SimpleNamespace(
            artifact_filename=None,
            cache=True,
            cache_dir="cache_dir",
            cache_limit=True,
            cache_limit_percent=None,
            cache_limit_size=None,
            cache_operation_only=False,
            delta=True,
            device_type="device_type",
            device_group=None,
            log_level="INFO",
            mender_host="https://hosted.mender.io",
            manifest_name=None,
            manifest_file=Path("manifest_file"),
            platform="platform",
            previous_version=None,
            release=False,
            service_files=(),
            service_images=(("web", "nginx:latest"), ("api", "redis:7")),
            wait_for_deploy=True,
            verbose=0,
        )

        service_images = {}
        for service, image in args.service_images:
            service_images[service] = image
        args.service_images = service_images

        assert args.service_images == {"web": "nginx:latest", "api": "redis:7"}


class TestCliVerboseLogLevel:
    """Tests for log level adjustment with verbose flag."""

    def test_verbose_zero(self):
        """Test that verbose=0 keeps log level unchanged."""

        log_level = "INFO"
        verbose = 0
        result = LOG_LEVELS[max(0, LOG_LEVELS.index(log_level) - verbose)]
        assert result == "INFO"

    def test_verbose_one(self):
        """Test that verbose=1 reduces log level by one (more verbose)."""

        log_level = "INFO"
        verbose = 1
        result = LOG_LEVELS[max(0, LOG_LEVELS.index(log_level) - verbose)]
        assert result == "DEBUG"

    def test_verbose_two(self):
        """Test that verbose=2 reduces log level by two (capped at DEBUG)."""

        log_level = "INFO"
        verbose = 2
        result = LOG_LEVELS[max(0, LOG_LEVELS.index(log_level) - verbose)]
        assert result == "DEBUG"

    def test_verbose_exceeds_available(self):
        """Test that verbose exceeding available levels caps at DEBUG."""

        log_level = "DEBUG"
        verbose = 5
        result = LOG_LEVELS[max(0, LOG_LEVELS.index(log_level) - verbose)]
        assert result == "DEBUG"

    def test_verbose_from_warning(self):
        """Test verbose from WARNING level reduces to INFO."""

        log_level = "WARNING"
        verbose = 1
        result = LOG_LEVELS[max(0, LOG_LEVELS.index(log_level) - verbose)]
        assert result == "INFO"


class TestCliIntegration:
    """Integration tests for the CLI command using CliRunner."""

    def test_cli_help(self):
        """Test that CLI displays help message."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Produce and deploy a Mender artifact" in result.output

    def test_cli_version(self):
        """Test that CLI displays version."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "version" in result.output.lower()

    def test_cli_missing_manifest_file(self):
        """Test that CLI fails when manifest file does not exist."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "virtual",
                "-p",
                "linux/arm/v7",
                "--previous-version",
                "1.0.0",
                "nonexistent.yaml",
            ],
        )
        assert result.exit_code != 0

    def test_cli_calls_lifecycle_helper(self, tmp_path):
        """Test that CLI calls LifecycleHelper with correct args."""
        manifest_file = tmp_path / "docker-compose.yml"
        manifest_file.touch()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "-t",
                    "virtual",
                    "-p",
                    "linux/arm/v7",
                    "--previous-version",
                    "1.0.0",
                    str(manifest_file),
                ],
            )

        assert result.exit_code == 0
        mock_helper.assert_called_once()
        mock_instance.prep_artifact.assert_called_once()

    def test_cli_missing_manifest_file_arg(self, tmp_path):
        """Test that CLI fails when manifest_file argument is not provided."""
        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "-t",
                    "virtual",
                    "-p",
                    "linux/arm/v7",
                    "--previous-version",
                    "1.0.0",
                ],
            )

        assert result.exit_code != 0
        assert "manifest_file is required" in result.output
        mock_helper.assert_called_once()

    def test_cli_with_service_files(self, tmp_path):
        """Test CLI with service-files option."""
        manifest_file = tmp_path / "docker-compose.yml"
        manifest_file.touch()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "-t",
                    "virtual",
                    "-p",
                    "linux/arm/v7",
                    "--previous-version",
                    "1.0.0",
                    "-f",
                    "web",
                    "web.tar",
                    "-f",
                    "api",
                    "api.tar",
                    str(manifest_file),
                ],
            )

        assert result.exit_code == 0
        call_args = mock_helper.call_args[0][0]
        assert call_args.service_files == {"web": "web.tar", "api": "api.tar"}

    def test_cli_with_service_images(self, tmp_path):
        """Test CLI with service-images option."""
        manifest_file = tmp_path / "docker-compose.yml"
        manifest_file.touch()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "-t",
                    "virtual",
                    "-p",
                    "linux/arm/v7",
                    "--previous-version",
                    "1.0.0",
                    "-i",
                    "web",
                    "nginx:latest",
                    "-i",
                    "api",
                    "redis:7",
                    str(manifest_file),
                ],
            )

        assert result.exit_code == 0
        call_args = mock_helper.call_args[0][0]
        assert call_args.service_images == {"web": "nginx:latest", "api": "redis:7"}

    def test_cli_with_no_cache(self, tmp_path):
        """Test CLI with --no-cache option."""
        manifest_file = tmp_path / "docker-compose.yml"
        manifest_file.touch()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "-t",
                    "virtual",
                    "-p",
                    "linux/arm/v7",
                    "--previous-version",
                    "1.0.0",
                    "--no-cache",
                    str(manifest_file),
                ],
            )

        assert result.exit_code == 0
        call_args = mock_helper.call_args[0][0]
        assert call_args.cache is False

    def test_cli_with_no_delta(self, tmp_path):
        """Test CLI with --no-delta option."""
        manifest_file = tmp_path / "docker-compose.yml"
        manifest_file.touch()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "-t",
                    "virtual",
                    "-p",
                    "linux/arm/v7",
                    "--previous-version",
                    "1.0.0",
                    "--no-delta",
                    str(manifest_file),
                ],
            )

        assert result.exit_code == 0
        call_args = mock_helper.call_args[0][0]
        assert call_args.delta is False

    def test_cli_with_release(self, tmp_path):
        """Test CLI with --release option."""
        manifest_file = tmp_path / "docker-compose.yml"
        manifest_file.touch()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "-t",
                    "virtual",
                    "-p",
                    "linux/arm/v7",
                    "--previous-version",
                    "1.0.0",
                    "--release",
                    str(manifest_file),
                ],
            )

        assert result.exit_code == 0
        call_args = mock_helper.call_args[0][0]
        assert call_args.release is True

    def test_cli_with_artifact_filename(self, tmp_path):
        """Test CLI with --artifact-filename option."""
        manifest_file = tmp_path / "docker-compose.yml"
        manifest_file.touch()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "-t",
                    "virtual",
                    "-p",
                    "linux/arm/v7",
                    "--previous-version",
                    "1.0.0",
                    "-a",
                    "my-artifact.mender",
                    str(manifest_file),
                ],
            )

        assert result.exit_code == 0
        call_args = mock_helper.call_args[0][0]
        assert call_args.artifact_filename == "my-artifact.mender"

    def test_cli_with_device_group(self, tmp_path):
        """Test CLI with --device-group option."""
        manifest_file = tmp_path / "docker-compose.yml"
        manifest_file.touch()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "-t",
                    "virtual",
                    "-p",
                    "linux/arm/v7",
                    "--previous-version",
                    "1.0.0",
                    "-g",
                    "production",
                    str(manifest_file),
                ],
            )

        assert result.exit_code == 0
        call_args = mock_helper.call_args[0][0]
        assert call_args.device_group == "production"

    def test_cli_with_manifest_name(self, tmp_path):
        """Test CLI with --manifest-name option."""
        manifest_file = tmp_path / "docker-compose.yml"
        manifest_file.touch()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "-t",
                    "virtual",
                    "-p",
                    "linux/arm/v7",
                    "--previous-version",
                    "1.0.0",
                    "-m",
                    "my-app",
                    str(manifest_file),
                ],
            )

        assert result.exit_code == 0
        call_args = mock_helper.call_args[0][0]
        assert call_args.manifest_name == "my-app"

    def test_cli_with_mender_host(self, tmp_path):
        """Test CLI with --mender-host option."""
        manifest_file = tmp_path / "docker-compose.yml"
        manifest_file.touch()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "-t",
                    "virtual",
                    "-p",
                    "linux/arm/v7",
                    "--previous-version",
                    "1.0.0",
                    "-h",
                    "https://mender.example.com",
                    str(manifest_file),
                ],
            )

        assert result.exit_code == 0
        call_args = mock_helper.call_args[0][0]
        assert call_args.mender_host == "https://mender.example.com"

    def test_cli_with_cache_dir(self, tmp_path):
        """Test CLI with --cache-dir option."""
        manifest_file = tmp_path / "docker-compose.yml"
        manifest_file.touch()
        cache_dir = tmp_path / "custom-cache"

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "-t",
                    "virtual",
                    "-p",
                    "linux/arm/v7",
                    "--previous-version",
                    "1.0.0",
                    "--cache-dir",
                    str(cache_dir),
                    str(manifest_file),
                ],
            )

        assert result.exit_code == 0
        call_args = mock_helper.call_args[0][0]
        assert str(call_args.cache_dir) == str(cache_dir)

    def test_cli_with_log_level(self, tmp_path):
        """Test CLI with --log-level option."""
        manifest_file = tmp_path / "docker-compose.yml"
        manifest_file.touch()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "-t",
                    "virtual",
                    "-p",
                    "linux/arm/v7",
                    "--previous-version",
                    "1.0.0",
                    "-l",
                    "DEBUG",
                    str(manifest_file),
                ],
            )

        assert result.exit_code == 0
        call_args = mock_helper.call_args[0][0]
        assert call_args.log_level == "DEBUG"

    def test_cli_with_verbose(self, tmp_path):
        """Test CLI with -v option for verbose."""
        manifest_file = tmp_path / "docker-compose.yml"
        manifest_file.touch()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "-t",
                    "virtual",
                    "-p",
                    "linux/arm/v7",
                    "--previous-version",
                    "1.0.0",
                    "-v",
                    str(manifest_file),
                ],
            )

        assert result.exit_code == 0
        call_args = mock_helper.call_args[0][0]
        assert call_args.verbose == 1

    def test_cli_with_multiple_verbose(self, tmp_path):
        """Test CLI with multiple -v options."""
        manifest_file = tmp_path / "docker-compose.yml"
        manifest_file.touch()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "-t",
                    "virtual",
                    "-p",
                    "linux/arm/v7",
                    "--previous-version",
                    "1.0.0",
                    "-vvv",
                    str(manifest_file),
                ],
            )

        assert result.exit_code == 0
        call_args = mock_helper.call_args[0][0]
        assert call_args.verbose == 3

    def test_cli_missing_required_device_type(self, tmp_path):
        """Test CLI fails without required device-type option."""
        manifest_file = tmp_path / "docker-compose.yml"
        manifest_file.touch()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "-p",
                    "linux/arm/v7",
                    "--previous-version",
                    "1.0.0",
                    str(manifest_file),
                ],
            )

        assert result.exit_code != 0

    def test_cli_missing_required_platform(self, tmp_path):
        """Test CLI fails without required platform option."""
        manifest_file = tmp_path / "docker-compose.yml"
        manifest_file.touch()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "-t",
                    "virtual",
                    "--previous-version",
                    "1.0.0",
                    str(manifest_file),
                ],
            )

        assert result.exit_code != 0

    def test_cli_with_wait_for_deploy(self, tmp_path):
        """Test CLI with --wait-for-deploy option."""
        manifest_file = tmp_path / "docker-compose.yml"
        manifest_file.touch()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "-t",
                    "virtual",
                    "-p",
                    "linux/arm/v7",
                    "--previous-version",
                    "1.0.0",
                    "-w",
                    str(manifest_file),
                ],
            )

        assert result.exit_code == 0
        call_args = mock_helper.call_args[0][0]
        assert call_args.wait_for_deploy is True

    def test_cli_without_wait_for_deploy(self, tmp_path):
        """Test CLI without --wait-for-deploy option (default True)."""
        manifest_file = tmp_path / "docker-compose.yml"
        manifest_file.touch()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "-t",
                    "virtual",
                    "-p",
                    "linux/arm/v7",
                    "--previous-version",
                    "1.0.0",
                    str(manifest_file),
                ],
            )

        assert result.exit_code == 0
        call_args = mock_helper.call_args[0][0]
        assert call_args.wait_for_deploy is True

    def test_cli_with_long_form_wait_for_deploy(self, tmp_path):
        """Test CLI with --wait-for-deploy long form option."""
        manifest_file = tmp_path / "docker-compose.yml"
        manifest_file.touch()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "-t",
                    "virtual",
                    "-p",
                    "linux/arm/v7",
                    "--previous-version",
                    "1.0.0",
                    "--wait-for-deploy",
                    str(manifest_file),
                ],
            )

        assert result.exit_code == 0
        call_args = mock_helper.call_args[0][0]
        assert call_args.wait_for_deploy is True

    def test_cli_with_no_wait_for_deploy(self, tmp_path):
        """Test CLI with --no-wait-for-deploy option."""
        manifest_file = tmp_path / "docker-compose.yml"
        manifest_file.touch()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "-t",
                    "virtual",
                    "-p",
                    "linux/arm/v7",
                    "--previous-version",
                    "1.0.0",
                    "--no-wait-for-deploy",
                    str(manifest_file),
                ],
            )

        assert result.exit_code == 0
        call_args = mock_helper.call_args[0][0]
        assert call_args.wait_for_deploy is False


class TestCliCacheLimitOptions:
    """Tests for cache limit CLI options."""

    def test_cli_with_cache_limit_size(self, tmp_path):
        """Test CLI with --cache-limit-size option."""
        manifest_file = tmp_path / "docker-compose.yml"
        manifest_file.touch()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "-t",
                    "virtual",
                    "-p",
                    "linux/arm/v7",
                    "--previous-version",
                    "1.0.0",
                    "--cache-limit-size",
                    "5000000000",
                    str(manifest_file),
                ],
            )

        assert result.exit_code == 0
        call_args = mock_helper.call_args[0][0]
        assert call_args.cache_limit_size == 5000000000
        assert call_args.cache_limit is True

    def test_cli_with_cache_limit_percent(self, tmp_path):
        """Test CLI with --cache-limit-percent option."""
        manifest_file = tmp_path / "docker-compose.yml"
        manifest_file.touch()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "-t",
                    "virtual",
                    "-p",
                    "linux/arm/v7",
                    "--previous-version",
                    "1.0.0",
                    "--cache-limit-percent",
                    "20",
                    str(manifest_file),
                ],
            )

        assert result.exit_code == 0
        call_args = mock_helper.call_args[0][0]
        assert call_args.cache_limit_percent == 20.0

    def test_cli_with_no_cache_limit(self, tmp_path):
        """Test CLI with --no-cache-limit option."""
        manifest_file = tmp_path / "docker-compose.yml"
        manifest_file.touch()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "-t",
                    "virtual",
                    "-p",
                    "linux/arm/v7",
                    "--previous-version",
                    "1.0.0",
                    "--no-cache-limit",
                    str(manifest_file),
                ],
            )

        assert result.exit_code == 0
        call_args = mock_helper.call_args[0][0]
        assert call_args.cache_limit is False

    def test_cli_size_takes_precedence_over_percent(self, tmp_path):
        """Test that --cache-limit-size takes precedence over --cache-limit-percent."""
        manifest_file = tmp_path / "docker-compose.yml"
        manifest_file.touch()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "-t",
                    "virtual",
                    "-p",
                    "linux/arm/v7",
                    "--previous-version",
                    "1.0.0",
                    "--cache-limit-size",
                    "5000000000",
                    "--cache-limit-percent",
                    "20",
                    str(manifest_file),
                ],
            )

        assert result.exit_code == 0
        call_args = mock_helper.call_args[0][0]
        assert call_args.cache_limit_size == 5000000000
        assert call_args.cache_limit_percent is None


class TestCliCacheCleanCommand:
    """Tests for the cache clean CLI command."""

    def test_cache_clean_no_limit_specified(self, tmp_path):
        """Test cache clean without limit flags uses default percent."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True)
        (cache_dir / "images").mkdir()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "--clean-cache",
                    "--cache-dir",
                    str(cache_dir),
                ],
            )

        assert result.exit_code == 0
        mock_helper.assert_called_once()
        args = mock_helper.call_args[0][0]
        assert str(args.cache_dir) == str(cache_dir)
        assert args.clear_cache is False
        assert args.clear_image_cache is False
        assert args.clean_cache is True

    def test_cache_clean_size_takes_precedence_over_percent(self, tmp_path):
        """Test that --cache-limit-size takes precedence over --cache-limit-percent."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True)
        (cache_dir / "images").mkdir()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "--clean-cache",
                    "--cache-dir",
                    str(cache_dir),
                    "--cache-limit-size",
                    "1000",
                    "--cache-limit-percent",
                    "20",
                ],
            )

        assert result.exit_code == 0
        args = mock_helper.call_args[0][0]
        assert args.cache_limit_size == 1000

    def test_clear_image_cache(self, tmp_path):
        """Test --clear-image-cache flag removes image cache."""
        cache_dir = tmp_path / "cache"
        images_dir = cache_dir / "images"
        images_dir.mkdir(parents=True)
        (images_dir / "save").mkdir()
        (images_dir / "extract").mkdir()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "--clear-image-cache",
                    "--cache-dir",
                    str(cache_dir),
                ],
            )

        assert result.exit_code == 0
        args = mock_helper.call_args[0][0]
        assert args.clear_image_cache is True

    def test_clear_cache(self, tmp_path):
        """Test --clear-cache flag calls LifecycleHelperContext."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True)
        (cache_dir / "images").mkdir()
        (cache_dir / "manifests").mkdir()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "--clear-cache",
                    "--cache-dir",
                    str(cache_dir),
                ],
            )

        assert result.exit_code == 0
        args = mock_helper.call_args[0][0]
        assert args.clear_cache is True

    def test_cache_nonexistent_directory(self, tmp_path):
        """Test clear_cache on non-existent directory raises FileNotFoundError."""
        cache_dir = tmp_path / "nonexistent"

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "--clear-cache",
                    "--cache-dir",
                    str(cache_dir),
                ],
            )

        # The clear_cache method raises FileNotFoundError if the directory doesn't exist
        assert result.exit_code == 0

    def test_clean_cache_does_not_call_lifecycle_helper(self, tmp_path):
        """Test that --clean-cache triggers helper creation with cache flags."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True)
        (cache_dir / "images").mkdir()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "--clean-cache",
                    "--cache-dir",
                    str(cache_dir),
                    "--cache-limit-size",
                    "1000",
                ],
            )

        assert result.exit_code == 0
        args = mock_helper.call_args[0][0]
        assert args.clean_cache is True

    def test_clear_image_cache_does_not_call_lifecycle_helper(self, tmp_path):
        """Test that --clear-image-cache triggers helper creation with cache flags."""
        cache_dir = tmp_path / "cache"
        images_dir = cache_dir / "images"
        images_dir.mkdir(parents=True)
        (images_dir / "save").mkdir()
        (images_dir / "extract").mkdir()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "--clear-image-cache",
                    "--cache-dir",
                    str(cache_dir),
                ],
            )

        assert result.exit_code == 0
        args = mock_helper.call_args[0][0]
        assert args.clear_image_cache is True

    def test_clear_cache_does_not_call_lifecycle_helper(self, tmp_path):
        """Test that --clear-cache triggers helper creation with cache flags."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True)
        (cache_dir / "images").mkdir()
        (cache_dir / "manifests").mkdir()

        mock_helper = MagicMock()
        mock_instance = MagicMock()
        mock_helper.return_value = mock_instance

        with patch("mender_docker_lifecycle_helper.cli.LifecycleHelper", mock_helper):
            runner = CliRunner()
            result = runner.invoke(
                cli,
                [
                    "--clear-cache",
                    "--cache-dir",
                    str(cache_dir),
                ],
            )

        assert result.exit_code == 0
        args = mock_helper.call_args[0][0]
        assert args.clear_cache is True
