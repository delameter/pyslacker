from math import floor


def trunc_int(f: float):
    return f - floor(abs(f))
