from __future__ import annotations

import logging
from pathlib import Path

import click
from rich.console import Console

from job_hunter import __version__

console = Console()


def _setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


@click.group()
@click.version_option(version=__version__)
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
@click.option("--config-dir", type=click.Path(exists=True), default=".", help="Config directory")
@click.pass_context
def cli(ctx, verbose, config_dir):
    """Job Hunter — discover, score, tailor, apply."""
    _setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["config_dir"] = Path(config_dir)
    ctx.obj["verbose"] = verbose


@cli.command()
@click.pass_context
def doctor(ctx):
    """Check that all dependencies and configs are set up."""
    click.echo("doctor: not yet implemented")


@cli.command()
@click.pass_context
def status(ctx):
    """Show pipeline statistics."""
    click.echo("status: not yet implemented")
