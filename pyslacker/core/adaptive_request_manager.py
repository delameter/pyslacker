# -----------------------------------------------------------------------------
# empiristic request rate adjuster
# 2022 A. Shavykin <0.delameter@gmail.com>
# -----------------------------------------------------------------------------
from __future__ import annotations

from argparse import Namespace
from math import isclose
from time import time, sleep
from typing import Callable, Tuple, cast, Sequence, Deque

from requests import Response

from pyslacker.core.logger import Logger
from pyslacker.core.req_seq_renderer import RequestSequenceRenderer
from pyslacker.core.request_flow_interface import RequestFlowInterace
from pyslacker.core.singleton import Singleton


# noinspection PyAttributeOutsideInit
class AdaptiveRequestManager(RequestFlowInterace, metaclass=Singleton):
    RETRY_MAX_NUM = 20
    SAMPLES_MAX_LEN = 60
    OPTIMIZING_THRESHOLD_MIN = 1.5  # starts to decrease delay after THRESHOLD minutes without rate limit errors

    DELAY_POST_MIN_SEC = 0.0
    DELAY_POST_REQUEST_INITIAL_SEC = DELAY_POST_MIN_SEC
    DELAY_POST_REQUEST_STABILIZE_SEC = .20
    DELAY_POST_REQUEST_OPTIMIZE_SEC = .10
    # exponential, but at the same time small and slow at start:
    DELAY_TRANSPORT_FAILURE_SEC = [0.5] + [pow(1.2, i) + 10 * x for i, x in enumerate(range(0, RETRY_MAX_NUM))]
    DELAY_TRANSPORT_FAILURE_STATIC_SEC = 30  # if disabled via arguments

    @staticmethod
    def compute_rpm(samples: Sequence[float]) -> float|None:
        if len(samples) > 5:  # @TODO rolling average?
            return 60 * len(samples) / (samples[0] - samples[-1])
        return None

    def __init__(self):
        self._req_seq_renderer: RequestSequenceRenderer = cast(RequestSequenceRenderer, RequestSequenceRenderer.get_instance())
        self._logger = Logger.get_instance()

        self._post_req_delay: float = 0
        self._req_num: int
        self._successive_req_num: int
        self._samples: Deque[float] = Deque[float]()   # in seconds
        self._rpm: float
        self._rpm_allowed_to_increase: bool = True

        self._delay_adjustment_enabled = True
        self._rpm_max: float|None = None  # None = disabled

        self.reinit()

    def reinit(self, requests_estimated: int = None):
        self._req_seq_renderer.reinit(requests_estimated)

        self._req_num = 0
        self._successive_req_num = 0
        self._samples.clear()
        self._rpm = 0.0

        if self._delay_adjustment_enabled:
            self._set_post_req_delay(self.DELAY_POST_REQUEST_INITIAL_SEC)
        else:
            self._post_req_delay = 0.0

    def apply_app_args(self, args: Namespace):
        if args.A:
            self._delay_adjustment_enabled = False
        if args.x:
            self._rpm_max = max(0.0, args.x)
            if isclose(0, self._rpm_max, abs_tol=1e-03):
                self._rpm_max = None

    def before_paginated_batch(self, url: str):
        self._req_seq_renderer.before_paginated_batch(url)

    def after_paginated_batch(self):
        self._req_seq_renderer.after_paginated_batch()
        pass

    def perform_retriable_request(self,
                                  request_fn: Callable[[int], Tuple[Response, int]],
                                  completion_fn: Callable[[], str] = None) -> Response:
        self._req_num += 1
        self._req_seq_renderer.before_request(self._req_num)

        attempt_num = 0
        while attempt_num <= AdaptiveRequestManager.RETRY_MAX_NUM:
            attempt_num += 1
            self._req_seq_renderer.before_request_attempt(attempt_num)
            try:
                (response, content_size) = request_fn(attempt_num)
            except Exception as e:
                self.on_request_failure(attempt_num, f'{e!s}')
                self._logger.error('[ReqManager] ' + f'{e!s}', silent=True)
                continue

            self.on_request_completion(response, content_size)
            if not response.ok and response.status_code == 429:
                retry_after_sec = float(response.headers["Retry-After"])
                self.on_rate_limited_request_fail(retry_after_sec)
                continue

            if completion_fn:
                self._req_seq_renderer.print_event(completion_fn(), persist=False)
            return response

        raise RuntimeError('Max retry amount exceeded')

    def on_request_failure(self, attempt_num: int, msg: str):
        self._req_seq_renderer.on_request_failure(attempt_num, msg)

        delay = self._get_progressing_delay_on_failure(attempt_num)
        self._req_seq_renderer.before_sleeping(delay)

        self._successive_req_num = 0
        self._sleep(delay)
        self._req_seq_renderer.after_sleeping()

    def on_request_completion(self, response: Response, response_size: int):
        # COMPLETED, NOT SUCCEEDED (can be 429, 404 etc)
        response_ok = response.ok
        status_code = str(response.status_code)

        self._req_seq_renderer.update_statistics(response_ok, response_size, self._rpm)
        self._req_seq_renderer.on_request_completion(response_ok, status_code)

        if len(self._samples) >= self.SAMPLES_MAX_LEN:
            self._samples.pop()
        self._samples.appendleft(time())
        self._rpm = self.compute_rpm(self._samples)

        self._optimize_flow()

    def on_rate_limited_request_fail(self, retry_after_sec: float):
        self._stabilize_flow(retry_after_sec)

        self._req_seq_renderer.before_sleeping(retry_after_sec)
        self._sleep(retry_after_sec + self._post_req_delay)

    def _stabilize_flow(self, retry_after_sec: float):  # increase the delay
        if not self._delay_adjustment_enabled:
            return

        delta_with_response = retry_after_sec - self._post_req_delay
        if delta_with_response >= self.DELAY_POST_REQUEST_STABILIZE_SEC:
            self._shift_pre_request_delay(delta_with_response - self.DELAY_POST_REQUEST_STABILIZE_SEC)
        else:
            self._shift_pre_request_delay(self.DELAY_POST_REQUEST_STABILIZE_SEC)
        self._successive_req_num = 0

    def _optimize_flow(self):  # decrease the delay
        if not self._delay_adjustment_enabled:
            return
        self._apply_rpm_limit()
        self._successive_req_num += 1
        if self.minutes_without_failures >= self.OPTIMIZING_THRESHOLD_MIN and self._rpm_allowed_to_increase:
            self._shift_pre_request_delay(-1 * self.DELAY_POST_REQUEST_OPTIMIZE_SEC)
            self._successive_req_num = 0
        sleep(self._post_req_delay)

    def _get_progressing_delay_on_failure(self, attempt_num: int) -> float:
        if self._delay_adjustment_enabled:
            return self.DELAY_TRANSPORT_FAILURE_SEC[attempt_num]
        return self.DELAY_TRANSPORT_FAILURE_STATIC_SEC

    def _set_post_req_delay(self, new_value: float):
        new_value = max(self.DELAY_POST_MIN_SEC, new_value)
        if isclose(self._post_req_delay, new_value, abs_tol=1e-03):
            return
        self._post_req_delay = new_value

    def _shift_pre_request_delay(self, delta: float):
        if delta < 0 and isclose(self.DELAY_POST_MIN_SEC, self._post_req_delay, abs_tol=1e-03):
            return
        self._set_post_req_delay(self._post_req_delay + delta)

        self._req_seq_renderer.on_post_request_delay_update(int(delta / abs(delta)))
        self._req_seq_renderer.print_event(f'Set post-request delay to {self._post_req_delay:.2f}s', persist=True)
        self._logger.info(f'[ReqManager] Set post-request delay to {self._post_req_delay:.2f}s', silent=True)

    def _sleep(self, seconds: float):
        while seconds > 1:
            self._req_seq_renderer.sleep_iterator(seconds)
            seconds -= 1
            sleep(1)
        sleep(seconds)

    def _apply_rpm_limit(self):
        if not self._rpm:
            return  # not enough data yet
        # @TODO
        pass

    @property
    def rpm(self) -> float|None:
        if isclose(0.0, self._rpm, abs_tol=1e-03):
            return None
        return self._rpm

    @property
    def minutes_without_failures(self) -> float:
        return self._successive_req_num / 60
