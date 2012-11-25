#
# Copyright (c) 2009-2012, Mendix bv
# All Rights Reserved.
#
# http://www.mendix.com/
#

import os
import shutil
import subprocess
from log import logger

# allow - in filenames we're completing without messing up completion
import readline
readline.set_completer_delims(readline.get_completer_delims().replace('-', ''))


def unpack(model_upload_path, mda_name, app_base):

    mda_file_name = os.path.join(model_upload_path, mda_name)
    if not os.path.isfile(mda_file_name):
        logger.error("file %s does not exist" % mda_file_name)
        return False

    logger.debug("Testing archive...")
    cmd = ("unzip", "-tqq", mda_file_name)
    try:
        proc = subprocess.Popen(cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        (stdout, stderr) = proc.communicate()

        if proc.returncode != 0:
            logger.error("An error occured while testing archive "
                         "consistency: ")
            if stdout != '':
                logger.error(stdout)
            if stderr != '':
                logger.error(stderr)
            return False
    except OSError, ose:
        logger.error("An error occured while executing unzip: %s" % ose)
        return False

    logger.info("This command will replace the contents of the model/ and "
                "web/ locations, using the files extracted from the archive")
    answer = raw_input("Continue? (y)es, (N)o? ")
    if answer != 'y':
        logger.info("Aborting!")
        return False

    logger.debug("Removing everything in model/ and web/ locations...")
    # TODO: error handling. removing model/ and web/ itself should not be
    # possible (parent dir is root owned), all errors ignored for now
    shutil.rmtree(os.path.join(app_base, 'model'), ignore_errors=True)
    shutil.rmtree(os.path.join(app_base, 'web'), ignore_errors=True)

    logger.debug("Extracting archive...")
    cmd = ("unzip", "-oq", mda_file_name, "web/*", "model/*", "-d", app_base)
    proc = subprocess.Popen(cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    (stdout, stderr) = proc.communicate()

    if proc.returncode != 0:
        logger.error("An error occured while extracting archive: ")
        if stdout != '':
            print(logger.error(stdout))
        if stderr != '':
            print(logger.error(stderr))
        return False

    # XXX: reset permissions on web/ model/ to be sure after executing this
    # function
    return True


def complete_unpack(model_upload_path, text):
    logger.trace("complete_unpack: Looking for %s in %s" %
                 (text, model_upload_path))
    return [f for f in os.listdir(model_upload_path)
            if os.path.isfile(os.path.join(model_upload_path, f))
            and f.startswith(text)
            and (f.endswith(".zip") or f.endswith(".mda"))]
