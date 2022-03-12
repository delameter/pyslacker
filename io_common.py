import re
from math import floor, trunc

from sgr import SGRSequence, SGRRegistry


def get_terminal_width():
    try:
        import shutil as _shutil
        return _shutil.get_terminal_size().columns - 2
    except ImportError:
        return 80


def fmt_sizeof(num, separator=" ", unit_suffix="b"):
    # result max length: 9
    # 6 chars for number, 2 chars for default unit, 1 for separator
    num = max(0, num)
    for unit_idx, unit in enumerate(["", "k", "M", "G", "T", "P", "E", "Z"]):
        decimal_places = 2
        if unit_idx == 0:
            decimal_places = 0

        if num < 1024.0:
            if num >= 1000:
                decimal_places = 1
            num_fmt = "{:6.%df}" % decimal_places
            return num_fmt.format(num) + f"{separator}{unit}{unit_suffix}"
        num /= 1024.0
    return str(num)


time_units = [
    {"name": "sec", "in_next": 60},
    {"name": "min", "in_next": 60},
    {"name": "hr", "in_next": 24},
    {"name": "day", "in_next": 30},
    {"name": "mon", "in_next": 12},
    {"name": "yr", "in_next": None},
]


def fmt_time_delta(seconds: float) -> str:
    # result max length is 6 for all reasonable values:
    # 13 sec, 17 min, 5h 23m, 11 hr, 23 day, 2 mon, 3m 21d, 11 yr
    # returns exponential form (2e+27) for ridiculously big values
    seconds = max(0.0, seconds)
    num = seconds
    unit_idx = 0
    prev_frac = ''

    while unit_idx < len(time_units):
        unit = time_units[unit_idx]
        unit_name = unit["name"]
        next_unit_ratio = unit["in_next"]

        if num < 1:
            return f'<1 {unit_name:3s}'
        elif not next_unit_ratio:
            return f'{num:>7.1e}'
        elif num < 10 and (unit_name == "hr" or unit_name == "mon"):
            return f'{num:1.0f}{unit_name[0]:1s} {prev_frac:<3s}'
        elif num < next_unit_ratio:
            return f'{num:>2.0f} {unit_name:<3s}'
        else:
            next_num = floor(num / next_unit_ratio)
            prev_frac = '{:d}{:1s}'.format(floor(num - (next_num * next_unit_ratio)), unit_name[0])
            num = next_num
            unit_idx += 1
            continue


class AutoFloat(float):
    RE_MAX_LEN = re.compile(r'(\d+)f$')

    def __format__(self, format_spec: str) -> str:
        converted_spec = self._convert_a_to_f(format_spec)
        f = super().__format__(converted_spec)
        return f

    def _convert_a_to_f(self, format_spec: str) -> str:
        max_len_match = self.RE_MAX_LEN.findall(format_spec)
        if not max_len_match:
            raise RuntimeError('Max length should be specified as in float format, e.g. ":4f"')

        max_decimals_len = 2
        max_len = int(max_len_match[0])

        integer_len = len(str(trunc(self)))
        decimals_and_point_len = min(max_decimals_len + 1, max_len - integer_len)

        decimals_len = 0
        if decimals_and_point_len >= 2:  # dot without decimals make no sense
            decimals_len = decimals_and_point_len - 1
        dot_str = f'.{decimals_len!s}'

        return self.RE_MAX_LEN.sub(f'{max_len}{dot_str}f', format_spec)


class BackgroundProgressBar:
    def __init__(self, source_str: str, ratio: float, highlight_open_seq: SGRSequence = None, regular_open_seq: SGRSequence = None):
        super().__init__()
        self._source_str: str = source_str
        self._highlight_len: int = 0
        self._highlight_open_seq: SGRSequence = highlight_open_seq
        self._regular_open_seq: SGRSequence = regular_open_seq

        percents = max(0.0, min(1.0, ratio))
        self._highlight_len = max(0, floor(percents * len(self._source_str)))

    def format(self):
        highlight_part = self._source_str[:self._highlight_len]
        regular_part = self._source_str[self._highlight_len:]
        left_part_len = self._highlight_len + 1  # paddings
        right_part_len = len(self._source_str) - self._highlight_len + 1

        return f'{self._highlight_open_seq}' + \
               f'{highlight_part:>{left_part_len}s}' + \
               f'{SGRRegistry.FMT_RESET}{self._regular_open_seq}' + \
               f'{regular_part:<{right_part_len}s}' + \
               f'{SGRRegistry.FMT_RESET}'

    def __str__(self):
        return self._source_str
