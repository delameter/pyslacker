# -----------------------------------------------------------------------------
# simple logger with buffering control
# 2022 A. Shavykin <0.delameter@gmail.com>
# -----------------------------------------------------------------------------
from __future__ import annotations

import re
import sys
import time
from datetime import datetime
from io import FileIO
from typing import Optional

from sgr import SGRRegistry


class Logger:
    CR_LF_REGEX = re.compile(r'[\r\n]+')

    _instance: Logger = None

    @classmethod
    def get_instance(cls, require_new: bool = False):
        if not cls._instance:
            cls._instance = cls()
        elif require_new:
            raise RuntimeError('Already instantiated')
        return cls._instance

    def __init__(self):
        self.id = hash(self)
        super().__init__()

        self._buf = ''
        self._fileio: Optional[FileIO] = None

        self._open_io()
        self.debug(f'Created logger instance')

    def log(self, text: str, level: str = 'info', buffered: bool = False):
        if buffered:
            self._buf += text
            return
        if not self._fileio or self._fileio.closed:
            print(f'ERROR: Log file pointer is null or file closed: {self._fileio.name if self._fileio else None}')

        dt, micro = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f").rsplit('.', 1)
        print(f'[{dt}.{micro:.3s}] {level.upper()}: {self._buf + text}',
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

    def _get_current_file_name(self) -> str:
        return time.strftime("./log/log.%Y-%m-%d.log", time.gmtime())

    def _open_io(self):
        log_filename = self._get_current_file_name()
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
