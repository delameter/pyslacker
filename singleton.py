# -----------------------------------------------------------------------------
# simple singleton pattern implementation
# 2022 A. Shavykin <0.delameter@gmail.com>
# -----------------------------------------------------------------------------
from __future__ import annotations
from typing import Dict


class Singleton(type):
    _instances: Dict[type, Singleton] = {}

    def __call__(cls, *args, **kwargs):
        cls.get_instance(*args, **kwargs)

    def get_instance(cls, *args, **kwargs) -> Singleton:
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]
