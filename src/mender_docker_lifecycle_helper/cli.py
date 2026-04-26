from pathlib import Path
from types import SimpleNamespace

import click

from mender_docker_lifecycle_helper.context import LifecycleHelperContext, LOG_LEVELS
from mender_docker_lifecycle_helper.helper import LifecycleHelper


@click.command(context_settings={"show_default": True})
@click.option(
    "-a",
    "--artifact-filename",
    default=None,
    help="Name of the artifact file to create. [default: <manifest-name>-<previous-version>+<current repo commit SHA>+<UUID>.mender]",
    type=str,
    show_default=False,
)
@click.option(
    "--cache/--no-cache",
    default=True,
    flag_value=True,
    help="Read/skip reading previous artifact info from cache and always read from the repo at the previous version.",
)
@click.option(
    "--cache-dir",
    default=LifecycleHelperContext._default_cache_dir(),
    help="The cache dir for the helper. Overrides the MENDER_HELPER_CACHE_DIR variable.",
    type=click.Path(file_okay=False, dir_okay=True),
)
@click.option(
    "--delta/--no-delta",
    default=True,
    flag_value=True,
    help="Generate the artifact as an update artifact, if applicable.",
)
@click.option(
    "-t",
    "--device-type",
    help="Device type for the artifact.",
    required=True,
    type=str,
)
@click.option(
    "-g",
    "--device-group",
    default=None,
    help="Device group to which to deploy the artifact, or skip deployment if not defined.",
    type=str,
)
@click.option(
    "-l",
    "--log-level",
    default="INFO",
    help="Set logging level",
    type=click.Choice(LOG_LEVELS, case_sensitive=False),
)
@click.option(
    "-m",
    "--manifest-name",
    default=None,
    help="The application/software name for the artifact [default: <dirname of repo containing manifest_file>-<dirname directly containing manifest_file>].",
    show_default=False,
    type=str,
)
@click.option(
    "-h",
    "--mender-host",
    default="https://hosted.mender.io",
    help="Mender host URL for artifact upload and deployment.",
)
@click.option(
    "-p",
    "--platform",
    help="Platform with which the artifact is compatible (e.g., linux/arm/v7)",
    required=True,
    type=str,
)
@click.option(
    "--previous-version",
    default=None,
    help="Repo ref from which to read image names and versions for comparison to the current state. [default: contents of the VERSION file in root of the repo containing manifest_file]",
    show_default=False,
    type=str,
)
@click.option(
    "-r",
    "--release/--no-release",
    default=False,
    flag_value=True,
    help="Create the artifact for a release, using the current value of the VERSION file as the artifact version and the value of the VERSION file at the previous commit as the --previous-version.",
)
@click.option(
    "-f",
    "--service-file",
    "service_files",
    default=None,
    metavar="<SERVICE NAME> <IMAGE FILE>",
    help="Image file to extract and use to override the image for the specified service in the manifest_file. Can be specified multiple times.",
    type=click.Tuple([str, str]),
    multiple=True,
)
@click.option(
    "-i",
    "--service-image",
    "service_images",
    default=None,
    metavar="<SERVICE NAME> <IMAGE NAME>",
    help="Image name to override for the specified service in the manifest_file. Can be specified multiple times.",
    type=click.Tuple([str, str]),
    multiple=True,
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase verbosity by one level (see --log-level). Can be specified multiple times.",
)
@click.argument(
    "manifest_file",
    type=click.Path(
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        allow_dash=True,
        path_type=Path,
    ),
)
@click.version_option()
def cli(**args) -> None:
    """
    Produce and deploy a Mender artifact for the MANIFEST_FILE (compose yaml) Docker application, as deltas against local cache when available or repo version context otherwise.

    :param args: An object of CLI args for the execution as prepared by Click decorators.
    :return: None
    """
    args = SimpleNamespace(**args)

    args.log_level = LOG_LEVELS[max(0, LOG_LEVELS.index(args.log_level) - args.verbose)]

    service_files = {}
    for service, file in args.service_files:
        service_files[service] = file
    args.service_files = service_files

    service_images = {}
    for service, image in args.service_images:
        service_images[service] = image
    args.service_images = service_images

    LifecycleHelper(args).prep_artifact()


if __name__ == "__main__":
    cli()
