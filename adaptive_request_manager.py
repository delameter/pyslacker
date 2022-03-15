# -----------------------------------------------------------------------------
# empiristic request rate adjuster
# 2022 A. Shavykin <0.delameter@gmail.com>
# -----------------------------------------------------------------------------
from __future__ import annotations

from argparse import Namespace
from math import isclose
from time import time, sleep
from typing import List, Callable

from requests import Response

from abstract_singleton import AbstractSingleton
from logger import Logger
from request_series_printer import RequestSeriesPrinter


class AdaptiveRequestManager(AbstractSingleton):
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

    @classmethod
    def _construct(cls) -> AdaptiveRequestManager:
        return AdaptiveRequestManager(cls._create_key)

    def __init__(self, _key=None):
        super().__init__(_key)
        self.request_series_printer = RequestSeriesPrinter.get_instance()
        self.logger = Logger().get_instance()

        self._post_req_delay: float = 0
        self._successive_req_num: int
        self._samples: List[float] = []   # in seconds
        self._rpm: float
        self._rpm_allowed_to_increase: bool = True

        self._delay_adjustment_enabled = True
        self._rpm_max: float|None = None  # None = disabled
        self.reinit()

    def reinit(self):
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

    def perform_retriable_request(self, request_fn: Callable) -> Response|None:
        attempt_num = 0
        while attempt_num <= AdaptiveRequestManager.RETRY_MAX_NUM:
            attempt_num += 1
            self.request_series_printer.before_request_attempt(attempt_num)
            try:
                response: Response = request_fn()
            except Exception as e:
                self.on_request_failure(attempt_num, f'{e!s}')
                self.logger.error(f'{e!s}', silent=True)
                continue

            self.on_request_completion(response)
            if not response.ok and response.status_code == 429:
                retry_after_sec = float(response.headers["Retry-After"])
                self.on_rate_limited_request_fail(retry_after_sec)
                continue
            return response

        self.logger.error('Max retry amount exceeded')
        return None

    def on_request_failure(self, attempt_num: int, msg: str):
        self.request_series_printer.on_request_failure(msg)

        delay = self._get_progressing_delay_on_failure(attempt_num)
        self.request_series_printer.before_sleeping(delay, 'transport failure')

        self._successive_req_num = 0
        self._sleep(delay)
        self.request_series_printer.after_sleeping()

    def on_request_completion(self, response: Response):
        # COMPLETED, NOT SUCCEEDED (can be 429, 404 etc)
        self.request_series_printer.update_statistics(response.ok, len(response.content), self._rpm)
        self.request_series_printer.on_request_completion(response.status_code, response.ok)

        if len(self._samples) >= self.SAMPLES_MAX_LEN:
            self._samples.pop()
        self._samples.insert(0, time())
        if len(self._samples) > 5:
            self._rpm = 60 * len(self._samples) / (self._samples[0] - self._samples[-1])

        self._optimize_flow()

    def on_rate_limited_request_fail(self, retry_after_sec: float):
        self._stabilize_flow(retry_after_sec)

        self.request_series_printer.before_sleeping(retry_after_sec, 'rate limited')
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
        self.request_series_printer.on_post_request_delay_update(
            new_value=self._post_req_delay,
            delta_sign=delta/abs(delta),
        )

    def _sleep(self, seconds: float):
        while seconds > 1:
            self.request_series_printer.sleep_iterator(seconds)
            seconds -= 1
            sleep(1)
        sleep(seconds)

    def _apply_rpm_limit(self):
        if not self._rpm:
            return  # not enough data yet
        #@wip
        pass

    @property
    def rpm(self) -> float|None:
        if isclose(0.0, self._rpm, abs_tol=1e-03):
            return None
        return self._rpm

    @property
    def minutes_without_failures(self) -> float:
        return self._successive_req_num / 60
