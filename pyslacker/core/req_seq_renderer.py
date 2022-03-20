# -----------------------------------------------------------------------------
# real-time compact output of repetitve network requests
# 2022 A. Shavykin <0.delameter@gmail.com>
# -----------------------------------------------------------------------------
from __future__ import annotations

import time
from builtins import super
from math import isclose
from typing import Deque, TypeVar

from pyslacker.core.logger import Logger
from pyslacker.core.request_flow_interface import RequestFlowInterace
from pyslacker.core.singleton import Singleton
from pyslacker.util.io import *


class ExpiringFragment:
    def __init__(self, text: str, duration_sec: float = 3):
        self._text: str = text
        self._duration_sec: float = duration_sec

        self.iterate(0)

    def __call__(self, *args, **kwargs) -> str:
        return self._text

    def __str__(self) -> str:
        return self._text

    def __repr__(self) -> str:
        return f'[{self._duration_sec:.1f}] {self._text}{SGRRegistry.FMT_RESET}'

    def iterate(self, frame_duration_sec: float) -> bool:
        self._duration_sec = max(0.0, self._duration_sec - frame_duration_sec)
        return self.visible

    @property
    def visible(self) -> bool:
        return not isclose(.0, self._duration_sec, abs_tol=1e-3)


Renderable = TypeVar('Renderable', ExpiringFragment, str)


class RenderQueue(Deque[Renderable]):
    def __init__(self):
        super(RenderQueue, self).__init__()
        self._prev_frame_time_ns = time.time_ns()

    def __bool__(self) -> bool:
        return len(self) > 0

    def __repr__(self):
        return f'[{(self._prev_frame_time_ns - time.time_ns()) / 1e9:.2f}s] ' + '; '.join([f.__repr__() for f in self])

    def iterate(self, pop=False, simulate_duration_sec: float = None) -> Renderable|None:
        cur_frame_time_ns = time.time_ns()
        frame_duraion_sec = (cur_frame_time_ns - self._prev_frame_time_ns)/1e9
        self._prev_frame_time_ns = cur_frame_time_ns
        if simulate_duration_sec:
            frame_duraion_sec = simulate_duration_sec

        if not len(self):
            return

        if isinstance(self[0], ExpiringFragment):
            visible_next_frame = self[0].iterate(frame_duraion_sec)
            if pop and not visible_next_frame:
                return self.popleft()

        return self[0]


class RenderQueueManager:
    def __init__(self):
        self._queues: List[RenderQueue] = []

    def create_queue(self) -> RenderQueue:
        self._queues.append(RenderQueue())
        return self._queues[-1]

    def iterate(self, simulate_duration_sec: float = None):
        for queue in self._queues:
            queue.iterate(simulate_duration_sec=simulate_duration_sec)

    def clear(self):
        for queue in self._queues:
            queue.clear()


