# 2022 A. Shavykin <0.delameter@gmail.com>
# ----------------------------------------
from __future__ import annotations

import re
import sys
import time
from datetime import datetime
from io import FileIO
from typing import Optional

from pyslacker.util.io import SGRRegistry


class Logger:
    CR_LF_REGEX = re.compile(r'[\r\n]+')
    PREFIX = 'PYSLACKER'

    _instance: Logger = None

    @classmethod
    def get_instance(cls, require_new: bool = False, *args, **kwargs):
        if cls._instance and not require_new:
            return cls._instance
        instance = cls(*args, **kwargs)
        if not cls._instance:
            cls._instance = instance
        return instance

    def __init__(self, filename: str|None = None):
        self.id = hash(self)
        super().__init__()

        self._buf = ''
        self._fileio: Optional[FileIO] = None

        self._open_io(filename)
        self.debug(f'Created logger instance')

    def log(self, text: str, level: str = 'info', buffered: bool = False):
        if buffered:
            self._buf += text
            return
        if not self._fileio or self._fileio.closed:
            print(f'ERROR: Log file pointer is null or file closed: {self._fileio.name if self._fileio else None}')

        dt, micro = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f").rsplit('.', 1)
        print(f'{dt}.{micro:.3s} {self.PREFIX} {level.upper()}: {self._buf + text}',
              file=self._fileio, end='\n', flush=True)
        self._buf = ''

    def debug(self, text: str, silent: bool = True):
        if not silent:
            print(f'{SGRRegistry.FMT_CYAN!s}{text}{SGRRegistry.FMT_RESET!s}', file=sys.stdout)
        self.log(text, 'debug')

    def info(self, text: str, silent: bool = False):
        if not silent:
            print(text, file=sys.stdout)
        self.log(text, 'info')

    def warn(self, text: str, silent: bool = False):
        if not silent:
            print(f'{SGRRegistry.FMT_YELLOW!s}{text}{SGRRegistry.FMT_RESET!s}', file=sys.stdout)
        self.log(text, 'warn')

    def error(self, text: str, silent: bool = False):
        if not silent:
            print(f'{SGRRegistry.FMT_RED!s}{text}{SGRRegistry.FMT_RESET!s}', file=sys.stderr)
        self.log(text, 'error')

    def _get_default_filename(self) -> str:
        return time.strftime("./log/log.%Y-%m-%d.log", time.gmtime())

    def _open_io(self, filename: str|None):
        log_filename = filename or self._get_default_filename()
        try:
            self._fileio = open(log_filename, 'a', encoding='utf-8')
        except Exception as e:
            print('WARNING: Opening log file {} failed: {}'.format(log_filename, e))
        self.debug(f'Opened log file for appending: {log_filename}')

    def close_io(self):
        if not self._fileio or not self._buf:
            return
        self._fileio.flush()
        self._fileio.close()
        self._fileio = None
