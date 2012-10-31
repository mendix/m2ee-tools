#!/usr/bin/python

import cmd
import subprocess
import atexit
from m2ee import pgutil, M2EE, M2EEProfiler, mdautil
from m2ee.log import logger
from m2ee.config import find_yaml_files
import os, pwd, sys, getpass, signal
import string, pprint, yaml

class CLI(cmd.Cmd):

    def __init__(self, yamlfiles=None):
        cmd.Cmd.__init__(self)
        self.m2ee = M2EE(yamlfiles)
        self.do_status(None)
        username = pwd.getpwuid(os.getuid())[0]
        self._default_prompt = "m2ee(%s): " % username
        self.prompt = self._default_prompt
        logger.info("Application Name: %s" % self.m2ee.config.get_app_name())

    def do_restart(self, args):
        if self._stop():
            if not self.m2ee.start_appcontainer():
                return
            self._start_runtime()

    def do_stop(self, args):
        self._stop()

    def do_start(self, args):
        if not self.m2ee.start_appcontainer():
            return
        self._start_runtime()

    def _stop(self):
        (pid_alive, m2ee_alive) = self.m2ee.check_alive()
        if not pid_alive and not m2ee_alive:
            logger.info("Nothing to stop, the application is not running.")
            return True

        logger.debug("Trying to stop the application.")
        stopped = False

        # first of all, try issuing shutdown command, so the mendix process can cleanup and stop stuff correctly
        logger.info("Waiting for the application to shutdown...")
        stopped = self.m2ee.runner.stop(timeout=10) # waits a bit for the process to disappear
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
                stopped = self.m2ee.runner.terminate(timeout=10)
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
                stopped = self.m2ee.runner.kill(timeout=10)
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

    def _start_runtime(self):
        self.m2ee.fix_mxclientsystem_symlink()

        if not self.m2ee.send_runtime_config():
            # stop when sending configuration causes error messages
            return

        # try hitting the runtime until it breaks or stops complaining
        abort = False
        params = {}
        while not abort:
            startresponse = self.m2ee.client.start(params)
            result = startresponse.get_result()
            if result == 0: # \o/
                abort = True
                logger.info("The MxRuntime is fully started now.")
            else:
                startresponse.display_error()
                if result == 2: # db does not exist
                    answer = self._ask_user_whether_to_create_db()
                    if answer == 'a':
                        abort = True
                    elif self.m2ee.config._dirty_hack_is_25 and answer == 'c':
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
                    answer = self._handle_admin_1(startresponse.get_feedback()['users'])
                    if answer == 'a':
                        abort = True
                elif result == 6: # invalid_state
                    abort = True
                elif result == 7 or result == 8 or result == 9: # missing config values
                    logger.error("You'll have to fix the configuration and run start again... (or ask for help..)")
                    abort = True
                else:
                    abort = True

    def _ask_user_whether_to_create_db(self):
        answer = None
        while not answer in ('c','r','a'):
            if self.m2ee.config.get_dtap_mode()[0] in 'DT':
                answer = raw_input("Do you want to (c)reate, (r)etry, or (a)bort: ")
            else:
                answer = raw_input("Do you want to (r)etry, or (a)bort: ")
            if answer in ('a','r'):
                pass
            elif answer == 'c':
                if not self.m2ee.config.get_dtap_mode()[0] in ('D','T'):
                    logger.error("Automatic Database creation is disabled in Acceptance and Production mode!")
                    answer = None
                elif not self.m2ee.config.dirty_hack_is_25():
                    # call execute_ddl_commands, because since 3.0, this tries to create a database
                    # and immediately executes initial ddl commands
                    m2eeresponse = self.m2ee.client.execute_ddl_commands()
                    m2eeresponse.display_error()
            else:
                print "Unknown option", answer
        return answer
    
    def _handle_ddl_commands(self):
        feedback = self.m2ee.client.get_ddl_commands({"verbose":True}).get_feedback()
        answer = None
        while not answer in ('v','s','e','a'):
            answer = raw_input("Do you want to (v)iew queries, (s)ave them to a file, (e)xecute and save them, or (a)bort: ")
            if answer in set(('a',)): # design for tomorrow!!~`1 (note the extra efficient handling by using a set)
                pass
            elif answer == 'v':
                print '\n'.join(feedback['ddl_commands'])
                answer = None
            elif answer in ('e','s'):
                ddl_commands = feedback['ddl_commands']
                self.m2ee.save_ddl_commands(ddl_commands)
                if answer == 'e':
                    m2eeresponse = self.m2ee.client.execute_ddl_commands()
                    m2eeresponse.display_error()
            else:
                print "Unknown option", answer
        return answer

    def _ask_user_to_fix_constants(self):
        answer = None
        # list of constant names was already printed as part of the error message from the runtime
        logger.error("You'll have to add the constant definitions to the configuration in the MicroflowConstants section.")
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
                            m2eeresponse = self.m2ee.client.update_admin_user({"username": username, "password": newpw1})
                            m2eeresponse.display_error()
                            if not m2eeresponse.has_error():
                                changed = True
            else:
                print "Unknown option", answer
        return answer

    def do_create_admin_user(self, args=None):
        (pid_alive, m2ee_alive) = self.m2ee.check_alive()
        if not m2ee_alive:
            logger.warn("The application process needs to be running to create a user object in the application.")
            return
        print "This option will create an administrative user account, using the preset username and user role settings."
        newpw1 = getpass.getpass("Type new password for this user: ")
        newpw2 = getpass.getpass("Type new password for this user again: ")
        if newpw1 != newpw2:
            print "The passwords are not equal!"
        else:
            m2eeresponse = self.m2ee.client.create_admin_user({"password": newpw1})
            m2eeresponse.display_error()

    def do_update_admin_user(self, args=None):
        (pid_alive, m2ee_alive) = self.m2ee.check_alive()
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
            m2eeresponse = self.m2ee.client.update_admin_user({"username": username, "password": newpw1})
            m2eeresponse.display_error()

    def do_debug(self, args):
        answer = raw_input("This command will throw you into a local python debug session inside the M2EE object! Continue (y/N)?")
        if answer == 'y':
            import code
            code.interact(local=locals())

    def do_status(self, args):
        if self._report_not_running():
            return
        feedback = self.m2ee.client.runtime_status().get_feedback()
        logger.info("The application process is running, the MxRuntime has status: %s" % feedback['status'])

        # look if any critical message was logged
        critlist = self.m2ee.client.get_critical_log_messages()
        if len(critlist) > 0:
            logger.error("%d critical error(s) were logged. Use show_critical_log_messages to view them." % len(critlist))

        max_show_users = 10
        total_users = self._who(max_show_users)
        if total_users > max_show_users:
            logger.info("Only showing %s logged in users. Use who to see a complete list." % max_show_users)

    def do_show_critical_log_messages(self, args):
        if self._report_not_running():
            return

        critlist = self.m2ee.client.get_critical_log_messages()
        if len(critlist) == 0:
            logger.info("No messages were logged to a critical loglevel since starting the application.")
            return
        print "\n".join(critlist)

    def do_check_health(self, args):
        if self._report_not_running():
            return
        health_response = self.m2ee.client.check_health()
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
        if self._report_not_running():
            return
        stats = self.m2ee.client.runtime_statistics().get_feedback()
        stats.update(self.m2ee.client.server_statistics().get_feedback())
        pprint.pprint(stats)

    def do_munin_config(self, args):
        import m2ee.munin
        m2ee.munin.print_all(self.m2ee.client, self.m2ee.config, self.m2ee.config.get_munin_options(), args, print_config=True)

    def do_munin_values(self, args):
        import m2ee.munin
        m2ee.munin.print_all(self.m2ee.client, self.m2ee.config, self.m2ee.config.get_munin_options(), args)

    def do_nagios(self, args):
        import m2ee.nagios
        logger.info("The nagios plugin will exit m2ee after running, this is by design, don't report it as bug.")
        # TODO: possible to propagate return value through cmd to exit?
        sys.exit(m2ee.nagios.check(self.m2ee.runner, self.m2ee.client))

    def do_about(self, args):
        if self._report_not_running():
            return
        feedback = self.m2ee.client.about().get_feedback()
        print "Using %s version %s" % (feedback['name'], feedback['version'])
        print feedback['copyright']
        if 'company' in feedback:
            print 'Project company name is %s' % feedback['company']
        if 'partner' in feedback:
            print 'Project partner name is %s' % feedback['partner']

    def do_show_license_information(self, args):
        if self._report_not_running():
            return
        m2eeresp = self.m2ee.client.get_license_information()
        if m2eeresp.get_result() == m2eeresp.ERR_ACTION_NOT_FOUND:
            logger.error("This action is not available in the Mendix Runtime version you are currently using.")
            logger.error("It was implemented in Mendix 3.0.0")
            return
        m2eeresp.display_error()
        if not m2eeresp.has_error():
            feedback = m2eeresp.get_feedback()
            if 'license' in feedback:
                print yaml.dump((feedback['license']))
            elif 'license_id' in feedback:
                print "Unlicensed environment."
                print "Server ID: %s" % feedback['license_id']
            else:
                print "Unlicensed environment."

    def do_activate_license(self, args):
        if self._report_not_running():
            return
        print "The command activate_license will set the license key used in this application. " \
              "As far as currently known, recent Mendix Runtime versions do not check the submitted " \
              "license key for validity, so incorrect input will unconditionally un-license " \
              "your Mendix application! After setting the license, there will be no feedback about " \
              "validity of the license. You can use show_license_information to check the active license."
        answer = raw_input("Do you want to continue anyway? (type YES if you want to): ")
        if answer != 'YES':
            print "Aborting."
            return
        license_key = raw_input("Paste your license key (a long text string without newlines line): ")
        m2eeresp = self.m2ee.client.set_license({'license_key': license_key})
        if m2eeresp.get_result() == m2eeresp.ERR_ACTION_NOT_FOUND:
            logger.error("This action is not available in the Mendix Runtime version you are currently using.")
            logger.error("It was implemented in Mendix 3.0.0")
            return
        m2eeresp.display_error()
        # no usable feedback, anyway, not as of 4.1.0

    def do_who(self, args):
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
        self.m2ee.reload_config()

    def do_dump_config(self, args):
        self.m2ee.config.dump()

    def do_psql(self, args):
        if not self.m2ee.config.is_using_postgresql():
            logger.error("Only PostgreSQL databases are supported right now.")
            return
        pgutil.psql(
            self.m2ee.config.get_pg_environment(),
            self.m2ee.config.get_psql_binary(),
        )

    def do_dumpdb(self, args):
        if not self.m2ee.config.is_using_postgresql():
            logger.error("Only PostgreSQL databases are supported right now.")
            return
        pgutil.dumpdb(
            self.m2ee.config.get_pg_environment(),
            self.m2ee.config.get_pg_dump_binary(),
            self.m2ee.config.get_database_dump_path(),
        )

    def do_restoredb(self, args):
        if not self.m2ee.config.is_using_postgresql():
            logger.error("Only PostgreSQL databases are supported right now.")
            return
        if not self.m2ee.config.allow_destroy_db():
            logger.error("Destructive database operations are turned off.")
            return
        if not args:
            logger.error("restoredb needs the name of a dump file in %s as argument" % self.m2ee.config.get_database_dump_path())
            return
        (pid_alive, m2ee_alive) = self.m2ee.check_alive()
        if pid_alive or m2ee_alive:
            logger.warn("The application is still running, refusing to restore the database right now.")
            return
        pgutil.restoredb(
            self.m2ee.config.get_pg_environment(),
            self.m2ee.config.get_pg_restore_binary(),
            self.m2ee.config.get_database_dump_path(),
            args,
        )

    def complete_restoredb(self, text, line, begidx, endidx):
        if not self.m2ee.config.is_using_postgresql():
            return []
        return pgutil.complete_restoredb(
            self.m2ee.config.get_database_dump_path(),
            text,
        )

    def do_emptydb(self, args):
        if not self.m2ee.config.is_using_postgresql():
            logger.error("Only PostgreSQL databases are supported right now.")
            return
        if not self.m2ee.config.allow_destroy_db():
            logger.error("Destructive database operations are turned off.")
            return
        (pid_alive, m2ee_alive) = self.m2ee.check_alive()
        if pid_alive or m2ee_alive:
            logger.warn("The application process is still running, refusing to empty the database right now.")
            return
        pgutil.emptydb(
            self.m2ee.config.get_pg_environment(),
            self.m2ee.config.get_psql_binary(),
        )

    def do_unpack(self, args):
        if not args:
            logger.error("unpack needs the name of a model upload zipfile in %s as argument" % self.m2ee.config.get_model_upload_path())
            return
        (pid_alive, m2ee_alive) = self.m2ee.check_alive()
        if pid_alive or m2ee_alive:
            logger.error("The application process is still running, refusing to unpack a new application model right now.")
            return
        if mdautil.unpack(
            self.m2ee.config.get_model_upload_path(),
            args,
            self.m2ee.config.get_app_base(),
        ):
            self.m2ee.reload_config()
        post_unpack_hook = self.m2ee.config.get_post_unpack_hook()
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
        # these complete functions seem to eat exceptions, which is very bad behaviour
        # if anything here throws an excaption, you just won't get completion, without
        # knowing why
        return mdautil.complete_unpack(self.m2ee.config.get_model_upload_path(), text)
    
    def do_log(self, args):
        if self._cleanup_logging():
            return
        logfile = self.m2ee.config.get_logfile()
        if not logfile:
            logger.warn("logfile location is not specified")
            return
        print "This command will start printing log information from the application " \
              "right in the middle of all of the other output on your screen. This can " \
              "be confusing, especially when you're typing something and everything " \
              "gets messed up by the logging. Typing log again will turn off logging " \
              "output."
        answer = raw_input("Do you want to start log output (y/N): ")
        if answer == 'y':
            cmd = ("tail", "-F", logfile)
            proc = subprocess.Popen(cmd)
            self.m2ee._logproc = proc
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
        log_levels = self.m2ee.get_log_levels()
        print "Current loglevels:"
        log_subscribers = []
        for (subscriber_name, node_names) in log_levels.iteritems(): 
            for (node_name, subscriber_level) in node_names.iteritems():
                log_subscribers.append("%s %s %s" % 
                        (subscriber_name, node_name, subscriber_level))
        log_subscribers.sort()
        print("\n".join(log_subscribers))

    def _set_log_level(self, subscriber, node, level):
        level = level.upper()
        response = self.m2ee.set_log_level(subscriber, node, level)
        if response.has_error():
            response.display_error()
            print "Remember, all parameters are case sensitive"
        else:
            logger.info("Loglevel for %s set to %s" % (node, level))

    def _report_not_running(self):
        """
        To be used by actions to see whether m2ee is available for executing requests.
        Also prints a line when the application is not running.

        if self._report_not_running():
            return
        do_things_that_communicate_using_m2ee_client()

        returns True when m2ee is not available for requests, else False
        """
        (pid_alive, m2ee_alive) = self.m2ee.check_alive()
        if not pid_alive and not m2ee_alive:
            logger.info("The application process is not running.")
            return True
        # if pid is alive, but m2ee does not respond, errors are already printed by check_alive
        if pid_alive and not m2ee_alive:
            return True
        return False

    def do_show_current_runtime_requests(self, args):
        if self._report_not_running():
            return
        m2eeresp = self.m2ee.client.get_current_runtime_requests()
        if m2eeresp.get_result() == m2eeresp.ERR_ACTION_NOT_FOUND:
            logger.error("This action is not available in the Mendix Runtime version you are currently using.")
            logger.error("It was implemented in Mendix 2.5.8 and 3.1.0")
            return
        m2eeresp.display_error()
        if not m2eeresp.has_error():
            feedback = m2eeresp.get_feedback()
            if not feedback:
                logger.info("There are no currently running runtime requests.")
            else:
                print "Current running Runtime Requests:"
                print yaml.dump(feedback)

    def do_show_all_thread_stack_traces(self, args):
        if self._report_not_running():
            return
        m2eeresp = self.m2ee.client.get_all_thread_stack_traces()
        if m2eeresp.get_result() == m2eeresp.ERR_ACTION_NOT_FOUND:
            logger.error("This action is not available in the Mendix Runtime version you are currently using.")
            logger.error("It was implemented in Mendix 3.2.0")
            return
        m2eeresp.display_error()
        if not m2eeresp.has_error():
            feedback = m2eeresp.get_feedback()
            print "Current JVM Thread Stacktraces:"
            print pprint.pprint(feedback)

    def do_interrupt_request(self, args):
        if self._report_not_running():
            return
        if args == "":
            logger.error("This function needs a request id as parameter")
            logger.error("Use show_current_runtime_requests to view currently running requests")
            return
        m2eeresp = self.m2ee.client.interrupt_request({"request_id":args})
        if m2eeresp.get_result() == m2eeresp.ERR_ACTION_NOT_FOUND:
            logger.error("This action is not available in the Mendix Runtime version you are currently using.")
            logger.error("It was implemented in Mendix 2.5.8 and 3.1.0")
            return
        m2eeresp.display_error()
        if not m2eeresp.has_error():
            feedback = m2eeresp.get_feedback()
            if feedback["result"] == False:
                logger.error("A request with ID %s was not found" % args)
            else:
                logger.info("An attempt to cancel the running action was made.")

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
            M2EEProfiler(self.m2ee.client).cmdloop()

    def _cleanup_logging(self):
        # atexit
        if self.m2ee._logproc:
            logger.debug("Stopping log output...")
            self.prompt = self._default_prompt
            if not self.m2ee._logproc.poll():
                os.kill(self.m2ee._logproc.pid, signal.SIGTERM)
            self.m2ee._logproc = None
            return True
        return False

    def _who(self, limitint=None):
        limit = {}
        if limitint != None:
            limit = {"limit": limitint}
        m2eeresp = self.m2ee.client.get_logged_in_user_names(limit)
        m2eeresp.display_error()
        if not m2eeresp.has_error():
            feedback = m2eeresp.get_feedback()
            logger.info("Logged in users: (%s) %s" % (feedback['count'], feedback['users']))
            return feedback['count']
        return 0

    # simple hook to log usage and reload config if changed
    def precmd(self, line):
        self.m2ee.reload_config_if_changed()
        if line:
            logger.trace("Executing command: %s" % line)
        return line

    # if the emptyline function is not defined, Cmd will automagically
    # repeat the previous command given, and that's not what we want
    def emptyline(self):
        pass

    def do_help(self, args):
        print "Welcome to m2ee, the Mendix Runtime helper tools."
        print
        print "Available commands:"
        print " unpack - unpack an uploaded Mendix Deployment Archive from data/model-upload"
        print " start - try starting the application using the unpacked deployment files"
        print " stop - stop the application"
        print " restart - restart the application"
        print " status - display Mendix Runtime status (is the application running?)"
        print " create_admin_user - create first user when starting with an empty database"
        print " update_admin_user - reset the password of an application user"
        print " who, w - show currently logged in users"
        print " log - follow live logging from the application"
        print " loglevel - view and configure loglevels"
        print " about - show Mendix Runtime version information"
        print " show_current_runtime_requests - show action stack of currently handled requests"
        print " interrupt_request - cancel a running runtime request"
        print " show_license_information - show details about current mendix license key"
        print " exit, quit, <ctrl>-d - exit m2ee"
        print

        if self.m2ee.config.is_using_postgresql():
            print "When using PostgreSQL, you can also use:"
            print " psql - start the postgresql shell"
            print " dumpdb - create a database dump into the data/database folder"
            print " emptydb - drop all tables and sequences from the database"
            print " restoredb - restore a database dump from the data/database folder"
            print

        if args == 'expert':
            print "Advanced commands:"
            print " statistics - show all application statistics that can be used for monitoring"
            print " show_all_thread_stack_traces - show all low-level JVM threads with stack trace"
            print " profiler - start the profiler (experimental) "
            print " check_health - manually execute health check"
            print
            print "Extra commands you probably don't need:"
            print " debug - dive into a local python debug session inside this program"
            print " dump_config - dump the yaml configuration information"
            print " reload - reload configuration from yaml files (this is done automatically)"
            print " munin_config - configure option for the built-in munin plugin"
            print " munin_values - show monitoring output gathered by the built-in munin plugin"
            print " nagios - execute the built-in nagios plugin (will exit m2ee)"
            print " activate_license - DANGEROUS - replace/set license key"
            print

        print "Hint: use tab autocompletion for commands!"

        if args != 'expert':
            print "Use help expert to show expert and debugging commands" 

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

    yaml_files = []
    if options.yamlfiles:
        yaml_files = options.yamlfiles
    else:
        yaml_files = find_yaml_files()

    m2ee = CLI(yaml_files)
    atexit.register(m2ee._cleanup_logging)
    if args:
        m2ee.onecmd(' '.join(args))
    else:
        m2ee.cmdloop()

