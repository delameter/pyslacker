# -----------------------------------------------------------------------------
# SGR ANSI control sequences helper
# 2022 A. Shavykin <0.delameter@gmail.com>
# -----------------------------------------------------------------------------
import re


class SGRSequence:
    # SGR — Select Graphic Rendition, one of the CSI codes

    CONTROL_CHARACTER = '\033'
    INTRODUCER = '['
    SEPARATOR = ';'
    TERMINATOR = 'm'

    def __init__(self, *params: int):
        self.params = list(params)

    def __format__(self, format_spec: str) -> str:
        return self.__str__()

    def __str__(self):
        return '{}{}{}{}'.format(self.CONTROL_CHARACTER,
                                 self.INTRODUCER,
                                 self.SEPARATOR.join([str(param) for param in self.params]),
                                 self.TERMINATOR)


class SGRRegistry:
    FMT_RESET = SGRSequence(0)
    FMT_BOLD = SGRSequence(1)
    FMT_RED = SGRSequence(31)
    FMT_GREEN = SGRSequence(32)
    FMT_YELLOW = SGRSequence(33)
    FMT_BLUE = SGRSequence(34)

    SGR_REGEX = re.compile(r'\033\[[0-9;]*m')

    @staticmethod
    def remove_sgr_seqs(s: str) -> str:
        # remove all SGR escape sequences
        return SGRRegistry.SGR_REGEX.sub('', s)
