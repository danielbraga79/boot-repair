from __future__ import annotations

import logging
import os
import shutil
from subprocess import CompletedProcess
from typing import Mapping, Sequence

from .system import CommandError, CommandNotFoundError, CommandResult, CommandTimeoutError, run

logger = logging.getLogger(__name__)


def is_root() -> bool:
    return hasattr(os, 'geteuid') and os.geteuid() == 0


def sudo_available() -> bool:
    return shutil.which('sudo') is not None


def _normalize_command(command: Sequence[str]) -> tuple[str, ...]:
    if not command:
        raise ValueError('command must not be empty')
    argv = tuple(str(part) for part in command)
    if any(not part.strip() for part in argv):
        raise ValueError('command parts must not be empty')
    return argv


def sudo_command(command: Sequence[str]) -> tuple[str, ...]:
    argv = _normalize_command(command)
    if is_root():
        logger.debug('Already root, running command without sudo: %s', argv)
        return argv
    if not sudo_available():
        logger.error('sudo unavailable while building privileged command: %s', argv)
        raise CommandNotFoundError(('sudo',))
    return ('sudo', '-E', *argv)


def ensure_sudo_cached(
    *,
    timeout: int = 30,
    cwd: str = '',
    env: Mapping[str, str] | None = None,
    check: bool = True,
) -> CommandResult:
    if is_root():
        logger.debug('Privilege cache refresh skipped because process is already root')
        return CommandResult(('true',), 0, '', '')

    logger.info('Refreshing sudo credential cache')
    return run(('sudo', '-v'), timeout=timeout, cwd=cwd, env=env, check=check)


def run_privileged(
    command: Sequence[str],
    *,
    timeout: int = 30,
    cwd: str = '',
    env: Mapping[str, str] | None = None,
    check: bool = True,
) -> CommandResult:
    argv = _normalize_command(command)
    if is_root():
        logger.info('Running privileged command directly as root: %s', argv)
        return run(argv, timeout=timeout, cwd=cwd, env=env, check=check)

    privileged_command = ('sudo', '-E', *argv)
    logger.info('Running privileged command through sudo: %s', privileged_command)
    try:
        return run(privileged_command, timeout=timeout, cwd=cwd, env=env, check=check)
    except CommandError as exc:
        logger.error('Privileged command failed: %s', exc)
        raise
    except CommandTimeoutError as exc:
        logger.error('Privileged command timed out: %s', exc)
        raise
