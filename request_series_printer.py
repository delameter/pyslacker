# -----------------------------------------------------------------------------
# compact real-time output of iterated/repetitve network requests
# 2022 A. Shavykin <0.delameter@gmail.com>
# -----------------------------------------------------------------------------
from __future__ import annotations

import re
from math import trunc
from typing import Deque

from abstract_singleton import AbstractSingleton
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
        self._progress_bar = BackgroundProgressBar(
            highlight_open_seq=SGRSequence(34, 1),
            regular_open_seq=SGRSequence(),
        )
        self.reinit()

    def reinit(self, requests_estimated: int = 0):
        self._current_line_cache = ''
        self._requests_estimated = requests_estimated
        self._requests_successful = 0
        self._request_num = 0
        self._attempt_num = 0
        self._request_url: str | None = None
        self._response_size_sum: int = 0
        self._render_phase: int = 0
        self._event_msg_queue: Deque[str] = Deque[str]()

        self._request_progress_perc: float | None = None
        self._rpm_cached: float | None = None
        self._minutes_left: int | None = None
        self._rpm_marker_queue: Deque[str] = Deque[str]()

        self._cursor_x: int = 0
        self._cursor_y_estim: int = 0

        self._progress_bar.reset()
        self._progress_bar.update(source_str='', indicator_size=5, indent_size=0)

    def update_statistics(self, response_ok: bool, size_b: int, rpm: float | None):
        if response_ok:
            self._response_size_sum += size_b
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
        self._print(f"Data provider: {SGRRegistry.FMT_BLUE}{self._request_url}{SGRRegistry.FMT_RESET}")
        self._persist_line()

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
        self._render()
        self._render_phase = 2

    def on_request_completion(self, request_ok: bool, status_code: str):
        self._reset_line()
        if not request_ok:
            self._print(f'Request #{self._request_num} resulted in HTTP Code {status_code}')
            self._persist_line()
        self._render(request_ok, status_code)
        self._render_phase = 2

    def before_sleeping(self, delay_sec: float):
        self.print_event(f'Waiting for {delay_sec:.2f}s{self.INDENT}', once=True)

    def sleep_iterator(self, seconds_left: float):
        # get last line from cache (the one that is currently visible),
        # find indicator placeholder and overwrite current line:
        self._print('\r' + re.sub(
            r'^(.+?#\d+\S*\s*[@R](?:\033\[[0-9;]*m)?\s*)(@)',
            lambda m: f'{m.group(1)}{SGRSequence(36, 1)}W{SGRRegistry.FMT_RESET}'
                      if trunc(seconds_left) % 2 == 0
                      else f'{m.group(1)} ',
            self._current_line_cache), cache=False)
        pass

    def after_sleeping(self):
        self._current_line_cache = ''

    def on_post_request_delay_update(self, delta_sign: int = None):
        if not delta_sign:
            fmt = SGRRegistry.FMT_CYAN
            marker = '&'
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

    # @ TODO solve "waiting" problem - pre-render / priority
    def print_event(self, event_msg: str, once: bool = False):
        event_msgs = [event_msg] * (1 if once else self.EVENT_TTL)
        self._event_msg_queue.extendleft(event_msgs)

    # -----------------------------------------------------------------------------

    def _render(self, request_ok: bool = False, status_code: str | None = None):
        introducer = '>' if self._cursor_y_estim % 2 == 0 else ' '
        self._print(f'{SGRSequence(97)!s}{introducer:<1s}{SGRRegistry.FMT_RESET} ')

        self._render_request_id()
        self._render_request_status(status_code, request_ok)
        self._render_progress_bar()
        self._render_eta()
        self._render_rpm()
        self._render_size()

        if len(self._event_msg_queue):
            self._print(f'{SGRSequence(37)}'
                        f'{self._event_msg_queue.popleft()}'
                        f'{SGRRegistry.FMT_RESET}{self.INDENT}')

    # -----------------------------------------------------------------------------
    # render phase 0

    def _render_request_id(self):
        request_tpl = '#{:d}'.format(self._request_num)

        marker_placeholder = '@'
        attempt_fmt = ''
        attempt_marker = marker_placeholder
        if self._attempt_num > 1:
            attempt_fmt = f'{SGRRegistry.FMT_RED}{SGRRegistry.FMT_BOLD}'
            attempt_marker = f'R'
        wait_marker = marker_placeholder

        self._print(f'{SGRSequence(1, 97)}' +
                    f'{request_tpl:s}' +
                    f'{SGRRegistry.FMT_RESET}' +
                    f'{attempt_fmt}' +
                    f'{attempt_marker:>2s}' +
                    f'{SGRRegistry.FMT_RESET if attempt_fmt else ""}' +
                    f'{wait_marker:>2s}'
                    )

    def _render_request_status(self, status_code: str | None, request_ok: bool, skipped: bool = False):
        status_str = 'N/A'
        status_fmt = SGRRegistry.FMT_HI_YELLOW
        status_pad_len = len(self.INDENT)
        if status_code:
            status_str = f'{status_code:3s}'
            if len(status_str) > 3:
                status_pad_len = max(0, status_pad_len - (len(status_str) - 3))
            if request_ok:
                status_fmt = SGRRegistry.FMT_GREEN
            else:
                status_fmt = SGRRegistry.FMT_RED
        if skipped:
            status_str = 'skip'
            status_fmt = SGRRegistry.FMT_RESET

        self._print(f'{self.INDENT:.{status_pad_len}s}' +
                    f'{status_fmt}{status_str}{SGRRegistry.FMT_RESET}'
                    f'{self.INDENT}')

    def _render_progress_bar(self):
        if self._progress_available:
            progress_tpl = "{:<4f}%"
            self._progress_bar.update(source_str=progress_tpl.format(AutoFloat(self._request_progress_perc)),
                                      ratio=self._request_progress_perc / 100)
            progress_str = self._progress_bar.format()
        else:
            progress_str = f'{SGRSequence(37)!s}--- %{SGRRegistry.FMT_RESET!s}'

        self._print(f'{progress_str}' +
                    f'{self.INDENT}')

    def _render_idle_bar(self):
        idle_len = self.PROGRESS_BAR_SIZE + 4
        idle_cursor_idx = (self._cursor_y_estim % (idle_len + 1))
        idle_str = ' ' * idle_cursor_idx + '*' + ' ' * (idle_len - idle_cursor_idx - 1)
        self._progress_bar.update(source_str=f'{idle_str:.{idle_len}s}', ratio=1, indicator_size=idle_len,
                                  indent_size=0)
        self._print(f'{self._progress_bar.format()}' +
                    f'{self.INDENT}')

    def _render_eta(self):
        eta_str = re.sub(r'\S', '-', fmt_time_delta(10 * 60))
        eta_fmt = SGRSequence(37)
        if self._eta_available:
            eta_fmt = ''
            eta_str = fmt_time_delta(self._minutes_left * 60).strip()

        self._print(f'{eta_fmt!s}ETA {eta_str:<6s}{self.INDENT}{SGRRegistry.FMT_RESET}')

    def _render_rpm(self):
        rpm_numf = "{:>4f}"
        rpm_str = re.sub(r'\d', '-', rpm_numf.format(AutoFloat(10.00)))
        rpm_fmt = ''

        if self._rpm_available:
            rpm_prefix = ' '
            if len(self._rpm_marker_queue) > 0:
                rpm_prefix = self._rpm_marker_queue.popleft()
            rpm_str = rpm_numf.format(AutoFloat(self._rpm_cached)).strip()
            rpm_str = ('*' + rpm_str).rjust(5).replace('*', rpm_prefix)
        else:
            rpm_fmt = f'{SGRSequence(37)}'

        self._print(f'{rpm_fmt}{rpm_str:>5s}{SGRRegistry.FMT_RESET} {rpm_fmt}RPM{SGRRegistry.FMT_RESET}{self.INDENT}')

    def _render_size(self):
        size_str = fmt_sizeof(self._response_size_sum)
        self._print(f'{size_str:>8s}{self.INDENT}')

    # -----------------------------------------------------------------------------
    # low-level output

    def _print(self, s: str, cache: bool = True):
        if cache:
            self._current_line_cache += s
        s = s.replace('@', ' ')
        print(s, end='', flush=True)

        no_esq_input = SGRRegistry.remove_sgr_seqs(s)
        self._cursor_x += len(no_esq_input)
        self._render_phase = 1

    def _persist_line(self):
        print('\n', end='')
        self._current_line_cache = ''
        self._cursor_x = 0
        self._cursor_y_estim += 1
        self._render_phase = 0

    def _reset_line(self):
        print('\r' + ' ' * get_terminal_width(), end='')
        print('\r', end='')
        self._current_line_cache = ''
        self._cursor_x = 0
        self._cursor_y_estim += 1
        self._render_phase = 0

    @property
    def _progress_available(self) -> bool:
        return self._request_progress_perc is not None and self._request_progress_perc > 0

    @property
    def _eta_available(self) -> bool:
        return self._minutes_left is not None

    @property
    def _rpm_available(self) -> bool:
        return self._rpm_cached is not None and self._rpm_cached > 0


# @ WIP
class ResponseResult:
    def __init__(self, ok: bool, status: str, fmt: str):
        self._ok: bool = ok
        self._status: str = status  # <HTTP CODE> | N/A | file | skip
        self._fmt: str = fmt

    @property
    def ok(self) -> bool:
        return self._ok

    @property
    def status(self) -> str:
        return self._status

    @property
    def fmt(self) -> str:
        return self._fmt


class ResponseResultRegistry:
    HTTP_OK = ResponseResult(True, '200', SGRRegistry.FMT_GREEN)
    HTTP_ERROR = ResponseResult(False, '400', SGRRegistry.FMT_RED)
