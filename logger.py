# -----------------------------------------------------------------------------
# simple logger with buffering control
# 2022 A. Shavykin <0.delameter@gmail.com>
# -----------------------------------------------------------------------------
from __future__ import annotations

import re
import time
from io import FileIO
from typing import Optional

from abstract_singleton import AbstractSingleton
from sgr import SGRRegistry


class Logger(AbstractSingleton):
    CR_LF_REGEX = re.compile(r'[\r\n]+')

    @classmethod
    def _construct(cls) -> Logger:
        return Logger(cls._create_key)

    def __init__(self, _key=None):
        super().__init__(_key)
        self._buf = ''
        self._fileio: Optional[FileIO] = None

        self._open_io()

    def log_append(self, s: str):
        if not self._fileio:
            return
        s = SGRRegistry.remove_sgr_seqs(s)
        s = self.CR_LF_REGEX.sub('', s)
        self._buf += s

    def log_line(self, s: str):
        self.log_append(s)
        self.flush()

    def flush(self):
        if not self._fileio or not self._buf:
            return
        ts = time.strftime("[%Y-%m-%d %H:%M:%S] ", time.gmtime())
        print(ts + self._buf, file=self._fileio, end='\n', flush=True)
        self._buf = ''

    def error(self, text: str):
        self.log_line(text)

    def _get_current_file_name(self) -> str:
        return time.strftime("./log/log.%Y-%m-%d.log", time.gmtime())

    def _open_io(self):
        log_filename = self._get_current_file_name()
        try:
            self._fileio = open(log_filename, 'a', encoding='utf-8')
        except Exception as e:
            print('WARNING: Opening log file {} failed: {}'.format(log_filename, e))
            self._fileio = None

    def _close_io(self):
        if not self._fileio or not self._buf:
            return
        self._fileio.flush()
        self._fileio.close()
        self._fileio = None
