# 2022 A. Shavykin <0.delameter@gmail.com>
# ----------------------------------------
from __future__ import annotations

import json
import os
import signal
import sys
import traceback

from pyslacker.core.logger import Logger


# noinspection PyMethodMayBeStatic
class ExceptionHandler:
    def __init__(self, logger: Logger|None = None):
        if not logger:
            logger = Logger.get_instance()
        self._logger = logger
        signal.signal(signal.SIGINT, lambda signum, f: self.on_signal(signum, f))

    def on_signal(self, s, f):
        self._logger.debug('Terminating (SIGINT)')
        sys.exit(2)

    def handle(self, e: Exception):
        self._write(e)
        if os.environ.get('EXCEPTION_TRACE', None):
            self._write_with_trace(e)
        print()
        sys.exit(1)

    def _write(self, e: Exception):
        self._logger.error(str(e))

    def _write_with_trace(self, e: Exception):
        tb_splitted = traceback.format_exception(e.__class__, e, e.__traceback__)
        tb_lines = [line.rstrip('\n') for line in tb_splitted]

        self._logger.error(json.dumps(tb_splitted, ensure_ascii=False), silent=True)
        print("\n".join(tb_lines), file=sys.stderr)

