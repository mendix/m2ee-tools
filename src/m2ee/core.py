#!/usr/bin/python
#
# Copyright (c) 2009-2012, Mendix bv
# All Rights Reserved.
# http://www.mendix.com/
#

import pwd, os
from m2ee.config import M2EEConfig
from m2ee.client import M2EEClient
from m2ee.runner import M2EERunner
from m2ee import mdautil
from m2ee.log import logger

class M2EE():

    def __init__(self, yamlfiles=None, config=None):
        self._yamlfiles = yamlfiles
        self._reload_config(config)
        username = pwd.getpwuid(os.getuid())[0]
        self._default_prompt = "m2ee(%s): " % username
        self.prompt = self._default_prompt
        logger.info("Application Name: %s" % self._config.get_app_name())
        self._logproc = None

    def _reload_config_if_changed(self):
        if self._config.mtime_changed():
            logger.info("Configuration change detected, reloading.")
            self._reload_config()

    def _reload_config(self, config):
        self._config = M2EEConfig(yaml_files = self._yamlfiles, config = config)
        self._client = M2EEClient('http://127.0.0.1:%s/' % self._config.get_admin_port(), self._config.get_admin_pass())
        self._runner = M2EERunner(self._config, self._client)

    def _check_alive(self):
        pid_alive = self._runner.check_pid()
        m2ee_alive = self._client.ping()

        if pid_alive and not m2ee_alive:
            logger.error("The application process seems to be running (pid %s is alive), but does not respond to administrative requests." % self._runner.get_pid())
            logger.error("This could be caused by JVM Heap Space / Out of memory errors. Please review the application logfiles.")
            logger.error("You should consider restarting the application process, because it is likely to be in an undetermined broken state right now.")
        elif not pid_alive and m2ee_alive:
            logger.error("pid %s is not available, but m2ee responds" % self._runner.get_pid())
        return (pid_alive, m2ee_alive)

    def _report_not_running(self):
        """
        To be used by actions to see whether m2ee is available for executing requests.
        Also prints a line when the application is not running.

        if self._report_not_running():
            return
        do_things_that_communicate_using_m2ee_client()

        returns True when m2ee is not available for requests, else False
        """
        (pid_alive, m2ee_alive) = self._check_alive()
        if not pid_alive and not m2ee_alive:
            logger.info("The application process is not running.")
            return True
        # if pid is alive, but m2ee does not respond, errors are already printed by _check_alive
        if pid_alive and not m2ee_alive:
            return True
        return False

    def start_appcontainer(self):
        self._reload_config_if_changed()

        if not self._config.all_systems_are_go():
            logger.error("Cannot start MxRuntime due to previous critical errors.")
            return

        logger.debug("Checking if the runtime is already alive...")
        (pid_alive, m2ee_alive) = self._check_alive()
        if not pid_alive and not m2ee_alive:
            logger.info("Trying to start the MxRuntime...")
            if not self._runner.start():
                return
        elif not m2ee_alive:
            return

        # check if Appcontainer startup went OK
        m2eeresponse = self._client.runtime_status()
        if m2eeresponse.has_error():
            m2eeresponse.display_error()
            return

        # check status, if it's created or starting, go on, else stop
        m2eeresponse = self._client.runtime_status()
        status = m2eeresponse.get_feedback()['status']
        if not status in ['feut','created','starting']:
            logger.error("Cannot start MxRuntime when it has status %s" % status)
            return
        logger.debug("MxRuntime status: %s" % status)

        # go do startup sequence
        self._configure_logging()
        self._send_jetty_config()
        self._send_mime_types()

        xmpp_credentials = self._config.get_xmpp_credentials()
        if xmpp_credentials:
            self._client.connect_xmpp(xmpp_credentials)

        # when running hybrid appcontainer, we need to create the runtime ourselves
        if self._config.get_appcontainer_version():
            self._client.create_runtime({
                "runtime_path": os.path.join(self._config.get_runtime_path(),'runtime'),
                "port": self._config.get_runtime_port(),
                "application_base_path": self._config.get_app_base(),
                "use_blocking_connector": self._config.get_runtime_blocking_connector(),
            })

        self._fix_mxclientsystem_symlink()

        if not self._send_runtime_config():
            # stop when sending configuration causes error messages
            return

    def _fix_mxclientsystem_symlink(self):
        # check mxclientsystem symlink and refresh if necessary
        if self._config.get_symlink_mxclientsystem():
            mxclient_symlink = os.path.join(self._config.get_public_webroot_path(), 'mxclientsystem')
            real_mxclient_location = self._config.get_real_mxclientsystem_path()
            if os.path.islink(mxclient_symlink):
                current_real_mxclient_location = os.path.realpath(mxclient_symlink)
                if not current_real_mxclient_location == real_mxclient_location:
                    logger.debug("mxclientsystem symlink exists, but points to %s" % current_real_mxclient_location)
                    logger.debug("redirecting symlink to %s" % real_mxclient_location)
                    os.unlink(mxclient_symlink)
                    os.symlink(real_mxclient_location, mxclient_symlink)
            elif not os.path.exists(mxclient_symlink):
                logger.debug("creating mxclientsystem symlink pointing to %s" % real_mxclient_location)
                try:
                    os.symlink(real_mxclient_location, mxclient_symlink)
                except OSError, e:
                    logger.error("creating symlink failed: %s" % e)
            else:
                logger.warn("Not touching mxclientsystem symlink: file exists and is not a symlink")
    
    def _configure_logging(self):
        # try configure logging
        # catch:
        # - logsubscriber already exists -> ignore
        #   (TODO:functions to restart logging when config is changed?)
        # - logging already started -> ignore
        logger.debug("Setting up logging...")
        logging_config = self._config.get_logging_config()
        if len(logging_config) == 0:
            logger.warn("No logging settings found, this is probably not what you want.")
        else:
            for log_subscriber in logging_config:
                m2eeresponse = self._client.create_log_subscriber(log_subscriber)
                result = m2eeresponse.get_result()
                if result == 3: # name exists
                    pass # ignore for now
                elif result != 0:
                    m2eeresponse.display_error()
            m2eeresponse = self._client.start_logging() # ignore response

    def _send_jetty_config(self):
        # send jetty configuration
        jetty_opts = self._config.get_jetty_options()
        if jetty_opts:
            logger.debug("Sending Jetty configuration...")
            m2eeresponse = self._client.set_jetty_options(jetty_opts)
            result = m2eeresponse.get_result()
            if result != 0:
                logger.error("Setting Jetty options failed: %s" % m2eeresponse.get_cause())

    def _send_mime_types(self):
        mime_types = self._config.get_mimetypes()
        if mime_types:
            logger.debug("Sending mime types...")
            m2eeresponse = self._client.add_mime_type(mime_types)
            result = m2eeresponse.get_result()
            if result != 0:
                logger.error("Setting mime types failed: %s" % m2eeresponse.get_cause())

    def _send_runtime_config(self):
        # send runtime configuration
        # catch and report:
        # - configuration errors (X is not a file etc)
        # XXX: fix mxruntime to report all errors and warnings in adminaction feedback instead of stopping to process input
        # if errors, abort.
        logger.debug("Sending MxRuntime configuration...")
        m2eeresponse = self._client.update_configuration(self._config.get_runtime_config())
        result = m2eeresponse.get_result()
        if result == 1:
            logger.error("Sending configuration failed: %s" % m2eeresponse.get_cause())
            logger.error("You'll have to fix the configuration and run start again...")
            return False

        # send custom configuration
        custom_config = self._config.get_custom_config()
        # custom_config will be None if running 3.0+ because update_custom_configuration is gone in 3.0
        if custom_config:
            logger.debug("Sending custom configuration...")
            m2eeresponse = self._client.update_custom_configuration(self._config.get_custom_config())
            result = m2eeresponse.get_result()
            if result == 1:
                logger.error("Sending custom configuration failed: %s" % m2eeresponse.get_cause())
                return False

        return True

    def _who(self, limitint=None):
        limit = {}
        if limitint != None:
            limit = {"limit": limitint}
        m2eeresp = self._client.get_logged_in_user_names(limit)
        m2eeresp.display_error()
        if not m2eeresp.has_error():
            feedback = m2eeresp.get_feedback()
            logger.info("Logged in users: (%s) %s" % (feedback['count'], feedback['users']))
            return feedback['count']
        return 0

    def complete_unpack(self, text, line, begidx, endidx):
        return mdautil.complete_unpack(self._config.get_model_upload_path(), text)

    def _get_log_levels(self):
        if self._report_not_running():
            return
        params = {"sort" : "subscriber"}
        m2eeresponse = self._client.get_log_settings(params) 
        print "Current loglevels:"
        log_subscribers = []
        for (subscriber_name, node_names) in m2eeresponse.get_feedback().iteritems():
            for (node_name, subscriber_level) in node_names.iteritems():
                log_subscribers.append("%s %s %s" % 
                        (subscriber_name, node_name, subscriber_level))
        log_subscribers.sort()
        print("\n".join(log_subscribers))

    def _set_log_level(self, subscriber, node, level):
        if self._report_not_running():
            return
        level = level.upper()
        params = {"subscriber":subscriber,"node":node,"level":level}
        response = self._client.set_log_level(params)
        if response.has_error():
            response.display_error()
            print "Remember, all parameters are case sensitive"
        else:
            logger.info("Loglevel for %s set to %s" % (node, level))

    def emptyline(self):
        self._reload_config_if_changed()
        pass

    # simple hook to log usage
    def precmd(self, line):
        if line:
            logger.trace("Executing command: %s" % line)
        return line

