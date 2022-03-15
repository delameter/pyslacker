#!/usr/bin/env python3
from math import copysign
from random import randint, random
from time import sleep

from logger import Logger
from request_series_printer import RequestSeriesPrinter

logger = Logger.get_instance()

request_series_printer = RequestSeriesPrinter.get_instance()

def _sleep(seconds: float):
    while seconds > 1:
        request_series_printer.sleep_iterator(seconds)
        seconds -= 1
        sleep(1)
    sleep(seconds)

for slp in (0, 1):
    request_series_printer.reinit()
    request_series_printer.before_paginated_batch(f'est20')
    for req_id in range(0, 100):
        if  req_id % 20 == 0:
            request_series_printer._requests_estimated = None
            request_series_printer._print_event('Estimation off')
        elif req_id % 20 == 10:
            request_series_printer._requests_estimated = 90
            request_series_printer._print_event('Estimation on')

        request_series_printer.before_request()
        request_series_printer.before_request_attempt(randint(1, 2))

        if req_id % 11 == 0:
            try:
                request_series_printer['nonextsingkey']
            except Exception as e:
                request_series_printer.on_request_failure(f'{e!s}')
                logger.error(f'{e!s}', silent=True)
        else:
            request_series_printer.update_statistics(True, 0, pow(req_id-8,2)/35 if req_id > 5 else None)
            request_series_printer.on_request_completion(randint(200, 209), True)

        if req_id % 25 == 0:
            request_series_printer.on_post_request_delay_update(0, delta_sign=copysign(1*(req_id-50), req_id-50))
            request_series_printer._print_event('Delay updated')
        if req_id % 25 == 1 and slp == 0:
            request_series_printer._persist_line()

        if req_id % 40 == 37:
            request_series_printer.before_sleeping(slp, 'Nap')
            _sleep(10*slp)
            request_series_printer.after_sleeping()
        else:
            sleep(slp)

    request_series_printer.after_paginated_batch()
exit()

for batch_idx, max_req in enumerate([100, 2000, 100]):
    request_series_printer.reinit(1111)

    if batch_idx == 2:
        request_series_printer._requests_estimated = 0
    request_series_printer.before_paginated_batch(f'max_i={max_req}')


    for req_id in range(1, max_req):
        request_series_printer.before_request()
        request_series_printer.before_request_attempt(randint(1, 2))

        result = randint(0, 100)
        if req_id > 5:
            rpm = randint(1,1050)+randint(0,9)/10
            if randint(0,5) == 0:
                rpm = randint(1,9)+random()
        else:
            rpm = None

        if req_id < 100 and result < 4:
            continue

        if result < 2:
            request_series_printer.on_request_failure("(NotImplementedError('NO'))")
            #logger.error('PANICPANICPANICPANICPANICPANICPANICPANICPANICPANICPANICPANICPANICPANICPANICPANICPANICPANICPANIC')
        elif result < 4:
            request_series_printer.update_statistics(False, 0, rpm)
            request_series_printer.on_request_completion(randint(400, 509), False)
            request_series_printer.on_post_request_delay_update(0, delta_sign=randint(-1, 1))
        else:
            size = randint(0, 550)
            request_series_printer.update_statistics(True, size, rpm)
            request_series_printer.on_request_completion(randint(200, 209), True)
        #request_series_printer._persist_line()

    request_series_printer.after_paginated_batch()
        #//sleep(.01)

    #31    107   63.3%   ETA 41 sec   16.23 RPM      4.36 Mb ...
    #32 9  475   63.3%   ETA 59 sec  [OVERCLOCK]     4.36 Mb ...
    #33    267   63.3%   ETA 38 sec   17.20 RPM    124.36 Mb ...
    #33    267   63.3%   ETA 38 sec  [ SUPPRESS]   124.36 Mb ...
    #33    267   63.3%   ETA 38 sec   17.20 RPM    124.36 Mb ...
