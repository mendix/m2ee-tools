#
# Copyright (c) 2009-2015, Mendix bv
# All Rights Reserved.
#
# http://www.mendix.com/
#

import os
import logging
import shutil
import subprocess
import socket
import httplib
import sys
import tempfile
from m2ee.exceptions import M2EEException

logger = logging.getLogger(__name__)

try:
    import readline
    # allow - in filenames we're completing without messing up completion
    readline.set_completer_delims(
        readline.get_completer_delims().replace('-', '')
    )
except ImportError:
    pass

try:
    import httplib2
except ImportError:
    logger.critical("Failed to import httplib2. This module is needed by "
                    "m2ee. Please povide it on the python library path")
    raise


def unpack(config, mda_name):

    mda_file_name = os.path.join(config.get_model_upload_path(), mda_name)
    if not os.path.isfile(mda_file_name):
        raise M2EEException("File %s does not exist." % mda_file_name)

    logger.debug("Testing archive...")
    cmd = ("unzip", "-tqq", mda_file_name)
    logger.trace("Executing %s" % str(cmd))
    try:
        proc = subprocess.Popen(cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        (stdout, stderr) = proc.communicate()

        logger.trace("stdout: %s" % stdout)
        logger.trace("stderr: %s" % stderr)
        if proc.returncode != 0:
            raise M2EEException("\n".join([
                "An error occured while testing archive consistency:",
                "stdout: %s" % stdout,
                "stderr: %s" % stderr,
            ]))
    except OSError, ose:
        import errno
        if ose.errno == errno.ENOENT:
            raise M2EEException("The unzip program could not be found", ose)
        else:
            raise M2EEException("An error occured while executing unzip: %s " % ose, ose)

    logger.debug("Removing everything in model/ and web/ locations...")
    # TODO: error handling. removing model/ and web/ itself should not be
    # possible (parent dir is root owned), all errors ignored for now
    app_base = config.get_app_base()
    shutil.rmtree(os.path.join(app_base, 'model'), ignore_errors=True)
    shutil.rmtree(os.path.join(app_base, 'web'), ignore_errors=True)

    logger.debug("Extracting archive...")
    cmd = ("unzip", "-oq", mda_file_name, "web/*", "model/*", "-d", app_base)
    logger.trace("Executing %s" % str(cmd))
    proc = subprocess.Popen(cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    (stdout, stderr) = proc.communicate()

    logger.trace("stdout: %s" % stdout)
    logger.trace("stderr: %s" % stderr)
    if proc.returncode != 0:
        raise M2EEException("\n".join([
            "An error occured while extracting archive:",
            "stdout: %s" % stdout,
            "stderr: %s" % stderr,
        ]))

    # XXX: reset permissions on web/ model/ to be sure after executing this
    # function


def fix_mxclientsystem_symlink(config):
    logger.debug("Running fix_mxclientsystem_symlink...")
    mxclient_symlink = os.path.join(
        config.get_public_webroot_path(), 'mxclientsystem')
    logger.trace("mxclient_symlink: %s" % mxclient_symlink)
    real_mxclientsystem_path = config.get_real_mxclientsystem_path()
    logger.trace("real_mxclientsystem_path: %s" % real_mxclientsystem_path)
    if os.path.islink(mxclient_symlink):
        current_real_mxclientsystem_path = os.path.realpath(
            mxclient_symlink)
        if current_real_mxclientsystem_path != real_mxclientsystem_path:
            logger.debug("mxclientsystem symlink exists, but points "
                         "to %s" % current_real_mxclientsystem_path)
            logger.debug("redirecting symlink to %s" %
                         real_mxclientsystem_path)
            os.unlink(mxclient_symlink)
            os.symlink(real_mxclientsystem_path, mxclient_symlink)
    elif not os.path.exists(mxclient_symlink):
        logger.debug("creating mxclientsystem symlink pointing to %s" %
                     real_mxclientsystem_path)
        try:
            os.symlink(real_mxclientsystem_path, mxclient_symlink)
        except OSError, e:
            logger.error("creating symlink failed: %s" % e)
    else:
        logger.warn("Not touching mxclientsystem symlink: file exists "
                    "and is not a symlink")


def run_post_unpack_hook(post_unpack_hook):
    if os.path.isfile(post_unpack_hook):
        if os.access(post_unpack_hook, os.X_OK):
            logger.info("Running post-unpack-hook: %s" % post_unpack_hook)
            retcode = subprocess.call((post_unpack_hook,))
            if retcode != 0:
                logger.error("The post-unpack-hook returned a "
                             "non-zero exit code: %d" % retcode)
        else:
            logger.error("post-unpack-hook script %s is not "
                         "executable." % post_unpack_hook)
    else:
        logger.error("post-unpack-hook script %s does not exist." %
                     post_unpack_hook)


def download_and_unpack_runtime_curl(version, url, path, **curl_opts):
    check_runtime_download_url(url)
    logger.info("Going to download %s to %s" % (url, path))
    tempdir = tempfile.mkdtemp(dir=path)
    fd, temptgz = tempfile.mkstemp(dir=tempdir)
    os.close(fd)
    logger.debug("Download temp file: %s" % temptgz)
    download_with_curl(url, temptgz, **curl_opts)
    logger.info("Extracting runtime archive...")
    unpack_runtime(version, tempdir, temptgz, path)
    shutil.rmtree(tempdir, ignore_errors=True)
    logger.info("Successfully downloaded runtime!")


def check_runtime_download_url(url):
    h = httplib2.Http(timeout=10)
    logger.debug("Checking for existence of %s via HTTP HEAD" % url)
    try:
        (response_headers, response_body) = h.request(url, "HEAD")
        logger.trace("Response headers: %s" % response_headers)
    except (httplib2.HttpLib2Error, httplib.HTTPException, socket.error) as e:
        raise M2EEException("Checking download url %s failed" % url, e)
    if (response_headers['status'] == '404'):
        raise M2EEException("The location %s cannot be found." % url)
    elif (response_headers['status'] != '200'):
        raise M2EEException("Checking download url %s failed, HTTP status code %s" %
                            (url, response_headers['status']))
    logger.debug("Ok, got HTTP 200")


def download_and_unpack_runtime_wget(url, path):
    check_runtime_download_url(url)
    p1 = subprocess.Popen([
        'wget',
        '-O',
        '-',
        url,
    ], stdout=subprocess.PIPE)
    p2 = subprocess.Popen([
        'tar',
        'xz',
        '-C',
        path,
    ], stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    p1.stdout.close()
    stdout, stderr = p2.communicate()
    if p2.returncode != 0:
        raise M2EEException("Could not download and unpack runtime:\n%s" % stderr)
    logger.info("Successfully downloaded runtime!")


def download_with_curl(url, output, retry=5, cookies=None,
                       max_time=None, speed_time=None, speed_limit=None,
                       resume=True):
    command = ['curl']
    if cookies is not None:
        command.extend(['--cookie', '; '.join(cookies)])
    if sys.stderr.isatty():
        command.append('-#')
    else:
        command.append('--silent')
    if max_time is not None:
        command.extend(['--max-time', str(max_time)])
    if speed_time is not None:
        command.extend(['--speed-time', str(speed_time)])
    if speed_limit is not None:
        command.extend(['--speed-limit', str(speed_limit)])
    if resume is True:
        command.extend(['--continue-at', '-'])
    command.extend(['--output', output, url])

    done = False
    attempt = 0
    while not done:
        logger.trace("Executing %s" % command)
        process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE,
                                   stderr=None if sys.stderr.isatty() else subprocess.PIPE,
                                   close_fds=True)
        stdout, stderr = process.communicate()
        returncode = process.returncode
        if returncode == 0:
            done = True
        elif returncode == 28:
            got_bytes = os.path.getsize(output)
            attempt += 1
            if attempt > retry:
                raise M2EEException("Failed to download %s, retried %s times, got %s bytes" %
                                    (url, retry, got_bytes))
            else:
                logger.warning("Download %s too slow, at %s bytes after %s seconds,"
                               " retrying %d/%d" % (url, got_bytes, speed_time, attempt, retry))
        else:
            if stderr is not None and len(stderr) > 0:
                logger.error("Unexpected curl returncode %s, stderr: %s" % (returncode, stderr))
            raise M2EEException("Failed to download %s, curl returncode %s" % (url, returncode))


def unpack_runtime(version, tempdir, temptgz, runtimes_path):
    try:
        subprocess.check_call(['tar', 'xz', '-C', tempdir, '-f', temptgz])
    except subprocess.CalledProcessError as cpe:
        raise M2EEException("Corrupt runtime archive, extracting failed: %s" % cpe.message, cpe)
    extracted_runtime_dir = os.path.join(tempdir, str(version))
    if not os.path.isdir(extracted_runtime_dir):
        raise M2EEException("Corrupt runtime archive, version %s not found inside!" % version)
    os.rename(extracted_runtime_dir, os.path.join(runtimes_path, str(version)))
