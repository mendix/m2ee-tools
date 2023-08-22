import logging


def monkeypatch_logging():
    # register trace logging possibility
    TRACE = 5
    logging.addLevelName(TRACE, 'TRACE')
    setattr(logging, 'TRACE', TRACE)

    def loggerClassTrace(self, msg, *args, **kwargs):
        if self.isEnabledFor(TRACE):
            self._log(TRACE, msg, args, **kwargs)

    setattr(logging.getLoggerClass(), 'trace', loggerClassTrace)

    def rootTrace(msg, *args, **kwargs):
        if logging.root.isEnabledFor(TRACE):
            logging.root._log(TRACE, msg, args, **kwargs)
    setattr(logging, 'trace', rootTrace)


if not hasattr(logging, 'trace'):
    monkeypatch_logging()

from m2ee.core import M2EE  # noqa
import m2ee.pgutil  # noqa
import m2ee.nagios  # noqa
import m2ee.munin  # noqa
import m2ee.version  # noqa

__version__ = '8.0.1'
