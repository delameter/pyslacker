#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# testing script for request renderer debugging 
# 2022 A. Shavykin <0.delameter@gmail.com>
# -----------------------------------------------------------------------------
import time
from math import copysign
from random import randint
from time import sleep
from typing import cast, Deque

from pyslacker.core.adaptive_request_manager import AdaptiveRequestManager
from pyslacker.core.logger import Logger
from pyslacker.core.req_seq_renderer import RequestSequenceRenderer


class RequestSimulator:
    def __init__(self):
        self.logger = Logger.get_instance()
        self.req_seq_renderer = cast(RequestSequenceRenderer, RequestSequenceRenderer.get_instance())
        self.samples: Deque[float] = Deque[float]()

    def run(self):
        self.simulate_batch(1e-3)
        self.simulate_batch(1.4)

    def sleep_iterator(self, seconds: float):
        while seconds > 1:
            self.req_seq_renderer.sleep_iterator(seconds)
            seconds -= 1
            sleep(1)
        sleep(seconds)

    def simulate_batch(self, inter_req_sleep_sec: float):
        self.req_seq_renderer.reinit(90)
        self.req_seq_renderer.before_paginated_batch(f'IRSI {inter_req_sleep_sec} sec')
        self.samples.clear()

        for request_num in range(1, 101):
            self.samples.appendleft(time.time())
            for attempt_num in range(1, 3):
                self.req_seq_renderer.before_request(request_num)
                self.req_seq_renderer.before_request_attempt(attempt_num)

                if request_num % 33 == 3 and attempt_num == 1:
                    try:
                        raise RuntimeError(f'Sorry Marty, we blew it all #{request_num}')
                    except Exception as e:
                        self.req_seq_renderer.on_request_failure(attempt_num, f'{e!s}')
                        self.logger.error(f'{e!s}', silent=True)

                        on_error_sleep_sec = inter_req_sleep_sec * 5
                        self.req_seq_renderer.before_sleeping(on_error_sleep_sec)
                        self.sleep_iterator(on_error_sleep_sec)
                        self.req_seq_renderer.after_sleeping()
                        continue

                self.req_seq_renderer.update_statistics(True, 16484, AdaptiveRequestManager.compute_rpm(self.samples))
                self.req_seq_renderer.on_request_completion(True, str(randint(200, 209)))

                if request_num % 25 == 0:
                    self.req_seq_renderer.on_post_request_delay_update(
                        int(copysign(1*(request_num-50), request_num-50))
                    )

                if inter_req_sleep_sec < 1:
                    self.req_seq_renderer._queue_manager.iterate(1)
                    self.req_seq_renderer.sleep_iterator(1)
                else:
                    self.sleep_iterator(inter_req_sleep_sec)
                break

        self.req_seq_renderer.after_paginated_batch()


if __name__ == '__main__':
    (RequestSimulator()).run()
