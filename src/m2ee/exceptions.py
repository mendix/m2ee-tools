# Copyright (c) 2009-2015, Mendix bv
# All Rights Reserved.
# http://www.mendix.com/
#


class M2EEException(Exception):
    def __init__(self, message, cause=None):
        self.message = message
        self.cause = cause

    def __str__(self):
        if self.cause is not None:
            return "%s, caused by: %s" % (self.message, self.cause)
        return self.message
