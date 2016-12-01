#
# Copyright (c) 2009-2015, Mendix bv
# All Rights Reserved.
#
# http://www.mendix.com/
#

import logging
import sys

logger = logging.getLogger("m2ee")
# level will be set at startup


class M2EELogFilter(logging.Filter):
    def __init__(self, level, ge):
        self.level = level
        # log levels greater than and equal to (True), or below (False)
        self.ge = ge

    def filter(self, record):
        if self.ge:
            return record.levelno >= self.level
        return record.levelno < self.level

consolelogformatter = logging.Formatter("%(levelname)s: %(message)s")

# log everything below ERROR to to stdout
stdoutlog = logging.StreamHandler(sys.stdout)
stdoutlog.setFormatter(consolelogformatter)
stdoutfilter = M2EELogFilter(logging.ERROR, False)
stdoutlog.addFilter(stdoutfilter)

# log everything that's ERROR and more serious to stderr
stderrlog = logging.StreamHandler(sys.stderr)
stderrlog.setFormatter(consolelogformatter)
stderrfilter = M2EELogFilter(logging.ERROR, True)
stderrlog.addFilter(stderrfilter)

logger.addHandler(stdoutlog)
logger.addHandler(stderrlog)
