# Copyright (c) 2009-2012, Mendix bv
# All Rights Reserved.
# http://www.mendix.com/
#

import os
import codecs
import time
import copy

from config import M2EEConfig
from client import M2EEClient
from runner import M2EERunner
from log import logger


class M2EE():

    def __init__(self, yamlfiles=None, config=None):
        self._yamlfiles = yamlfiles
        self.reload_config(config)
        self._logproc = None

    def reload_config_if_changed(self):
        if self.config.mtime_changed():
            logger.info("Configuration change detected, reloading.")
            self.reload_config()

    def reload_config(self, config=None):
        self.config = M2EEConfig(yaml_files=self._yamlfiles, config=config)
        self.client = M2EEClient(
            'http://127.0.0.1:%s/' % self.config.get_admin_port(),
            self.config.get_admin_pass())
        self.runner = M2EERunner(self.config, self.client)

    def check_alive(self):
        pid_alive = self.runner.check_pid()
        m2ee_alive = self.client.ping()

        if pid_alive and not m2ee_alive:
            logger.error("The application process seems to be running "
                         "(pid %s is alive), but is not accessible for "
                         "administrative requests." % self.runner.get_pid())
            logger.error("If this is not caused by a configuration error "
                         "(e.g. wrong admin_port) setting, it could be caused "
                         "by JVM Heap Space / Out of memory errors. Please "
                         "review the application logfiles. In case of JVM "
                         "errors, you should consider restarting the "
                         "application process, because it is likely to be in "
                         "an undetermined broken state right now.")
        elif not pid_alive and m2ee_alive:
            logger.error("pid %s is not available, but m2ee responds" %
                         self.runner.get_pid())
        return (pid_alive, m2ee_alive)

    def start_appcontainer(self):
        if not self.config.all_systems_are_go():
            logger.error("Cannot start MxRuntime due to previous critical "
                         "errors.")
            return False

        logger.debug("Checking if the runtime is already alive...")
        (pid_alive, m2ee_alive) = self.check_alive()
        if not pid_alive and not m2ee_alive:
            logger.info("Trying to start the MxRuntime...")
            if not self.runner.start():
                return False
        elif not m2ee_alive:
            return False

        # check if Appcontainer startup went OK
        m2eeresponse = self.client.runtime_status()
        if m2eeresponse.has_error():
            m2eeresponse.display_error()
            return False

        # check status, if it's created or starting, go on, else stop
        m2eeresponse = self.client.runtime_status()
        status = m2eeresponse.get_feedback()['status']
        if not status in ['feut', 'created', 'starting']:
            logger.error("Cannot start MxRuntime when it has status %s" %
                         status)
            return False
        logger.debug("MxRuntime status: %s" % status)

        # go do startup sequence
        self._configure_logging()
        self._send_jetty_config()
        self._send_mime_types()

        xmpp_credentials = self.config.get_xmpp_credentials()
        if xmpp_credentials:
            self.client.connect_xmpp(xmpp_credentials)

        # when running hybrid appcontainer, we need to create the runtime
        # ourselves
        if self.config.get_appcontainer_version():
            response = self.client.create_runtime({
                "runtime_path":
                os.path.join(self.config.get_runtime_path(), 'runtime'),
                "port": self.config.get_runtime_port(),
                "application_base_path": self.config.get_app_base(),
                "use_blocking_connector":
                self.config.get_runtime_blocking_connector(),
            })
            return not response.has_error()

        return True

    def stop(self):
        if self.runner.check_pid():
            return self.runner.stop()
        else:
            self.runner.cleanup_pid()
        return True

    def fix_mxclientsystem_symlink(self):
        # check mxclientsystem symlink and refresh if necessary
        if self.config.get_symlink_mxclientsystem():
            mxclient_symlink = os.path.join(
                self.config.get_public_webroot_path(), 'mxclientsystem')
            real_mxclient_location = self.config.get_real_mxclientsystem_path()
            if os.path.islink(mxclient_symlink):
                current_real_mxclient_location = os.path.realpath(
                    mxclient_symlink)
                if current_real_mxclient_location != real_mxclient_location:
                    logger.debug("mxclientsystem symlink exists, but points "
                                 "to %s" % current_real_mxclient_location)
                    logger.debug("redirecting symlink to %s" %
                                 real_mxclient_location)
                    os.unlink(mxclient_symlink)
                    os.symlink(real_mxclient_location, mxclient_symlink)
            elif not os.path.exists(mxclient_symlink):
                logger.debug("creating mxclientsystem symlink pointing to %s" %
                             real_mxclient_location)
                try:
                    os.symlink(real_mxclient_location, mxclient_symlink)
                except OSError, e:
                    logger.error("creating symlink failed: %s" % e)
            else:
                logger.warn("Not touching mxclientsystem symlink: file exists "
                            "and is not a symlink")

    def _configure_logging(self):
        # try configure logging
        # catch:
        # - logsubscriber already exists -> ignore
        #   (TODO:functions to restart logging when config is changed?)
        # - logging already started -> ignore
        logger.debug("Setting up logging...")
        logging_config = self.config.get_logging_config()
        if len(logging_config) == 0:
            logger.warn("No logging settings found, this is probably not what "
                        "you want.")
        else:
            for log_subscriber in logging_config:
                m2eeresponse = self.client.create_log_subscriber(
                    log_subscriber)
                result = m2eeresponse.get_result()
                if result == 3:  # logsubscriber name exists
                    pass
                elif result != 0:
                    m2eeresponse.display_error()
            self.client.start_logging()

    def _send_jetty_config(self):
        # send jetty configuration
        jetty_opts = self.config.get_jetty_options()
        if jetty_opts:
            logger.debug("Sending Jetty configuration...")
            m2eeresponse = self.client.set_jetty_options(jetty_opts)
            result = m2eeresponse.get_result()
            if result != 0:
                logger.error("Setting Jetty options failed: %s" %
                             m2eeresponse.get_cause())

    def _send_mime_types(self):
        mime_types = self.config.get_mimetypes()
        if mime_types:
            logger.debug("Sending mime types...")
            m2eeresponse = self.client.add_mime_type(mime_types)
            result = m2eeresponse.get_result()
            if result != 0:
                logger.error("Setting mime types failed: %s" %
                             m2eeresponse.get_cause())

    def send_runtime_config(self):
        # send runtime configuration
        # catch and report:
        # - configuration errors (X is not a file etc)
        # XXX: fix mxruntime to report all errors and warnings in adminaction
        # feedback instead of stopping to process input
        # if errors, abort.

        config = copy.deepcopy(self.config.get_runtime_config())
        custom_config_25 = None
        if self.config.dirty_hack_is_25():
            custom_config_25 = config.pop('MicroflowConstants', None)

        # convert MyScheduledEvents from list to dumb comma separated string if
        # needed:
        if isinstance(config.get('MyScheduledEvents', None), list):
            logger.trace("Converting mxruntime MyScheduledEvents from list to "
                         "comma separated string...")
            config['MyScheduledEvents'] = ','.join(config['MyScheduledEvents'])

        logger.debug("Sending MxRuntime configuration...")
        m2eeresponse = self.client.update_configuration(config)
        result = m2eeresponse.get_result()
        if result == 1:
            logger.error("Sending configuration failed: %s" %
                         m2eeresponse.get_cause())
            logger.error("You'll have to fix the configuration and run start "
                         "again...")
            return False

        # if running 2.5.x we send the MicroflowConstants via
        # update_custom_configuration
        if custom_config_25:
            logger.debug("Sending 2.5.x custom configuration...")
            m2eeresponse = self.client.update_custom_configuration(
                custom_config_25)
            result = m2eeresponse.get_result()
            if result == 1:
                logger.error("Sending custom configuration failed: %s" %
                             m2eeresponse.get_cause())
                return False

        return True

    def set_log_level(self, subscriber, node, level):
        params = {"subscriber": subscriber, "node": node, "level": level}
        return self.client.set_log_level(params)

    def get_log_levels(self):
        params = {"sort": "subscriber"}
        m2ee_response = self.client.get_log_settings(params)
        return m2ee_response.get_feedback()

    def save_ddl_commands(self, ddl_commands):
        query_file_name = os.path.join(self.config.get_database_dump_path(),
                                       "%s_database_commands.sql" %
                                       time.strftime("%Y%m%d_%H%M%S"))
        logger.info("Saving DDL commands to %s" % query_file_name)
        fd = codecs.open(query_file_name, mode='w', encoding='utf-8')
        fd.write("%s" % '\n'.join(ddl_commands))
        fd.close()
