# -----------------------------------------------------------------------------
# empiristic request rate adjuster
# 2022 A. Shavykin <0.delameter@gmail.com>
# -----------------------------------------------------------------------------
from __future__ import annotations

from argparse import Namespace
from math import isclose
from time import time, sleep
from typing import List

from requests import Response

from abstract_singleton import AbstractSingleton
from request_series_printer import RequestSeriesPrinter


class AdaptiveRequestManager(AbstractSingleton):
    RETRY_MAX_NUM = 20
    SAMPLES_MAX_LEN = 60
    STABILIZING_THRESHOLD_MIN = 1.5  # starts to decrease delay after THRESHOLD minutes without rate limit errors

    DeLAY_POST_MIN_SEC = 0.0
    DELAY_POST_REQUEST_INITIAL_SEC = DeLAY_POST_MIN_SEC
    DELAY_POST_REQUEST_INCREASE_STEP_SEC = .20
    DELAY_POST_REQUEST_DECREASE_STEP_SEC = .10
    # exponential, but at the same time small and slow at start:
    DELAY_TRANSPORT_FAILURE_SEC = [0.5] + [pow(1.2, i) + 10 * x for i, x in enumerate(range(0, RETRY_MAX_NUM))]
    DELAY_TRANSPORT_FAILURE_STATIC_SEC = 30  # if disabled via arguments

    @classmethod
    def _construct(cls) -> AdaptiveRequestManager:
        return AdaptiveRequestManager(cls._create_key)

    def __init__(self, _key=None):
        super().__init__(_key)
        self.request_series_printer = RequestSeriesPrinter.get_instance()

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

    def on_transport_error(self, attempt_num: int, exception_str: str):
        # printer always first! because terminal render happens while main thread is
        # idle - e.g. while "sleep()" is running. if you invoke printer after sleep,
        # you'll probably miss some output - it will be overwrite by next line
        self.request_series_printer.on_transport_error(exception_str)

        delay = self._get_progressing_delay_on_failure(attempt_num)
        self.request_series_printer.before_sleeping(delay, 'transport failure')
        self.on_request_failure()
        self._sleep(delay)
        self.request_series_printer.after_sleeping()

    def on_request_completion(self, response: Response):
        # i think it's time to implement event bus ... @TODO
        self.request_series_printer.on_request_completion(
            response.status_code, response.ok, len(response.content), self.rpm
        )

        if len(self._samples) >= self.SAMPLES_MAX_LEN:
            self._samples.pop()
        self._samples.insert(0, time())
        if len(self._samples) > 5:
            self._rpm = 60 * len(self._samples) / (self._samples[0] - self._samples[-1])

        if not self._delay_adjustment_enabled:
            return
        self._apply_rpm_limit()
        self._successive_req_num += 1
        if self.current_time_wout_fail_minutes >= self.STABILIZING_THRESHOLD_MIN and self._rpm_allowed_to_increase:
            self._shift_pre_request_delay(-1 * self.DELAY_POST_REQUEST_DECREASE_STEP_SEC)
            self._successive_req_num = 0
        sleep(self._post_req_delay)

    def on_request_failure(self):
        self._successive_req_num = 0

    def on_rate_limited_request_fail(self, retry_after_sec: float):
        if self._delay_adjustment_enabled:
            delta_with_response = retry_after_sec - self._post_req_delay
            if delta_with_response >= self.DELAY_POST_REQUEST_INCREASE_STEP_SEC:
                self._shift_pre_request_delay(delta_with_response - self.DELAY_POST_REQUEST_INCREASE_STEP_SEC)
            else:
                self._shift_pre_request_delay(self.DELAY_POST_REQUEST_INCREASE_STEP_SEC)
            self._successive_req_num = 0

        self.request_series_printer.before_sleeping(retry_after_sec, 'rate limited')
        self._sleep(retry_after_sec + self._post_req_delay)

    def _get_progressing_delay_on_failure(self, attempt_num: int) -> float:
        if self._delay_adjustment_enabled:
            return self.DELAY_TRANSPORT_FAILURE_SEC[attempt_num]
        return self.DELAY_TRANSPORT_FAILURE_STATIC_SEC

    def _set_post_req_delay(self, new_value: float):
        new_value = max(self.DeLAY_POST_MIN_SEC, new_value)
        if isclose(self._post_req_delay, new_value, abs_tol=1e-03):
            return
        self._post_req_delay = new_value

    def _shift_pre_request_delay(self, delta: float):
        if delta < 0 and isclose(self.DeLAY_POST_MIN_SEC, self._post_req_delay, abs_tol=1e-03):
            return
        self._set_post_req_delay(self._post_req_delay + delta)
        self.request_series_printer.on_post_request_delay_update(new_value=self._post_req_delay, delta=delta)

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
    def current_time_wout_fail_minutes(self) -> float:
        return self._successive_req_num / 60
