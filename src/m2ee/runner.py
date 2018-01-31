#
# Copyright (c) 2009-2017, Mendix bv
# All Rights Reserved.
# http://www.mendix.com/
#

import logging
import subprocess
import os
import signal
import time
import errno
from time import sleep
from client import M2EEAdminException
from m2ee.exceptions import M2EEException

logger = logging.getLogger(__name__)


class M2EERunner:
    # for background documentation, see:
    # http://www.faqs.org/faqs/unix-faq/programmer/faq/

    def __init__(self, config, client):
        self._config = config
        self._client = client
        self._read_pidfile()
        self._attached_proc = None

    def _read_pidfile(self):
        pidfile = self._config.get_pidfile()
        try:
            pf = file(pidfile, 'r')
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
                file(pidfile, 'w+').write("%s\n" % self._pid)
            except IOError, e:
                logger.error("Cannot write pidfile: %s" % e)

    def cleanup_pid(self):
        logger.debug("cleaning up pid & pidfile")
        self._pid = None
        pidfile = self._config.get_pidfile()
        if os.path.isfile(pidfile):
            os.unlink(pidfile)

    def get_pid(self):
        if self._pid is None:
            self._read_pidfile()
        return self._pid

    def check_pid(self, pid=None):
        if pid is None:
            pid = self.get_pid()
        if pid is None:
            logger.trace("No pid available.")
            return False
        try:
            os.kill(pid, 0)  # doesn't actually kill process
            logger.trace("pid %s is alive!" % pid)
            return True
        except OSError:
            logger.trace("No process with pid %s, or not ours." % pid)
            return False

    def check_attached_proc(self):
        if self._attached_proc is None:
            return False
        returncode = self._attached_proc.poll()
        if returncode is not None:
            logger.trace("Attached JVM process exited with returncode %s" % returncode)
            self._attached_proc = None
            return False
        logger.trace("Attached JVM process is still alive.")
        return True

    def stop(self, timeout):
        walltime_begin = time.time()
        self._client.shutdown(timeout)
        timeout = int(timeout - (time.time() - walltime_begin))
        if timeout < 1:
            logger.trace("Shutdown request returned just in time, adding a little bit of "
                         "extra time to wait for the pid to disappear")
            timeout = 2
        return self._wait_pid(timeout)

    def terminate(self, timeout):
        logger.debug("sending SIGTERM to pid %s" % self._pid)
        try:
            os.kill(self._pid, signal.SIGTERM)
        except OSError:
            # already gone or not our process?
            logger.debug("OSError! Process already gone?")
        return self._wait_pid(timeout)

    def kill(self, timeout):
        logger.debug("sending SIGKILL to pid %s" % self._pid)
        try:
            os.kill(self._pid, signal.SIGKILL)
        except OSError:
            # already gone or not our process?
            logger.debug("OSError! Process already gone?")
        return self._wait_pid(timeout)

    def start(self, detach=True, timeout=60, step=0.25):
        if self.check_pid():
            logger.error("The application process is already started!")
            return

        if detach:
            try:
                logger.trace("[%s] Forking now..." % os.getpid())
                pid = os.fork()
                if pid > 0:
                    self._pid = None
                    logger.trace("[%s] Waiting for intermediate process to exit..." % os.getpid())
                    # prevent zombie process
                    (pid, result) = os.waitpid(pid, 0)
                    exitcode = result >> 8
                    self._handle_jvm_start_result(exitcode)
                    return
            except OSError, e:
                raise M2EEException("Forking subprocess failed: %d (%s)\n" % (e.errno, e.strerror))
            logger.trace("[%s] Now in intermediate forked process..." % os.getpid())
            # decouple from parent environment
            os.chdir("/")
            os.setsid()
            os.umask(0022)
            exitcode = self._start_jvm(detach, timeout, step)
            logger.trace("[%s] Exiting intermediate process with exit code %s" %
                         (os.getpid(), exitcode))
            os._exit(exitcode)
        else:
            exitcode = self._start_jvm(detach, timeout, step)
            self._handle_jvm_start_result(exitcode)

    def _handle_jvm_start_result(self, exitcode):
        if exitcode == 0:
            logger.debug("The JVM process has been started.")
        elif exitcode == 2:
            logger.error("The java binary cannot be found in the default search path!")
            logger.error("By default, when starting the JVM, the environment is not "
                         "preserved. If you don't set preserve_environment to true or "
                         "specify PATH in preserve_environment or custom_environment in "
                         "the m2ee section of your m2ee.yaml configuration file, the "
                         "search path is likely a very basic default list like "
                         "'/bin:/usr/bin'")
            raise M2EEException("Starting the JVM process did not succeed: JVM binary not found",
                                errno=M2EEException.ERR_JVM_BINARY_NOT_FOUND)
        elif exitcode == 3:
            raise M2EEException("Starting the JVM process (fork/exec) did not succeed.",
                                errno=M2EEException.ERR_JVM_FORKEXEC)
        elif exitcode == 4:
            raise M2EEException("Starting the JVM process takes too long.",
                                errno=M2EEException.ERR_JVM_TIMEOUT)
        elif exitcode == 0x20:
            raise M2EEException("JVM process disappeared with a clean exit code.",
                                errno=M2EEException.ERR_APPCONTAINER_EXIT_ZERO)
        elif exitcode == 0x21:
            raise M2EEException("JVM process terminated without reason.",
                                errno=M2EEException.ERR_APPCONTAINER_UNKNOWN_ERROR)
        elif exitcode == 0x22:
            raise M2EEException("JVM process terminated: could not bind admin port.",
                                errno=M2EEException.ERR_APPCONTAINER_ADMIN_PORT_IN_USE)
        elif exitcode == 0x23:
            raise M2EEException("JVM process terminated: could not bind runtime port.",
                                errno=M2EEException.ERR_APPCONTAINER_RUNTIME_PORT_IN_USE)
        elif exitcode == 0x24:
            raise M2EEException("JVM process terminated: incompatible JVM version.",
                                errno=M2EEException.ERR_APPCONTAINER_INVALID_JDK_VERSION)
        else:
            raise M2EEException("Starting the JVM process failed, reason unknown (%s)." %
                                exitcode, errno=M2EEException.ERR_JVM_UNKNOWN)
        return

    def _start_jvm(self, detach, timeout, step):
        env = self._config.get_java_env()
        cmd = self._config.get_java_cmd()

        logger.trace("Environment to be used when starting the JVM: %s" %
                     ' '.join(["%s='%s'" % (k, v) for k, v in env.iteritems()]))
        logger.trace("Command line to be used when starting the JVM: %s" % ' '.join(cmd))
        logger.trace("[%s] Starting the JVM..." % os.getpid())
        try:
            proc = subprocess.Popen(
                cmd,
                close_fds=True,
                stdin=subprocess.PIPE,
                cwd='/',
                env=env,
            )
        except Exception as e:
            if isinstance(e, OSError) and e.errno == errno.ENOENT:
                return 2
            else:
                logger.error("Starting JVM failed: %s" % e)
                return 3

        # always write pid asap, so that monitoring can detect apps that should
        # be started but fail to do so
        self._pid = proc.pid
        logger.trace("[%s] Writing JVM pid to pidfile: %s" % (os.getpid(), self._pid))
        self._write_pidfile()
        # wait for m2ee to become available
        t = 0
        while t < timeout:
            sleep(step)
            dead = proc.poll()
            if dead is not None:
                logger.debug("Java subprocess terminated with errorcode %s" % dead)
                return 0x20 + dead
            if self.check_pid(proc.pid) and self._client.ping():
                break
            t += step
        if t >= timeout:
            logger.debug("Timeout: Java subprocess takes too long to start.")
            return 4
        if detach and self._config.get_close_stdio():
            self.close_jvm_stdio()
        if not detach:
            self._attached_proc = proc
        return 0

    def close_jvm_stdio(self):
        logger.trace("Calling CloseStdIO...")
        try:
            self._client.close_stdio()
        except M2EEAdminException as e:
            logger.error("Failed to close stdio, ignoring: %s" % e)

    def _wait_pid(self, timeout=None, step=0.25):
        logger.trace("Waiting for process to disappear: timeout=%s" % timeout)
        if self.check_pid():
            if timeout is None:
                return False
            t = 0
            while t < timeout:
                sleep(step)
                alive = self.check_pid()
                self.check_attached_proc()
                if not alive:
                    break
                t += step
            if t >= timeout:
                logger.trace("Timeout: Process %s takes too long to "
                             "disappear." % self._pid)
                return False
        self.cleanup_pid()
        return True
