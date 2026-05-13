"""
Centralized logging system for Boot Repair application.

Provides:
- Rotating file handlers (boot-repair.log, error.log)
- Console output with formatting
- System information logging at startup
- Function tracing decorator
- Global exception capture
- Log export functionality
"""

from __future__ import annotations

import datetime
import functools
import logging
import logging.handlers
import os
import platform
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable, TypeVar

# Type variable for decorator
F = TypeVar('F', bound=Callable[..., Any])


class _AppFilter(logging.Filter):
    """Filter to add custom fields to log records."""
    
    def filter(self, record: logging.LogRecord) -> bool:
        return True


def _ensure_logs_dir() -> Path:
    """Create logs directory if it doesn't exist."""
    logs_dir = Path.home() / '.cache' / 'boot-repair' / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def _get_log_format() -> str:
    """Return the log format string."""
    return '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s'


def _get_log_time_format() -> str:
    """Return the time format for logs."""
    return '%Y-%m-%d %H:%M:%S'


def setup_logger(debug: bool = False) -> None:
    """
    Configure centralized logging for Boot Repair.
    
    Args:
        debug: If True, set logging level to DEBUG. Otherwise, use INFO.
    """
    logs_dir = _ensure_logs_dir()
    
    # Remove existing handlers
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Set root logger level
    level = logging.DEBUG if debug else logging.INFO
    root_logger.setLevel(level)
    
    # Create formatter
    formatter = logging.Formatter(
        fmt=_get_log_format(),
        datefmt=_get_log_time_format()
    )
    
    # Add console handler (all levels)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # Add rotating file handler for all logs
    all_logs_file = logs_dir / 'boot-repair.log'
    all_logs_handler = logging.handlers.RotatingFileHandler(
        filename=all_logs_file,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=5
    )
    all_logs_handler.setLevel(level)
    all_logs_handler.setFormatter(formatter)
    root_logger.addHandler(all_logs_handler)
    
    # Add rotating file handler for errors only
    error_logs_file = logs_dir / 'error.log'
    error_handler = logging.handlers.RotatingFileHandler(
        filename=error_logs_file,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=5
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    root_logger.addHandler(error_handler)
    
    # Log startup information
    logger = get_logger(__name__)
    logger.info('='*70)
    logger.info('Boot Repair Application Started')
    logger.info('='*70)
    log_system_info(logger)
    logger.info('='*70)
    
    # Setup global exception handlers
    _setup_exception_handlers(logger)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a module.
    
    Args:
        name: Module name (typically __name__)
    
    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)


def log_system_info(logger: logging.Logger) -> None:
    """
    Public helper for logging system information.
    
    Args:
        logger: The logger instance to use for system info output.
    """
    _log_system_info(logger)


def _log_system_info(logger: logging.Logger) -> None:
    """Log system information at startup."""
    try:
        logger.info(f'Python version: {sys.version.split()[0]}')
        logger.info(f'OS: {sys.platform}')
        logger.info(f'Distribution: {_get_linux_distribution()}')
        logger.info(f'Architecture: {platform.machine()}')
        logger.info(f'Processor count: {os.cpu_count()}')
        logger.info(f'Display backend: {_detect_graphics_backend()}')
        logger.info(f'UID: {os.getuid()}')
        logger.info(f'Current user: {os.getenv("USER", "unknown")}')
        logger.info(f'Interpreter: {sys.executable}')
        logger.info(f'Working directory: {os.getcwd()}')
        logger.info(f'Home directory: {Path.home()}')
        
        # Log cache/logs directory
        logs_dir = _ensure_logs_dir()
        logger.info(f'Logs directory: {logs_dir}')
        
        # Log locale
        logger.info(f'Locale: {os.getenv("LANG", "not set")}')
        
        # Log Python path (first 3 entries)
        pythonpath_entries = sys.path[:3]
        for i, path in enumerate(pythonpath_entries):
            logger.debug(f'PYTHONPATH[{i}]: {path}')
            
    except Exception as exc:
        logger.warning(f'Error logging system info: {exc}')


def _get_linux_distribution() -> str:
    """Get Linux distribution name."""
    try:
        result = subprocess.run(
            ['lsb_release', '-ds'],
            capture_output=True,
            text=True,
            timeout=5,
            check=False
        )
        if result.returncode == 0:
            return result.stdout.strip().strip('"')
    except Exception:
        pass
    
    # Fallback
    if os.path.exists('/etc/os-release'):
        try:
            with open('/etc/os-release', 'r') as f:
                for line in f:
                    if line.startswith('PRETTY_NAME='):
                        return line.split('=', 1)[1].strip().strip('"')
        except Exception:
            pass
    
    return platform.system()


def _detect_graphics_backend() -> str:
    """Detect graphics backend (X11, Wayland, or none)."""
    if os.environ.get('WAYLAND_DISPLAY'):
        return 'Wayland'
    if os.environ.get('DISPLAY'):
        return 'X11'
    return 'none'


def _setup_exception_handlers(logger: logging.Logger) -> None:
    """Setup global exception handlers."""
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        
        logger.critical(
            'Uncaught exception',
            exc_info=(exc_type, exc_value, exc_traceback)
        )
    
    def handle_thread_exception(args):
        logger.critical(
            f'Uncaught exception in thread {args.thread.name}',
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback)
        )
    
    sys.excepthook = handle_exception
    threading.excepthook = handle_thread_exception


