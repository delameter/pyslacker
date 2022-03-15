# -----------------------------------------------------------------------------
# compact real-time output of iterated/repetitve network requests
# 2022 A. Shavykin <0.delameter@gmail.com>
# -----------------------------------------------------------------------------
from __future__ import annotations

import re
from datetime import datetime
from math import trunc

from abstract_singleton import AbstractSingleton
from logger import Logger
from sgr import SGRRegistry, SGRSequence
from util.io import fmt_sizeof, fmt_time_delta, AutoFloat, BackgroundProgressBar, get_terminal_width


# noinspection PyAttributeOutsideInit


class RequestSeriesPrinter(AbstractSingleton):
    REQUEST_DELTA_MAX_LEN = 40
    INDENT = 3 * ' '
    PROGRESS_BAR_SIZE = 5

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
        self._request_params: dict|None = None
        self._request_size_sum: int = 0

        self._request_progress_perc: float | None = None
        self._rpm_cached: float | None = None
        self._minutes_left: int | None = None
        self._arm_event_str: str | None = None
        self._arm_event_ttl: int = 0

        self._line_preserve = False
        self._delayed_output_buffer: str = ''
        self._cursor_x: int = 0
        self._cursor_y_estim: int = 0

        self._progress_bar.reset()

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
        self._print('', lf_after=True, log=False)

    def before_request(self, params: dict):
        self._request_num += 1
        self._request_params = params

    def before_request_attempt(self, attempt_num: int):
        self._attempt_num = attempt_num

    def on_request_failure(self, msg: str):
        self._reset_line()
        self._print_request(None, False, msg)
        self._preserve_current_line()
        self._reset_line()

    def on_request_completion(self, status_code: int, request_ok: bool):
        self._reset_line()
        self._print_request(status_code, request_ok, None)

        if request_ok:
            self._on_request_success()
        else:
            self._preserve_current_line()

    def _on_request_success(self):
        if self._request_num % 1000 == 0:
            self._print_event(
                datetime.now().strftime("[%-e-%b-%y %T]"),
                append=True, log=False
            )

    def before_sleeping(self, delay_sec: float, reason: str = ''):
        self._print_event(
            f'Waiting for {SGRRegistry.FMT_BOLD}{delay_sec:.2f}{SGRRegistry.FMT_RESET}s ({reason.lower()})',
            append=False, log=True
        )

    def after_sleeping(self):
        self._reset_line()

    def on_post_request_delay_update(self, new_value: float, delta_sign: int = None):
        if not delta_sign:
            fmt = {SGRRegistry.FMT_BOLD}
            msg = '='
        elif delta_sign > 0:
            fmt = f'{SGRRegistry.FMT_RED!s}{SGRRegistry.FMT_BOLD!s}'
            msg = '@'
        else:
            fmt = f'{SGRRegistry.FMT_GREEN!s}{SGRRegistry.FMT_BOLD!s}'
            msg = '^'

        self._arm_event_str = f'[{fmt}{msg}{SGRRegistry.FMT_RESET}]'
        self._arm_event_ttl = 3

        self._log(
            f'Set post-request delay to {new_value:.2f}s',
        )

    def sleep_iterator(self, seconds_left: float):
        if trunc(seconds_left) % 10 == 0:
            self._print('.', log=False)

    # -----------------------------------------------------------------------------
    # output

    def _print_request(self, status_code: int|None, request_ok: bool, failure_msg: str|None):
        self._print_request_id()
        self._print_request_status(status_code, request_ok)
        self._print_request_statictics(failure_msg)

        if self._arm_event_ttl > 0:
            self._arm_event_ttl -= 1
        elif self._arm_event_ttl == 0:
            self._arm_event_str = None

    def _print_request_id(self):
        request_numf = '#{:d}'.format(self._request_num)
        if self._attempt_num <= 1:
            attempt_char = ''
        elif self._attempt_num < 10:
            attempt_char = f' {self._attempt_num!s:.1s}'
        else:
            attempt_char = ' +'

        self._print(f'{SGRRegistry.FMT_BOLD}' +
                    f'{request_numf:>5s}' +
                    f'{SGRRegistry.FMT_HI_YELLOW}' +
                    f'{attempt_char:2.2s}' +
                    f'{SGRRegistry.FMT_RESET}')

    def _print_request_status(self, status_code: int|None, request_ok: bool):
        status_str = '---'
        fmt_status = SGRRegistry.FMT_YELLOW
        if status_code:
            status_str = f'{status_code:3d}'
            if request_ok:
                fmt_status = SGRRegistry.FMT_GREEN
            else:
                fmt_status = SGRRegistry.FMT_RED

        self._print(f'{self.INDENT:.2s}' +
                    f'{fmt_status}{status_str}{SGRRegistry.FMT_RESET}')

        self._log(f'Request #{self._request_num} attempt {self._attempt_num}:' +
                  f'{status_str} {self._request_url} {self._request_params!s}')

    def _print_request_statictics(self, failure_msg: str | None):
        self._print(f'{self.INDENT:.2s}' +
                    f'{self._progress_bar.format()}' +
                    f'{self.INDENT:.2s}')

        if failure_msg is not None:
            self._print(failure_msg)
            return

        progress_fmt = "{:<4f}%"
        progress_str = re.sub(r'\d', '-', progress_fmt.format(AutoFloat(100.0)))
        rpm_fmt = "{:>4f}"
        rpm_num_str = re.sub(r'\d', '-', rpm_fmt.format(AutoFloat(1000.0)))
        rpm_title = 'RPM'
        eta_str = re.sub(r'\S', '-', fmt_time_delta(10*60))
        size_str = fmt_sizeof(self._request_size_sum)

        if self._rpm_available:
            rpm_num_str = rpm_fmt.format(AutoFloat(self._rpm_cached))

        if self._arm_event_str:
            rpm_title = self._arm_event_str

        if self._progress_available:
            progress_str = progress_fmt.format(AutoFloat(self._request_progress_perc))
            self._progress_bar.update(source_str=progress_str, ratio=self._request_progress_perc / 100)
        else:
            self._progress_bar.update(source_str=('--- -' if self._cursor_y_estim % 4 else ''), ratio=0)
        #else:
        #idle_len = self.PROGRESS_BAR_SIZE + 4
        #idle_cursor_idx = (self._cursor_y_estim % (idle_len + 1))
        #idle_str = ' '*idle_cursor_idx + '*' + ' '*(idle_len - idle_cursor_idx - 1)
        #self._progress_bar.update(source_str=f'{idle_str:.{idle_len}s}',
        #                          ratio=1,
        #                          indicator_size=idle_len,
        #                          indent_size=0)

        eta_fmt = ''
        #eta_fmt = SGRSequence(2)
        if self._eta_available:
            eta_str = fmt_time_delta(self._minutes_left * 60).strip()

        self._print(f'{eta_fmt!s}ETA {eta_str:<6s}{self.INDENT:.1s}{SGRRegistry.FMT_RESET}' +
                    f'{rpm_num_str:>5s} {rpm_title:<3s}{self.INDENT}' +
                    f'{size_str:>8s}{self.INDENT:.1s}')
        self._log(f'PROGRESS {progress_str} SIZE {size_str} RPM {rpm_num_str} ETA {eta_str}')

    def _print_event(self, event_msg: str, append: bool, log: bool = True):
        if append:
            self._preserve_current_line()
        else:
            self._reset_line()

        self._print(event_msg + self.INDENT, log=log)

    def _print(self, s: str, lf_after: bool = False, log: bool = False):
        self._print_delayed()
        print(s, end='', flush=True)
        no_esq_input = SGRRegistry.remove_sgr_seqs(s)
        self._cursor_x += len(no_esq_input)

        if log:
            self._log(no_esq_input)
        if lf_after:
            print('\n', end='')
            self._cursor_x = 0
            self._cursor_y_estim += 1

    def _print_delayed(self):
        if not self._delayed_output_buffer:
            return
        print(self._delayed_output_buffer, end='')
        self._delayed_output_buffer = ''

    def _preserve_current_line(self):
        self._line_preserve = True

    def _reset_line(self):
        self._print_delayed()
        if self._line_preserve:
            self._print('', lf_after=True)
            self._line_preserve = False
        else:
            print('\r' + ' ' * get_terminal_width(), end='')
            print('\r', end='')
            self._cursor_x = 0
        self._cursor_y_estim += 1

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

