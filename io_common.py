# -----------------------------------------------------------------------------
# i/o helper class and methods
# 2022 A. Shavykin <0.delameter@gmail.com>
# -----------------------------------------------------------------------------
import re
from math import floor, trunc

from sgr import SGRSequence, SGRRegistry


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
    # returns exponential form (2e+27) if input is ridiculously big
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


def fmt_sizeof(num, separator=' ', unit='b'):
    # result max length: 8
    # 5 chars for number, 2 chars for unit, 1 for separator (with default options)
    num = max(0, num)
    for unit_idx, unit_prefix in enumerate(['', 'k', 'M', 'G', 'T', 'P', 'E', 'Z']):
        unit_full = f'{unit_prefix}{unit}'
        if num >= 1024.0:
            num /= 1024.0
            continue
        if unit_idx == 0:
            num_str = f'{num:5d}'
        else:
            num_str = f'{AutoFloat(num):5f}'
        return f'{num_str}{separator}{unit_full}'

    return f'{num!s}{unit}'


def get_terminal_width():
    try:
        import shutil as _shutil
        return _shutil.get_terminal_size().columns - 2
    except ImportError:
        return 80


class AutoFloat(float):
    # class for fixed-length float values printing
    # dynamically adjusts decimal digits amount to fill string as much as possible

    # usage:
    # f'{AutoFloat(1234.56):4f}'   ->   1235
    # f'{AutoFloat( 123.56):4f}'   ->    124
    # f'{AutoFloat(  12.56):4f}'   ->   12.6
    # f'{AutoFloat(   1.56):4f}'   ->   1.56

    # to hide decimals:
    # f'{AutoFloat(1234.56):<4d}'  ->   1235
    # f'{AutoFloat(  12.56):<4d}'  ->   13

    RE_MAX_LEN = re.compile(r'(\d+)([fd])$')

    def __format__(self, format_spec: str) -> str:
        converted_spec = self._convert_spec(format_spec)
        f = super().__format__(converted_spec)
        return f

    def _convert_spec(self, format_spec: str) -> str:
        spec_matches = self.RE_MAX_LEN.findall(format_spec)
        if not spec_matches or len(spec_matches) > 1:
            raise RuntimeError('AutoFloat format should be "4f" or "3d"')

        spec_match = spec_matches[0]
        max_len = int(spec_match[0])
        ftype = spec_match[1]
        if ftype == 'd':
            return self.RE_MAX_LEN.sub(f'{max_len}.0f', format_spec)

        max_decimals_len = 2
        integer_len = len(str(trunc(self)))
        decimals_and_point_len = min(max_decimals_len + 1, max_len - integer_len)

        decimals_len = 0
        if decimals_and_point_len >= 2:  # dot without decimals makes no sense
            decimals_len = decimals_and_point_len - 1
        dot_str = f'.{decimals_len!s}'

        return self.RE_MAX_LEN.sub(f'{max_len}{dot_str}f', format_spec)


class BackgroundProgressBar:
    def __init__(self, highlight_open_seq: SGRSequence = None,
                 regular_open_seq: SGRSequence = None,
                 source_str: str = '', ratio: float = .0):
        super().__init__()
        self._highlight_open_seq: SGRSequence = highlight_open_seq
        self._regular_open_seq: SGRSequence = regular_open_seq
        self._source_str: str
        self._ratio: float

        self.update(source_str, ratio)

    def update(self, source_str: str, ratio: float):
        self._source_str = source_str
        self._ratio = max(0.0, min(1.0, ratio))

    def format(self):
        highlight_len = max(0, floor(self._ratio * len(self._source_str)))
        highlight_part = self._source_str[:highlight_len]
        regular_part = self._source_str[highlight_len:]
        left_part_len = highlight_len + 1  # +paddings
        right_part_len = len(self._source_str) - highlight_len + 1

        return f'{self._highlight_open_seq}' + \
               ' ' + \
               f'{highlight_part:>{left_part_len}s}' + \
               f'{SGRRegistry.FMT_RESET}{self._regular_open_seq}' + \
               f'{regular_part:<{right_part_len}s}' + \
               ' ' + \
               f'{SGRRegistry.FMT_RESET}'

    def __str__(self):
        return self._source_str
