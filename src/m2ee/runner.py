#
# Copyright (c) 2009-2012, Mendix bv
# All Rights Reserved.
# http://www.mendix.com/
#

import subprocess
import os, signal, errno
from time import sleep
from log import logger

class M2EERunner:
    # for background documentation, see:
    # http://www.faqs.org/faqs/unix-faq/programmer/faq/

    def __init__(self, config, client):
        self._config = config
        self._client = client
        self._read_pidfile()

    def _read_pidfile(self):
        pidfile = self._config.get_pidfile()
        try:
            pf = file(pidfile,'r')
            self._pid = int(pf.read().strip())
            pf.close()
        except IOError, e:
            if e.errno != errno.ENOENT:
                logger.warn("Cannot read pidfile: %s" % e)
            self._pid = None
        except ValueError, e:
            logger.warn("Cannot read pidfile: %s" % e)
            self._pid = None

    def _write_pidfile(self):
        if self._pid:
            pidfile = self._config.get_pidfile()
            try:
                file(pidfile,'w+').write("%s\n" % self._pid)
            except IOError, e:
                logger.error("Cannot write pidfile: %s" % e)

    def _cleanup_pid(self):
        logger.debug("cleaning up pid & pidfile")
        self._pid = None
        pidfile = self._config.get_pidfile()
        if os.path.isfile(pidfile):
            os.unlink(pidfile)

    def get_pid(self):
        if not self._pid:
            self._read_pidfile()
        return self._pid

    def check_pid(self, pid=None):
        if pid == None:
            pid = self.get_pid()
        if not pid:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            logger.debug("No process with pid %s, or not ours." % pid)
            return False

    def stop(self, timeout=5):
        self._client.shutdown() # fire and forget!
        return self._wait_pid(timeout)

    def terminate(self, timeout=5):
        logger.debug("sending SIGTERM to pid %s" % self._pid)
        try:
            os.kill(self._pid, signal.SIGTERM)
        except OSError:
            # already gone or not our process?
            logger.debug("OSError! Process already gone?")
        return self._wait_pid(timeout)

    def kill(self, timeout=5):
        logger.debug("sending SIGKILL to pid %s" % self._pid)
        try:
            os.kill(self._pid, signal.SIGKILL)
        except OSError:
            # already gone or not our process?
            logger.debug("OSError! Process already gone?")
        return self._wait_pid(timeout)

    def start(self, timeout=10, step=0.25):
        if self.check_pid():
            logger.error("The application process is already started!")
            return False

        # check for platform availability
        version = self._config.get_runtime_version()
        classpath = self._config.get_classpath()
        if not classpath:
            logger.error("Cannot start MxRuntime, MxRuntime version %s is not available on this server" % version)
            return False

        try:
            pid = os.fork()
            if pid > 0:
                self._pid = None
                # prevent zombie process
                (waitpid, result) = os.waitpid(pid, 0)
                if result == 0:
                    logger.debug("The JVM process has been started.")
                    return True
                logger.error("Starting the JVM process did not succeed...")
                return False
        except OSError, e:
            logger.error("Forking subprocess failed: %d (%s)\n" % (e.errno, e.strerror))
            return
        # decouple from parent environment
        os.chdir("/")
        os.setsid()
        os.umask(0022)
        # start java subprocess (second fork)
        cmd = ['java']
        javaopts = self._config.get_java_opts()
        if javaopts:
            cmd.extend(javaopts)
        cmd.extend(['-cp', classpath, self._config.get_appcontainer_mainclass()])
        logger.trace("Starting java using command line: %s" % cmd)
        proc = subprocess.Popen(
            cmd,
            close_fds=True,
            cwd='/',
            env=self._config.get_java_env()
        )
        # always write pid asap, so that monitoring can detect apps that should
        # be started but fail to do so
        self._pid = proc.pid
        self._write_pidfile()
        # wait for m2ee to become available
        t = 0
        while t < timeout:
            sleep(step)
            dead = proc.poll()
            if dead != None:
                logger.error("Java subprocess terminated with errorcode %s" % dead)
                os._exit(1)
            if self.check_pid(proc.pid) and self._client.ping():
                break
            t += step
        if t >= timeout:
            os._exit(1)
        self._client.close_stdio().display_error()
        os._exit(0)

    def _wait_pid(self, timeout=None, step=0.25):
        if self.check_pid():
            if timeout == None:
                return False
            t = 0
            while t < timeout:
                sleep(step)
                if not self.check_pid():
                    break
                t += step
            if t >= timeout:
                return False
        self._cleanup_pid()
        return True

