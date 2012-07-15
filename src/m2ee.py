#!/usr/bin/python
#
# Copyright (c) 2009-2012, Mendix bv
# All Rights Reserved.
# http://www.mendix.com/
#

import cmd
import subprocess
import os, sys, signal, pwd, getpass, atexit
import time, string, pprint
from m2ee.config import M2EEConfig
from m2ee.client import M2EEClient
from m2ee.runner import M2EERunner
from m2ee.pgutil import M2EEPgUtil
from m2ee.mdautil import M2EEMdaUtil
from m2ee.profile import M2EEProfiler
from m2ee.log import logger

class M2EE(cmd.Cmd):

    def __init__(self, yamlfiles=None):
        cmd.Cmd.__init__(self)
        self._yamlfiles = yamlfiles
        self._reload_config()
        username = pwd.getpwuid(os.getuid())[0]
        self._default_prompt = "m2ee(%s): " % username
        self.prompt = self._default_prompt
        logger.info("Application Name: %s" % self._config.get_app_name())
        self.do_status(None)
        self._logproc = None

    def _reload_config_if_changed(self):
        if self._config.mtime_changed():
            logger.info("Configuration change detected, reloading.")
            self._reload_config()

    def _reload_config(self):
        self._config = M2EEConfig(self._yamlfiles)
        self._client = M2EEClient('http://127.0.0.1:%s/' % self._config.get_admin_port(), self._config.get_admin_pass())
        self._runner = M2EERunner(self._config, self._client)
        if self._config.is_using_postgresql():
            self._pgutil = M2EEPgUtil(self._config)
        self._mdautil = M2EEMdaUtil(self._config)

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

    def do_restart(self, args):
        if self._stop():
            self._start()

    def do_stop(self, args):
        self._stop()

    def do_start(self, args):
        self._start()

    def _stop(self):
        self._reload_config_if_changed()
        (pid_alive, m2ee_alive) = self._check_alive()
        if not pid_alive and not m2ee_alive:
            logger.info("Nothing to stop, the application is not running.")
            return True

        logger.debug("Trying to stop the application.")
        stopped = False

        # first of all, try issuing shutdown command, so the mendix process can cleanup and stop stuff correctly
        logger.info("Waiting for the application to shutdown...")
        stopped = self._runner.stop(timeout=10) # waits a bit for the process to disappear
        # if stopped, the process and pidfile are gone
        if stopped:
            logger.info("The application has been stopped successfully.")
            return True

        # if not, we know either shutdown did not respond, or it did not finish as fast as we'd like it to
        logger.warn("The application did not shutdown by itself yet...")
        answer = None
        while not answer in ('y','n'):
            answer = raw_input("Do you want to try to signal the JVM process to stop immediately? (y)es, (n)o? ")
            if answer == 'y':
                logger.info("Waiting for the JVM process to disappear...")
                stopped = self._runner.terminate(timeout=10)
                if stopped:
                    logger.info("The JVM process has been stopped.")
                    return True
            elif answer == 'n':
                logger.info("Doing nothing, use stop again to check if the process finally disappeared...")
                return False
            else:
                print "Unknown option", answer

        # so we chose to SIGTERM, but it did not TERM...
        logger.warn("The application process seems not to respond to any command or signal.")
        answer = None
        while not answer in ('y','n'):
            answer = raw_input("Do you want to kill the JVM process? (y)es, (n)o? ")
            if answer == 'y':
                logger.info("Waiting for the JVM process to disappear...")
                stopped = self._runner.kill(timeout=10)
                if stopped:
                    logger.info("The JVM process has been destroyed.")
                    return True
            elif answer == 'n':
                logger.info("Doing nothing, use stop again to check if the process finally disappeared...")
                return False
            else:
                print "Unknown option", answer

        logger.error("Stopping the application process failed thorougly.")
        return False

    def _start(self):
        self._reload_config_if_changed()
        (pid_alive, m2ee_alive) = self._check_alive()
        if not pid_alive and not m2ee_alive:
            logger.info("Trying to start the MxRuntime...")
            if not self._runner.start():
                return
        elif not m2ee_alive:
            return

        # check status, if it's created or starting, go on, else stop
        m2eeresponse = self._client.runtime_status()
        if m2eeresponse.has_error():
            m2eeresponse.display_error()
            return
        status = m2eeresponse.get_feedback()['status']
        if not status in ['created','starting']:
            logger.error("Cannot start MxRuntime when it has status %s" % status)
            return
        logger.debug("MxRuntime status: %s" % status)

        self._fix_mxclientsystem_symlink()

        # go do startup sequence
        self._configure_logging()
        self._send_jetty_config()
        self._send_mime_types()

        if not self._send_runtime_config():
            # stop when sending configuration causes error messages
            return

        # try hitting the runtime until it breaks or stops complaining
        abort = False
        params = {}
        while not abort:
            startresponse = self._client.start(params)
            result = startresponse.get_result()
            if result == 0: # \o/
                abort = True
                logger.info("The MxRuntime is fully started now.")
            else:
                logger.error(startresponse.get_message())
                if result == 2: # db does not exist
                    answer = self._ask_user_whether_to_create_db()
                    if answer == 'a':
                        abort = True
                    elif self._config._dirty_hack_is_25 and answer == 'c':
                        params["autocreatedb"] = True
                elif result == 3: # ddl commands needed to sync domain model with db structure
                    answer = self._handle_ddl_commands()
                    if answer == 'a':
                        abort = True
                elif result == 4: # missing constant definition
                    answer = self._ask_user_to_fix_constants()
                    if answer == 'a':
                        abort = True
                elif result == 5: # admin account with password 1 detected
                    self._handle_admin_1(startresponse.get_feedback()['users'])
                elif result == 6: # invalid_state
                    abort = True
                elif result == 7 or result == 8 or result == 9: # missing config values
                    logger.error("You'll have to fix the configuration and run start again... (or ask for help..)")
                    abort = True
                else:
                    logger.error("%s Caused by: %s" % (startresponse.get_message(), startresponse.get_cause()))
                    abort = True

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

    def _ask_user_whether_to_create_db(self):
        answer = None
        while not answer in ('c','r','a'):
            if self._config.get_dtap_mode()[0] in 'DT':
                answer = raw_input("Do you want to (c)reate, (r)etry, or (a)bort: ")
            else:
                answer = raw_input("Do you want to (r)etry, or (a)bort: ")
            if answer in ('a','r'):
                pass
            elif answer == 'c':
                if not self._config.get_dtap_mode()[0] in ('D','T'):
                    logger.error("Automatic Database creation is disabled in Acceptance and Production mode!")
                    answer = None
                elif not self._config.dirty_hack_is_25():
                    # call execute_ddl_commands, because since 3.0, this tries to create a database
                    # and immediately executes initial ddl commands
                    m2eeresponse = self._client.execute_ddl_commands()
                    m2eeresponse.display_error()
            else:
                print "Unknown option", answer
        return answer
    
    def _handle_ddl_commands(self):
        feedback = self._client.get_ddl_commands({"verbose":True}).get_feedback()
        answer = None
        while not answer in ('v','s','e','a'):
            answer = raw_input("Do you want to (v)iew queries, (s)ave them to a file, (e)xecute and save them, or (a)bort: ")
            if answer in set(('a',)): # design for tomorrow!!~`1 (note the extra efficient handling by using a set)
                pass
            elif answer == 'v':
                print '\n'.join(feedback['ddl_commands'])
                answer = None
            elif answer in ('e','s'):
                query_file_name = os.path.join(self._config.get_database_dump_path(),
                        "%s_database_commands.sql" % time.strftime("%Y%m%d_%H%M%S"))
                logger.info("Saving DDL commands to %s" % query_file_name)
                open(query_file_name,'w+').write("%s" % '\n'.join(feedback['ddl_commands']))
                if answer == 'e':
                    m2eeresponse = self._client.execute_ddl_commands()
                    m2eeresponse.display_error()
            else:
                print "Unknown option", answer
        return answer

    def _ask_user_to_fix_constants(self):
        answer = None
        # list of constant names was already printed as part of the error message from the runtime
        logger.error("You'll have to add the constant definitions to the configuration in the 'custom' section.")
        while not answer in ('r','a'):
            answer = raw_input("Do you want to (r)etry, or (a)bort: ")
            if answer not in ('a','r'):
                print "Unknown option", answer
        return answer

    def _handle_admin_1(self, users):
        answer = None
        while not answer in ('c','a'):
            answer = raw_input("Do you want to (c)hange passwords or (a)bort: ")
            if answer == 'a':
                pass
            elif answer == 'c':
                for username in users:
                    changed = False
                    while not changed:
                        newpw1 = getpass.getpass("Type new password for user %s: " % username)
                        newpw2 = getpass.getpass("Type new password for user %s again: " % username)
                        if newpw1 != newpw2:
                            print "The passwords are not equal!"
                        else:
                            m2eeresponse = self._client.update_admin_user({"username": username, "password": newpw1})
                            m2eeresponse.display_error()
                            if not m2eeresponse.has_error():
                                changed = True
            else:
                print "Unknown option", answer

    def do_create_admin_user(self, args=None):
        self._reload_config_if_changed()
        (pid_alive, m2ee_alive) = self._check_alive()
        if not m2ee_alive:
            logger.warn("The application process needs to be running to create a user object in the application.")
            return
        print "This option will create an administrative user account, using the preset username and user role settings."
        newpw1 = getpass.getpass("Type new password for this user: ")
        newpw2 = getpass.getpass("Type new password for this user again: ")
        if newpw1 != newpw2:
            print "The passwords are not equal!"
        else:
            m2eeresponse = self._client.create_admin_user({"password": newpw1})
            m2eeresponse.display_error()

    def do_update_admin_user(self, args=None):
        self._reload_config_if_changed()
        (pid_alive, m2ee_alive) = self._check_alive()
        if not m2ee_alive:
            logger.warn("The application process needs to be running to change user objects in the application.")
            return
        print "Using this function you can reset the password of an administrative user account."
        username = raw_input("User name: ")
        newpw1 = getpass.getpass("Type new password for user %s: " % username)
        newpw2 = getpass.getpass("Type new password for user %s again: " % username)
        if newpw1 != newpw2:
            print "The passwords are not equal!"
        else:
            m2eeresponse = self._client.update_admin_user({"username": username, "password": newpw1})
            m2eeresponse.display_error()

    def do_debug(self, args):
        answer = raw_input("This command will throw you into a local python debug session inside the M2EE object! Continue (y/N)?")
        if answer == 'y':
            import code
            code.interact(local=locals())

    def do_status(self, args):
        self._reload_config_if_changed()
        if self._report_not_running():
            return
        feedback = self._client.runtime_status().get_feedback()
        logger.info("The application process is running, the MxRuntime has status: %s" % feedback['status'])

        # look if any critical message was logged
        critlist = self._client.get_critical_log_messages()
        if len(critlist) > 0:
            logger.error("%d critical error(s) were logged. Use show_critical_log_messages to view them." % len(critlist))

        max_show_users = 10
        total_users = self._who(max_show_users)
        if total_users > max_show_users:
            logger.info("Only showing %s logged in users. Use who to see a complete list." % max_show_users)

    def do_show_critical_log_messages(self, args):
        self._reload_config_if_changed()
        if self._report_not_running():
            return

        critlist = self._client.get_critical_log_messages()
        if len(critlist) == 0:
            logger.info("No messages were logged to a critical loglevel since starting the application.")
            return
        print "\n".join(critlist)

    def do_check_health(self, args):
        if self._report_not_running():
            return
        health_response = self._client.check_health()
        if not health_response.has_error():
            feedback = health_response.get_feedback()
            if feedback['health'] == 'healthy':
                logger.info("Health check microflow says the application is healthy.")
            elif feedback['health'] == 'sick':
                logger.warning("Health check microflow says the application is sick: %s" % feedback['diagnosis'])
            elif feedback['health'] == 'unknown':
                logger.info("Health check microflow is not configured, no health information available.")
            else:
                logger.error("Unexpected health check status: %s" % feedback['health'])
        else:
            # Yes, we need API versioning!
            if health_response.get_result() == 3 and health_response.get_cause() == "java.lang.IllegalArgumentException: Action should not be null":
                # b0rk, b0rk, b0rk, in 2.5.4 or 2.5.5 this means that the runtime is health-check
                # capable, but no health check microflow is defined
                logger.info("Health check microflow is probably not configured, no health information available.")
            elif health_response.get_result() == health_response.ERR_ACTION_NOT_FOUND:
                # Admin action 'check_health' does not exist.
                logger.info("The Mendix version you are running does not yet support health check functionality.")
            else:
                health_response.display_error()

    def do_statistics(self, args):
        self._reload_config_if_changed()
        if self._report_not_running():
            return
        stats = self._client.runtime_statistics().get_feedback()
        stats.update(self._client.server_statistics().get_feedback())
        pprint.pprint(stats)

    def do_munin_config(self, args):
        import m2ee.munin
        m2ee.munin.print_all(self._client, self._config.get_munin_options(), args, config=True)

    def do_munin_values(self, args):
        import m2ee.munin
        m2ee.munin.print_all(self._client, self._config.get_munin_options(), args)

    def do_nagios(self, args):
        import m2ee.nagios
        logger.info("The nagios plugin will exit m2ee after running, this is by design, don't report it as bug.")
        # TODO: possible to propagate return value through cmd to exit?
        sys.exit(m2ee.nagios.check(self._runner, self._client))

    def do_about(self, args):
        self._reload_config_if_changed()
        if self._report_not_running():
            return
        feedback = self._client.about().get_feedback()
        print "Using %s version %s" % (feedback['name'], feedback['version'])
        print feedback['copyright']
        if 'company' in feedback:
            print 'Project company name is %s' % feedback['company']
        if 'partner' in feedback:
            print 'Project partner name is %s' % feedback['partner']

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

    def do_who(self, args):
        self._reload_config_if_changed()
        if self._report_not_running():
            return
        if args:
            try:
                limitint = int(args)
                self._who(limitint)
            except ValueError:
                logger.warn("Could not parse argument to an integer. Use a number as argument to limit the amount of logged in users shown.")
        else:
            self._who()

    def do_w(self, args):
        self.do_who(args)

    # deprecated
    def do_get_logged_in_user_names(self, args):
        logger.warn("get_logged_in_user_names is deprectated, use the more friendly command 'who', or even the alias 'w' instead! :)")
        self.do_who(args)

    def do_reload(self, args):
        logger.debug("Reloading configuration...")
        self._reload_config()

    def do_dump_config(self, args):
        self._reload_config_if_changed()
        self._config.dump()

    def do_psql(self, args):
        self._reload_config_if_changed()
        if not self._config.is_using_postgresql():
            logger.warn("Only PostgreSQL databases are supported right now.")
        self._pgutil.psql()

    def do_dumpdb(self, args):
        self._reload_config_if_changed()
        if not self._config.is_using_postgresql():
            logger.warn("Only PostgreSQL databases are supported right now.")
        self._pgutil.dumpdb()

    def do_restoredb(self, args):
        self._reload_config_if_changed()
        if not self._config.is_using_postgresql():
            logger.warn("Only PostgreSQL databases are supported right now.")
        if not args:
            logger.error("restoredb needs the name of a dump file in %s as argument" % self._config.get_database_dump_path())
            return
        (pid_alive, m2ee_alive) = self._check_alive()
        if pid_alive or m2ee_alive:
            logger.warn("The application is still running, refusing to restore the database right now.")
            return
        self._pgutil.restoredb(args)

    def complete_restoredb(self, text, line, begidx, endidx):
        if not self._config.is_using_postgresql():
            return []
        return self._pgutil.complete_restoredb(text)

    def do_emptydb(self, args):
        self._reload_config_if_changed()
        (pid_alive, m2ee_alive) = self._check_alive()
        if pid_alive or m2ee_alive:
            logger.warn("The application process is still running, refusing to empty the database right now.")
            return
        if not self._config.is_using_postgresql():
            logger("Only PostgreSQL databases are supported right now.")
            return
        self._pgutil.emptydb()

    def do_unpack(self, args):
        self._reload_config_if_changed()
        if not args:
            logger.error("unpack needs the name of a model upload zipfile in %s as argument" % self._config.get_model_upload_path())
            return
        (pid_alive, m2ee_alive) = self._check_alive()
        if pid_alive or m2ee_alive:
            logger.error("The application process is still running, refusing to unpack a new application model right now.")
            return
        if self._mdautil.unpack(args):
            self._reload_config()
        post_unpack_hook = self._config.get_post_unpack_hook()
        if post_unpack_hook:
            if os.path.isfile(post_unpack_hook):
                if os.access(post_unpack_hook, os.X_OK):
                    logger.info ("Running post-unpack-hook...")
                    retcode = subprocess.call((post_unpack_hook,))
                    if retcode != 0:
                        logger.error("The post-unpack-hook returned a non-zero exit code: %d" % retcode)
                else:
                    logger.error("post-unpack-hook script %s is not executable." % post_unpack_hook)
            else:
                logger.error("post-unpack-hook script %s does not exist." % post_unpack_hook)
    
    def complete_unpack(self, text, line, begidx, endidx):
        return self._mdautil.complete_unpack(text)

    def do_log(self, args):
        if self.cleanup_logging():
            return
        logfile = self._config.get_logfile()
        if not logfile:
            logging.warn("logfile location is not specified")
            return
        print "This command will start printing log information from the application"
        print "right in the middle of all of the other output on your screen. This can"
        print "be confusing, especially when you're typing something and everything"
        print "gets messed up by the logging. Typing log again will turn off logging"
        print "output."
        answer = raw_input("Do you want to start log output (y/N): ")
        if answer == 'y':
            cmd = ("tail", "-F", logfile)
            proc = subprocess.Popen(cmd)
            self._logproc = proc
            self.prompt = "LOG %s" % self._default_prompt

    def do_loglevel(self, args):
        if self._report_not_running():
            return
        args = string.split(args)
        if len(args) == 3:
            (subscriber, node, level) = args
            self._set_log_level(subscriber, node, level)
        else:
            if len(args) == 0:
                self._get_log_levels()
            print "To adjust loglevels, use: loglevel <subscribername> <lognodename> <level>"
            print "Available levels: NONE, CRITICAL, ERROR, WARNING, INFO, DEBUG, TRACE"

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

    def cleanup_logging(self):
        # atexit
        if self._logproc:
            logger.debug("Stopping log output...")
            self.prompt = self._default_prompt
            if not self._logproc.poll():
                os.kill(self._logproc.pid, signal.SIGTERM)
            self._logproc = None
            return True
        return False

    def emptyline(self):
        self._reload_config_if_changed()
        pass

    def do_exit(self, args):
        return -1

    def do_quit(self, args):
        return -1

    def do_EOF(self, args):
        print
        return -1

    def do_profiler(self, args):
        print "The profiler module in this program is experimental functionality and"
        print "should not be used in production environments. Incorrect use of the"
        print "profiler can cause out of memory errors on applications that handle"
        print "a lot of requests."
        answer = raw_input("Start profiler? (y/N): ")
        if answer == 'y':
            M2EEProfiler(self._client).cmdloop()

    # simple hook to log usage
    def precmd(self, line):
        if line:
            logger.trace("Executing command: %s" % line)
        return line

    def do_help(self, args):
        print "Welcome to m2ee, the Mendix Runtime helper tools."
        print
        print "Available commands:"
        print " unpack - unpack an uploaded Mendix Deployment Archive from data/model-upload"
        print " start - try starting the application using the unpacked deployment files"
        print " stop - stop the application"
        print " restart - restart the application"
        print " status - display Mendix Runtime status (is the application running?)"
        print " check_health - manually execute health check"
        print " create_admin_user - create first user when starting with an empty database"
        print " update_admin_user - reset the password of an application user"
        print " who, w - show currently logged in users"
        print " log - follow live logging from the application"
        print " loglevel - view and configure loglevels"
        print " profiler - start the profiler (experimental) "
        print " about - show Mendix Runtime version information"
        print " exit, quit, <ctrl>-d - exit m2ee"
        print
        print "When using PostgreSQL, you can also use:"
        print " psql - start the postgresql shell"
        print " dumpdb - create a database dump into the data/database folder"
        print " emptydb - drop all tables and sequences from the database"
        print " restoredb - restore a database dump from the data/database folder"
        print 
        print "Extra commands you probably don't need:"
        print " debug - dive into a local python debug session inside this program"
        print " dump_config - dump the yaml configuration information"
        print " reload - reload configuration from yaml files (this is done automatically)"
        print " statistics - show all application statistics that can be used for monitoring"
        print " munin_config - configure option for the built-in munin plugin"
        print " munin_values - show monitoring output gathered by the built-in munin plugin"
        print " nagios - execute the built-in nagios plugin (will exit m2ee)"
        print
        print "Hint: use tab autocompletion for commands!"

if __name__ == '__main__':
    from optparse import OptionParser
    parser = OptionParser()
    parser.add_option("-c", action="append", type="string", dest="yamlfiles")
    parser.add_option("-v", "--verbose", action="count", dest="verbose",
            help="increase verbosity of output (-vv to be even more verbose)")
    parser.add_option("-q", "--quiet", action="count", dest="quiet",
            help="decrease verbosity of output (-qq to be even more quiet)")
    (options, args) = parser.parse_args()

    # how verbose should we be? see http://docs.python.org/release/2.7/library/logging.html#logging-levels
    verbosity = 0
    if options.quiet:
        verbosity = verbosity + options.quiet
    if options.verbose:
        verbosity = verbosity - options.verbose
    verbosity = verbosity * 10 + 20
    if verbosity > 50:
        verbosity = 50
    if verbosity < 5:
        verbosity = 5
    logger.setLevel(verbosity)

    m2ee = M2EE(options.yamlfiles)
    atexit.register(m2ee.cleanup_logging)
    if args:
        m2ee.onecmd(' '.join(args))
    else:
        m2ee.cmdloop()

