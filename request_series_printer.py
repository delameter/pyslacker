# -----------------------------------------------------------------------------
# compact real-time output of iterated/repetitve network requests
# 2022 A. Shavykin <0.delameter@gmail.com>
# -----------------------------------------------------------------------------
from __future__ import annotations

import re
from math import trunc
from typing import Deque

from abstract_singleton import AbstractSingleton
from logger import Logger
from sgr import SGRRegistry, SGRSequence
from util.io import fmt_sizeof, fmt_time_delta, AutoFloat, BackgroundProgressBar, get_terminal_width


# noinspection PyAttributeOutsideInit
class RequestSeriesPrinter(AbstractSingleton):
    REQUEST_DELTA_MAX_LEN = 40
    INDENT = 3 * ' '
    PROGRESS_BAR_SIZE = 5
    MARKER_TTL = 3
    EVENT_TTL = 3

    @classmethod
    def _construct(cls) -> RequestSeriesPrinter:
        return RequestSeriesPrinter(cls._create_key)

    def __init__(self, _key=None):
        super().__init__(_key)
        self._logger = Logger.get_instance()
        self._progress_bar = BackgroundProgressBar(
            highlight_open_seq=SGRSequence(34, 40, 1),
            regular_open_seq=SGRSequence(37, 40),
        )
        self.reinit()

    def reinit(self, requests_estimated: int = 0):
        self._requests_estimated = requests_estimated
        self._requests_successful = 0
        self._request_num = 0
        self._attempt_num = 0
        self._request_url: str|None = None
        self._request_size_sum: int = 0
        self._render_phase: int = 0
        self._event_msg_queue: Deque[str] = Deque[str]()

        self._request_progress_perc: float | None = None
        self._rpm_cached: float | None = None
        self._minutes_left: int | None = None
        self._rpm_marker_queue: Deque[str] = Deque[str]()

        self._line_preserve = False
        self._delayed_output_buffer: str = ''
        self._cursor_x: int = 0
        self._cursor_y_estim: int = 0

        self._progress_bar.reset()
        self._progress_bar.update(source_str='-----')

    def update_statistics(self, request_ok: bool, size_b: int, rpm: float|None):
        if request_ok:
            self._request_size_sum += size_b
            self._requests_successful += 1

        if rpm is not None and rpm > 0:
            self._rpm_cached = rpm

        if self._requests_estimated:
            self._request_progress_perc = 100.0 * min(1.0, self._requests_successful / self._requests_estimated)
            if self._rpm_cached:
                self._minutes_left = (self._requests_estimated - self._requests_successful) / self._rpm_cached

    # -----------------------------------------------------------------------------
    # event hanlders

    def before_paginated_batch(self, url: str):
        self._request_url = url
        self._print(f"Current endpoint: {SGRRegistry.FMT_BLUE}{self._request_url}{SGRRegistry.FMT_RESET}",
                    lf_after=True,
                    log=False)

    def after_paginated_batch(self):
        self._persist_line()

    def before_request(self):
        self._request_num += 1

    def before_request_attempt(self, attempt_num: int):
        self._attempt_num = attempt_num

    def on_request_failure(self, msg: str):
        self._reset_line()
        self._print(msg)
        self._persist_line()
        self._render(None, False)

    def on_request_completion(self, status_code: int, request_ok: bool):
        self._reset_line()
        if not request_ok:
            self._print(f'Request #{self._request_num} resulted in HTTP Code {status_code}')
            self._persist_line()
        self._render(status_code, request_ok)

    def before_sleeping(self, delay_sec: float, reason: str = ''):
        pass

    # @TODO: make sure dots are always printed after render phase 0
    def sleep_iterator(self, seconds_left: float):
        if trunc(seconds_left) % 5 == 0:
            self._print(f'.', log=False)

    def after_sleeping(self):
        pass

    def on_post_request_delay_update(self, new_value: float, delta_sign: int = None):
        if not delta_sign:
            fmt = SGRRegistry.FMT_BLUE
            marker = '*'
        elif delta_sign > 0:
            fmt = SGRRegistry.FMT_YELLOW
            marker = '!'
        else:
            fmt = SGRRegistry.FMT_GREEN
            marker = '^'

        self._rpm_marker_queue.extendleft([f'{fmt!s}' +
                                           f'{SGRRegistry.FMT_BOLD!s}' +
                                           f'{marker}' +
                                           f'{SGRSequence(22)!s}'] * self.MARKER_TTL)
        self._log(
            f'Set post-request delay to {new_value:.2f}s',
        )

    # -----------------------------------------------------------------------------

    def _render(self, status_code: int | None, request_ok: bool):
        self._render_request_id()
        self._render_request_status(status_code, request_ok)
        self._render_progress_bar()
        self._render_eta()
        self._render_rpm()
        self._render_size()

        if len(self._event_msg_queue):
            self._print(self._event_msg_queue.popleft() + self.INDENT)

    # -----------------------------------------------------------------------------
    # render phase 0

    def _render_request_id(self):
        request_tpl = '#{:d}'.format(self._request_num)
        if self._attempt_num <= 1:
            attempt_marker = ''
        else:
            attempt_marker = ' R'

        self._print(f'{SGRRegistry.FMT_BOLD}' +
                    f'{request_tpl:>5s}' +
                    f'{SGRRegistry.FMT_RESET}' +
                    f'{SGRRegistry.FMT_HI_YELLOW}' +
                    f'{attempt_marker:2.2s}' +
                    f'{SGRRegistry.FMT_RESET}')

    def _render_request_status(self, status_code: int | None, request_ok: bool):
        status_str = '---'
        status_fmt = SGRRegistry.FMT_YELLOW
        if status_code:
            status_str = f'{status_code:3d}'
            if request_ok:
                status_fmt = SGRRegistry.FMT_GREEN
            else:
                status_fmt = SGRRegistry.FMT_RED

        self._print(f'{self.INDENT:.2s}' +
                    f'{status_fmt}{status_str}{SGRRegistry.FMT_RESET}')

        self._log(f'Request #{self._request_num} attempt {self._attempt_num}:' +
                  f'{status_str} {self._request_url}')

    def _render_progress_bar(self):
        if self._progress_available:
            progress_tpl = "{:<4f}%"
            progress_str = progress_tpl.format(AutoFloat(self._request_progress_perc))
            self._progress_bar.update(source_str=progress_str, ratio=self._request_progress_perc / 100)
        #else:
        #idle_len = self.PROGRESS_BAR_SIZE + 4
        #idle_cursor_idx = (self._cursor_y_estim % (idle_len + 1))
        #idle_str = ' '*idle_cursor_idx + '*' + ' '*(idle_len - idle_cursor_idx - 1)
        #self._progress_bar.update(source_str=f'{idle_str:.{idle_len}s}', ratio=1, indicator_size=idle_len, indent_size=0)

        self._print(f'{self.INDENT:.2s}' +
                    f'{self._progress_bar.format()}' +
                    f'{self.INDENT:.2s}')

    def _render_eta(self):
        eta_str = re.sub(r'\S', '-', fmt_time_delta(10*60))
        eta_fmt = SGRSequence(37)
        if self._eta_available:
            eta_fmt = ''
            eta_str = fmt_time_delta(self._minutes_left * 60).strip()

        self._print(f'{eta_fmt!s}ETA {eta_str:<6s}{self.INDENT}{SGRRegistry.FMT_RESET}')

    def _render_rpm(self):
        rpm_numf = "{:>4f}"
        rpm_str = re.sub(r'\d', '-', rpm_numf.format(AutoFloat(10.12)))

        if self._rpm_available:
            rpm_prefix = ' '
            if len(self._rpm_marker_queue) > 0:
                rpm_prefix = self._rpm_marker_queue.popleft()
            rpm_str = rpm_numf.format(AutoFloat(self._rpm_cached)).strip()
            rpm_str = ('*' + rpm_str).rjust(5).replace('*', rpm_prefix)

        self._print(f'{rpm_str:>5s}{SGRRegistry.FMT_RESET} RPM{self.INDENT:.2s}')

    def _render_size(self):
        size_str = fmt_sizeof(self._request_size_sum)
        self._print(f'{size_str:>8s}{self.INDENT}')

    # -----------------------------------------------------------------------------
    # low-level output

    def _print_event(self, event_msg: str, once: bool = False):
        self._event_msg_queue.extendleft([event_msg] * (1 if once else self.EVENT_TTL))

    def _print(self, s: str, lf_after: bool = False, log: bool = False):
        print(s, end='', flush=True)
        no_esq_input = SGRRegistry.remove_sgr_seqs(s)
        self._cursor_x += len(no_esq_input)

        if log:
            self._log(no_esq_input)
        if lf_after:
            print('\n', end='')
            self._cursor_x = 0
            self._cursor_y_estim += 1
        self._render_phase = 1

    def _persist_line(self):
        self._print('', lf_after=True)
        self._render_phase = 0

    def _reset_line(self):
        print('\r' + ' ' * get_terminal_width(), end='')
        print('\r', end='')
        self._cursor_x = 0
        self._cursor_y_estim += 1
        self._render_phase = 0

    @property
    def _progress_available(self) -> bool:
        return self._requests_estimated is not None and self._requests_estimated > 0

    @property
    def _eta_available(self) -> bool:
        return self._minutes_left is not None

    @property
    def _rpm_available(self) -> bool:
        return self._rpm_cached is not None and self._rpm_cached > 0

    def _log(self, s: str):
        self._logger.info(s, silent=True)
