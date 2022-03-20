# 2022 A. Shavykin <0.delameter@gmail.com>
# ----------------------------------------
from abc import ABCMeta, abstractmethod


class RequestFlowInterace(metaclass=ABCMeta):
    @abstractmethod
    def __init__(self): raise NotImplementedError

    def before_paginated_batch(self, url: str): pass
    def after_paginated_batch(self): pass
    def before_request(self, request_num: int): pass
    def before_request_attempt(self, attempt_num: int): pass
    def on_request_failure(self, attempt_num: int, msg: str): pass
    def on_request_completion(self, request_ok: bool, status_code: str): pass
    def before_sleeping(self, delay_sec: float): pass
    def sleep_iterator(self, seconds_left: float): pass
    def after_sleeping(self): pass