def log_command_execution(
    command: str | tuple,
    start_time: float | None = None,
    returncode: int | None = None,
    stdout: str | None = None,
    stderr: str | None = None,
    timeout: int | None = None
) -> None:
    """
    Log subprocess command execution details.
    
    Args:
        command: Command string or tuple
        start_time: Start time from time.time()
        returncode: Process return code
        stdout: Standard output (truncated if needed)
        stderr: Standard error (truncated if needed)
        timeout: Timeout value if applicable
    """
    logger = get_logger('core.execution')
    
    if isinstance(command, (list, tuple)):
        cmd_str = ' '.join(str(c) for c in command)
    else:
        cmd_str = str(command)
    
    if start_time is None:
        # Log command start
        logger.debug(f'Executing command: {cmd_str}')
    else:
        # Log command completion
        duration = time.time() - start_time
        
        if returncode is not None and returncode != 0:
            logger.warning(f'Command failed: {cmd_str} (exit code: {returncode}, duration: {duration:.2f}s)')
            if stderr:
                truncated_stderr = stderr[:500] + '...' if len(stderr) > 500 else stderr
                logger.warning(f'stderr: {truncated_stderr}')
        else:
            logger.debug(f'Command completed: {cmd_str} (duration: {duration:.2f}s, exit code: {returncode})')
        
        if timeout is not None:
            logger.debug(f'Command timeout was set to: {timeout}s')


def trace(func: F) -> F:
    """
    Decorator to trace function entry, exit, and timing.
    
    Logs:
    - Function entry with arguments
    - Function exit with return value (if not None)
    - Duration in milliseconds
    - Exceptions raised
    
    Usage:
        @trace
        def my_function(arg1, arg2):
            return arg1 + arg2
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        logger = get_logger(func.__module__)
        func_name = func.__qualname__
        
        # Log entry
        args_repr = [repr(a) for a in args]
        kwargs_repr = [f'{k}={v!r}' for k, v in kwargs.items()]
        signature = ', '.join(args_repr + kwargs_repr)
        logger.debug(f'→ {func_name}({signature})')
        
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            duration_ms = (time.time() - start_time) * 1000
            
            # Log exit with result
            result_repr = repr(result) if result is not None else 'None'
            if len(result_repr) > 100:
                result_repr = result_repr[:97] + '...'
            
            logger.debug(f'← {func_name}() → {result_repr} ({duration_ms:.2f}ms)')
            return result
            
        except Exception as exc:
            duration_ms = (time.time() - start_time) * 1000
            logger.error(
                f'✗ {func_name}() raised {type(exc).__name__} ({duration_ms:.2f}ms)',
                exc_info=True
            )
            raise
    
    return wrapper  # type: ignore


def export_logs_archive(output_dir: str | Path | None = None) -> Path:
    """
    Create a ZIP archive with diagnostics including logs, system info, and stack traces.
    
    Args:
        output_dir: Directory to save the archive. Defaults to current directory.
    
    Returns:
        Path to the created archive
    """
    import shutil
    import zipfile
    
    if output_dir is None:
        output_dir = Path.cwd()
    else:
        output_dir = Path(output_dir)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logs_dir = _ensure_logs_dir()
    timestamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    archive_name = f'boot-repair-diagnostics-{timestamp}.zip'
    archive_path = output_dir / archive_name
    
    logger = get_logger(__name__)
    logger.info(f'Exporting diagnostics to: {archive_path}')
    
    try:
        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Add log files
            if logs_dir.exists():
                for log_file in logs_dir.glob('*.log*'):
                    arcname = f'logs/{log_file.name}'
                    zf.write(log_file, arcname=arcname)
            
            # Add system info
            system_info_file = output_dir / 'system-info.txt'
            with open(system_info_file, 'w') as f:
                f.write('Boot Repair - System Information Export\n')
                f.write(f'Exported: {datetime.datetime.now().isoformat()}\n')
                f.write('='*70 + '\n\n')
                
                f.write('Python:\n')
                f.write(f'  Version: {sys.version}\n')
                f.write(f'  Executable: {sys.executable}\n\n')
                
                f.write('System:\n')
                f.write(f'  OS: {sys.platform}\n')
                f.write(f'  Distribution: {_get_linux_distribution()}\n')
                f.write(f'  Architecture: {platform.machine()}\n')
                f.write(f'  Hostname: {platform.node()}\n')
                f.write(f'  Processors: {os.cpu_count()}\n\n')
                
                f.write('Environment:\n')
                f.write(f'  User: {os.getenv("USER", "unknown")}\n')
                f.write(f'  UID: {os.getuid()}\n')
                f.write(f'  Home: {Path.home()}\n')
                f.write(f'  CWD: {os.getcwd()}\n')
                f.write(f'  Display: {_detect_graphics_backend()}\n')
                f.write(f'  Locale: {os.getenv("LANG", "not set")}\n')
            
            zf.write(system_info_file, arcname='system-info.txt')
            system_info_file.unlink()
        
        logger.info(f'Diagnostics exported successfully: {archive_path}')
        return archive_path
        
    except Exception as exc:
        logger.error(f'Error exporting diagnostics: {exc}', exc_info=True)
        raise


def get_logs_directory() -> Path:
    """Get the logs directory path."""
    return _ensure_logs_dir()
