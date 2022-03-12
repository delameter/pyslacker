# -----------------------------------------------------------------------------
# compact real-time output of iterated/repetitve network requests
# 2022 A. Shavykin <0.delameter@gmail.com>
# -----------------------------------------------------------------------------
from __future__ import annotations

import re
from math import trunc

from abstract_singleton import AbstractSingleton
from io_common import fmt_sizeof, fmt_time_delta, AutoFloat, BackgroundProgressBar,  get_terminal_width
from logger import Logger
from sgr import SGRRegistry, SGRSequence


class RequestSeriesPrinter(AbstractSingleton):
    REQUEST_DELTA_MAX_LEN = 40
    INDENT = 3 * ' '

    @classmethod
    def _construct(cls) -> RequestSeriesPrinter:
        return RequestSeriesPrinter(cls._create_key)

    def __init__(self, _key=None):
        super().__init__(_key)
        self._logger = Logger.get_instance()
        self.reinit()

    def reinit(self, requests_estimated: int = 0):
        self._requests_estimated = requests_estimated
        self._requests_successful = 0
        self._request_num = 0
        self._attempt_num = 0
        self._request_url: str|None = None
        self._request_params: dict|None = None
        self._request_size_sum: int = 0
        self._line_preserve = False
        self._delayed_output_buffer: str = ''
        self._cursor_x: int = 0
        self._cursor_y_estim: int = 0

    # -----------------------------------------------------------------------------
    # event hanlders

    def before_paginated_batch(self, url: str):
        self._request_url = url
        self._print(f"Endpoint: {SGRRegistry.FMT_BLUE}{self._request_url}{SGRRegistry.FMT_RESET}", lf_after=True)

    def after_paginated_batch(self):
        self._print('', lf_after=True)

    def before_request(self, params: dict):
        self._request_num += 1
        self._request_params = params

    def before_request_attempt(self, attempt_num: int):
        self._attempt_num = attempt_num

    def on_transport_error(self, exception_str: str):
        self.on_request_failure()
        self._print(exception_str)
        self._preserve_current_line()

    def on_request_completion(self, status_code: int, request_ok: bool, size_b: int, rpm: float|None):
        if request_ok:
            self._request_size_sum += size_b
            self._requests_successful += 1

        self._hard_line_reset()
        self._print_request_id()
        self._print_request_status(status_code, request_ok, size_b)
        self._print_statictics(rpm)
        self._print_line_ending()

        if not request_ok:
            self._preserve_current_line()

    def on_request_failure(self):
        self._hard_line_reset()
        self._print_request_id()
        self._print_request_status(None, False)

    def before_sleeping(self, delay_sec: float, reason: str = ''):
        self._hard_line_reset()
        self._print(
            "Waiting for {fmt}{delay:.2f}{fmt_close}s ({reason}){indent}".format(
                indent=self.INDENT,
                fmt=SGRRegistry.FMT_BOLD,
                fmt_close=SGRRegistry.FMT_RESET,
                delay=delay_sec,
                reason=reason.lower()
            ))

    def after_sleeping(self):
        self._hard_line_reset()

    def on_post_request_delay_update(self, new_value: float = None, delta: float = None):
        if not new_value and not delta:
            return
        if not delta:
            fmt = SGRRegistry.FMT_BOLD
        elif delta > 0:
            fmt = SGRRegistry.FMT_YELLOW
        else:
            fmt = SGRRegistry.FMT_GREEN

        self._print('Set post-request delay to {0}{1:.2f}s{2}{3}'.format(
            fmt, new_value, SGRRegistry.FMT_RESET, self.INDENT
        ))
        self._preserve_current_line()

    def sleep_iterator(self, seconds_left: float):
        if trunc(seconds_left) % 10 == 0:
            self._print('.', log=False)

    # -----------------------------------------------------------------------------
    # output

    def _print_request_id(self):
        request_numf = '#{:d}'.format(self._request_num)
        if self._attempt_num <= 1:
            attempt_char = ''
        elif self._attempt_num < 10:
            attempt_char = f' {self._attempt_num!s:.1s}'
        else:
            attempt_char = ' *'

        self._print(f'{SGRRegistry.FMT_BOLD}' +
                    f'{request_numf:>5s}' +
                    f'{attempt_char:2.2s}' +
                    f'{SGRRegistry.FMT_RESET}'
                    )

    def _print_request_status(self, status_code: int|None, request_ok: bool, size_b: int = 0):
        status_str = '---'
        fmt_status = SGRRegistry.FMT_YELLOW
        if status_code:
            status_str = f'{status_code:3d}'
            if request_ok:
                fmt_status = SGRRegistry.FMT_GREEN
            else:
                fmt_status = SGRRegistry.FMT_RED

        self._print('{indent:.2s}{fmt_status}{status}{fmtr}{indent:.2s}'.format(
            indent=self.INDENT,
            fmt_status=fmt_status,
            fmtr=SGRRegistry.FMT_RESET,
            status=status_str
        ))
        self._log(f'Request #{self._request_num} attempt {self._attempt_num}:' +
                  f'{status_str} {size_b} {self._request_url} {self._request_params!s}'
                  )

    def _print_statictics(self, rpm: float|None):
        progress_fmt = "{:<4f}%"
        rpm_fmt = "{:>5f}"

        progress_percents = 0
        progress_bar = re.sub(r'\d', '-', progress_fmt.format(AutoFloat(100.0)))
        rpm_str = re.sub(r'\d', '-', rpm_fmt.format(AutoFloat(1000.0)))

        eta = ''
        eta_label = 'ETA'
        rpm_label = 'RPM'
        if self._requests_estimated:
            progress_percents = AutoFloat(100.0 * min(1.0, self._requests_successful/self._requests_estimated))
            progress_bar = progress_fmt.format(progress_percents)
            requests_left = self._requests_estimated - self._requests_successful
            if rpm is not None:
                rpm_str = rpm_fmt.format(AutoFloat(rpm))
                minutes_left = requests_left / rpm
                eta = fmt_time_delta(minutes_left*60).strip()

        if not eta:
            eta = '-- ---'

        size_str = fmt_sizeof(self._request_size_sum)

        progress_bar = BackgroundProgressBar(
            progress_bar, progress_percents / 100, SGRSequence(34, 40, 1), SGRSequence(37, 40)
        )
        self._print(f'{progress_bar.format()}{self.INDENT:.2s}' +
                    f'{eta_label:4s}{eta:6s}{self.INDENT}' +
                    f'{rpm_str:<6s}{rpm_label:4s}{self.INDENT}' +
                    f'{size_str:>8s}{self.INDENT:.1s}')
        self._log(f'PROGRESS {progress_bar!s} SIZE {size_str} RPM {rpm_str} ETA {eta}')

    def _print_line_ending(self):
        liveness_indicator_active_len = (self._cursor_y_estim % (len(self.INDENT) + 1))
        self._print(self.INDENT[:liveness_indicator_active_len])
        self._delayed_output_buffer += (self.INDENT[liveness_indicator_active_len:])

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

    def _hard_line_reset(self):
        self._print_delayed()
        if self._line_preserve:
            self._print('', lf_after=True)
            self._line_preserve = False
        else:
            print('\r' + ' ' * get_terminal_width(), end='')
            print('\r', end='')
            self._cursor_x = 0
        self._cursor_y_estim += 1

    def _log(self, s: str):
        self._logger.log_line(s)
