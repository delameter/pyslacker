# -----------------------------------------------------------------------------
# simple singleton pattern implementation
# 2022 A. Shavykin <0.delameter@gmail.com>
# -----------------------------------------------------------------------------
from __future__ import annotations
import abc
abstractstaticmethod = abc.abstractmethod


class AbstractSingleton(metaclass=abc.ABCMeta):
    _instance: AbstractSingleton = None
    _create_key = object()

    @abstractstaticmethod
    def _construct() -> AbstractSingleton:
        raise RuntimeError('Cannot instantiate abstract class')

    @classmethod
    def get_instance(cls):
        if not cls._instance:
            cls._instance = cls._construct()
        return cls._instance

    def __init__(self, _key=None):
        if _key != self._create_key:
            raise RuntimeError("Cannot instantiate singleton directly, use {}.get_instance()".format(self.__class__.__name__))