# noinspection PyAttributeOutsideInit
class RequestSequenceRenderer(RequestFlowInterace, metaclass=Singleton):
    REQUEST_DELTA_MAX_LEN = 40

    INDENT = 3 * ' '
    PROGRESS_BAR_SIZE = 5
    MARKER_TTL = 3

    def __init__(self):
        self._logger = Logger.get_instance()
        self._progress_bar = BackgroundProgressBar(
            highlight_open_seq=SGRSequence(34, 1),
            regular_open_seq=SGRSequence(),
        )
        self._queue_manager: RenderQueueManager = RenderQueueManager()
        self._rpm_marker_queue: RenderQueue = self._queue_manager.create_queue()
        self.reinit()

    def reinit(self, requests_estimated: int = None):
        self._current_line_cache = ''
        self._render_phase: int = 0

        self._requests_estimated: int|None = requests_estimated
        self._requests_successful = 0
        self._request_num = 0
        self._attempt_num = 0
        self._request_url: str|None = None
        self._response_size_sum: int = 0

        self._request_progress_perc: float | None = None
        self._rpm_cached: float | None = None
        self._minutes_left: int | None = None

        self._cursor_x: int = 0
        self._cursor_y_estim: int = 0

        self._queue_manager.clear()
        self._progress_bar.reset()
        self._progress_bar.update(source_str='', indicator_size=5, indent_size=0)

    def update_statistics(self, response_ok: bool, size_b: int, rpm: float | None):
        stats_log_msg = []

        if response_ok:
            self._response_size_sum += size_b
            self._requests_successful += 1
            stats_log_msg.append(f'size total: {self._response_size_sum}')

        if rpm is not None and rpm > 0:
            self._rpm_cached = rpm
            stats_log_msg.append(f'rpm: {self._rpm_cached:.3f}')

        if self._requests_estimated:
            self._request_progress_perc = 100.0 * min(1.0, self._requests_successful / self._requests_estimated)
            stats_log_msg.append(f'progress: {self._request_progress_perc:.3}')

            if self._rpm_cached:
                self._minutes_left = (self._requests_estimated - self._requests_successful) / self._rpm_cached
                stats_log_msg.append(f'min left: {self._minutes_left:.3}')

        if stats_log_msg:
            self._logger.debug('[ReqRenderer] ' + '; '.join(stats_log_msg), silent=True)

    @property
    def _progress_available(self) -> bool:
        return self._request_progress_perc is not None and self._request_progress_perc > 0

    @property
    def _eta_available(self) -> bool:
        return self._minutes_left is not None

    @property
    def _rpm_available(self) -> bool:
        return self._rpm_cached is not None and self._rpm_cached > 0

    # -----------------------------------------------------------------------------
    # event hanlders

    def before_paginated_batch(self, url: str):
        self._request_url = url
        data_provider_str = f"Data provider: {SGRRegistry.FMT_BLUE}{self._request_url}{SGRRegistry.FMT_RESET}"
        self._print(data_provider_str)
        self._persist_line()
        self.print_separator()

    def after_paginated_batch(self):
        self._persist_line()

    def before_request(self, request_num: int):
        self._request_num = request_num

    def before_request_attempt(self, attempt_num: int):
        self._attempt_num = attempt_num

    def on_request_failure(self, attempt_num: int, msg: str):
        self.print_event(f'{SGRRegistry.FMT_RED}Error: {msg}{SGRRegistry.FMT_RESET}', persist=True)

    def on_request_completion(self, request_ok: bool, status_code: str):
        self._reset_line()
        if not request_ok:
            self._print(f'Request #{self._request_num} resulted in HTTP code {status_code}, retrying...')
            self._persist_line()
        self._render(request_ok, status_code)

    def before_sleeping(self, delay_sec: float):
        self.print_event(f'Waiting for {delay_sec:.2f}s{self.INDENT}')

    def sleep_iterator(self, seconds_left: float):
        # get last line from cache (the one that is currently visible),
        # replace indicator placeholder and overwrite current line:
        current_line_waiting = re.sub(
            r'^(.+?#\d+\S*\s*[@R](?:\033\[[0-9;]*m)?\s*)(@)',
            lambda m: f'{m.group(1)}{SGRSequence(36, 1)}W{SGRRegistry.FMT_RESET}'
            if trunc(seconds_left) % 2 == 0
            else f'{m.group(1)} ',
            self._current_line_cache)

        self._print('\r' + current_line_waiting, cache=False)

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

        self._rpm_marker_queue.append(ExpiringFragment(
            f'{fmt!s}'
            f'{SGRRegistry.FMT_BOLD!s}'
            f'{marker}'
            f'{SGRSequence(22)!s}', self.MARKER_TTL))

    # @ TODO queue to allow events in render phase 0/1
    def print_event(self, event_msg: str, persist=False, log=True):
        if log:
            self._logger.debug('[ReqRenderer] ' + event_msg, silent=True)

        if persist:
            self._reset_line()
            self._print(event_msg)
            self._persist_line()
            self._render()
            return

        if self._render_phase != 2:
            return
        self._print(f'{SGRSequence(37)}'
                    f'{event_msg}'
                    f'{SGRRegistry.FMT_RESET}{self.INDENT}')

    # @ TODO check how to determine if terminal doesn't support selected char and use fallbacks
    def print_separator(self):
        self._print('─' * min(80, get_terminal_width()))
        self._persist_line()

    # -----------------------------------------------------------------------------

    def _render(self, request_ok: bool = False, status_code: str = None):
        self._queue_manager.iterate()

        self._render_introducer()
        self._render_request_id()
        self._render_request_status(status_code, request_ok)
        self._render_progress_bar()
        self._render_eta()
        self._render_rpm()
        self._render_size()

        self._render_phase = 2
        if self._request_num % 10 == 0:
            self._persist_line()

    # -----------------------------------------------------------------------------
    # render phase 0

    def _render_introducer(self):
        introducer = '>' if self._cursor_y_estim % 2 == 0 else ' '
        self._print(f'{SGRSequence(97)!s}{introducer:<1s}{SGRRegistry.FMT_RESET} ')

    def _render_request_id(self):
        request_tpl = '#{:d}'.format(self._request_num)

        marker_placeholder = '@'
        attempt_fmt = ''
        attempt_marker = marker_placeholder
        if self._attempt_num > 1:
            attempt_fmt = f'{SGRRegistry.FMT_RED}{SGRRegistry.FMT_BOLD}'
            attempt_marker = f'R'
        wait_marker = marker_placeholder

        self._print(f'{SGRSequence(1, 97)}'
                    f'{request_tpl:>3s}'
                    f'{SGRRegistry.FMT_RESET}'
                    f'{attempt_fmt}'
                    f'{attempt_marker:>2s}'
                    f'{SGRRegistry.FMT_RESET if attempt_fmt else ""}'
                    f'{wait_marker:>2s}')

    def _render_request_status(self, status_code: str | None, request_ok: bool, skipped: bool = False):
        status_str = 'n/a'
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

        self._print(f'{self.INDENT:.{status_pad_len}s}'
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

        self._print(f'{progress_str}'
                    f'{self.INDENT}')

    def _render_idle_bar(self):
        idle_len = self.PROGRESS_BAR_SIZE + 4
        idle_cursor_idx = (self._cursor_y_estim % (idle_len + 1))
        idle_str = ' ' * idle_cursor_idx + '*' + ' ' * (idle_len - idle_cursor_idx - 1)
        self._progress_bar.update(source_str=f'{idle_str:.{idle_len}s}', ratio=1, indicator_size=idle_len,
                                  indent_size=0)
        self._print(f'{self._progress_bar.format()}'
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
            rpm_prefix = self._rpm_marker_queue.iterate(pop=True) or ''
            rpm_str = rpm_numf.format(AutoFloat(self._rpm_cached)).strip()
            rpm_str = ('*' + rpm_str).rjust(5).replace('*', str(rpm_prefix))
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
        # @ TODO can be optimized - by listening for resize events (signals?)
        print('\r' + ' ' * get_terminal_width(), end='')
        print('\r', end='')

        self._current_line_cache = ''
        self._cursor_x = 0
        self._cursor_y_estim += 1
        self._render_phase = 0
