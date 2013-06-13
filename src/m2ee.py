#!/usr/bin/python
#
# Copyright (c) 2009-2013, Mendix bv
# All Rights Reserved.
#
# http://www.mendix.com/
#

import cmd
import subprocess
import atexit
import os
import pwd
import sys
import getpass
import signal
import string
import random
import pprint
import yaml
import datetime

from m2ee import pgutil, M2EE, M2EEProfiler, logger, client_errno
import m2ee


class CLI(cmd.Cmd):

    def __init__(self, yaml_files=None):
        logger.debug('Using m2ee-tools version %s' % m2ee.__version__)
        cmd.Cmd.__init__(self)
        if yaml_files:
            self.m2ee = M2EE(yamlfiles=yaml_files, load_default_files=False)
        else:
            self.m2ee = M2EE()
        self.do_status(None)
        username = pwd.getpwuid(os.getuid())[0]
        self._default_prompt = "m2ee(%s): " % username
        self.prompt = self._default_prompt
        logger.info("Application Name: %s" % self.m2ee.config.get_app_name())

    def do_restart(self, args):
        if self._stop():
            self._start()

    def do_stop(self, args):
        self._stop()

    def do_start(self, args):
        self._start()

    def _stop(self):
        (pid_alive, m2ee_alive) = self.m2ee.check_alive()
        if not pid_alive and not m2ee_alive:
            logger.info("Nothing to stop, the application is not running.")
            return True

        logger.debug("Trying to stop the application.")
        stopped = False

        stopped = self.m2ee.stop()
        if stopped:
            return True

        answer = None
        while not answer in ('y', 'n'):
            answer = raw_input("Do you want to try to signal the JVM "
                               "process to stop immediately? (y)es, (n)o? ")
            if answer == 'y':
                stopped = self.m2ee.terminate()
                if stopped:
                    return True
            elif answer == 'n':
                logger.info("Doing nothing, use stop again to check if the "
                            "process finally disappeared...")
                return False
            else:
                print("Unknown option %s" % answer)

        answer = None
        while not answer in ('y', 'n'):
            answer = raw_input("Do you want to kill the JVM process? (y)es,"
                               "(n)o? ")
            if answer == 'y':
                stopped = self.m2ee.kill()
                if stopped:
                    return True
            elif answer == 'n':
                logger.info("Doing nothing, use stop again to check if the "
                            "process finally disappeared...")
                return False
            else:
                print("Unknown option %s" % answer)

        return False

    def _start(self):
        """
        This function deals with the start-up sequence of the Mendix Runtime.
        Starting the Mendix Runtime can fail in both a temporary or permanent
        way. See the client_errno for possible error codes.
        """
        if not self.m2ee.start_appcontainer():
            return

        if not self.m2ee.send_runtime_config():
            self._stop()
            return

        abort = False
        fully_started = False
        params = {}
        while not (fully_started or abort):
            startresponse = self.m2ee.start_runtime(params)
            result = startresponse.get_result()
            if result == client_errno.SUCCESS:
                fully_started = True
            else:
                startresponse.display_error()
                if result == client_errno.start_NO_EXISTING_DB:
                    answer = self._ask_user_whether_to_create_db()
                    if answer == 'a':
                        abort = True
                    elif (self.m2ee.config.get_runtime_version() // 2.5 and
                          answer == 'c'):
                        params["autocreatedb"] = True
                elif result == client_errno.start_INVALID_DB_STRUCTURE:
                    answer = self._handle_ddl_commands()
                    if answer == 'a':
                        abort = True
                elif result == client_errno.start_MISSING_MF_CONSTANT:
                    logger.error("You'll have to add the constant definitions "
                                 "to the configuration in the "
                                 "MicroflowConstants section.")
                    abort = True
                elif result == client_errno.start_ADMIN_1:
                    answer = self._handle_admin_1(
                        startresponse.get_feedback()['users'])
                    if answer == 'a':
                        abort = True
                else:
                    abort = True

        if abort:
            self._stop()

    def _ask_user_whether_to_create_db(self):
        answer = None
        while not answer in ('c', 'r', 'a'):
            if self.m2ee.config.get_dtap_mode()[0] in 'DT':
                answer = raw_input("Do you want to (c)reate, (r)etry, or "
                                   "(a)bort: ")
            else:
                answer = raw_input("Do you want to (r)etry, or (a)bort: ")
            if answer in ('a', 'r'):
                pass
            elif answer == 'c':
                if not self.m2ee.config.get_dtap_mode()[0] in ('D', 'T'):
                    logger.error("Automatic Database creation is disabled in "
                                 "Acceptance and Production mode!")
                    answer = None
                elif self.m2ee.config.get_runtime_version() >= 3:
                    # If in Development/Test, call execute_ddl_commands,
                    # because since 3.0, this tries to create a database and
                    # immediately executes initial ddl commands
                    m2eeresponse = self.m2ee.client.execute_ddl_commands()
                    m2eeresponse.display_error()
            else:
                print("Unknown option %s" % answer)
        return answer

    def _handle_ddl_commands(self):
        feedback = self.m2ee.client.get_ddl_commands(
            {"verbose": True}).get_feedback()
        answer = None
        while not answer in ('v', 's', 'e', 'a'):
            answer = raw_input("Do you want to (v)iew queries, (s)ave them to "
                               "a file, (e)xecute and save them, or (a)bort: ")
            if answer == 'a':
                pass
            elif answer == 'v':
                print('\n'.join(feedback['ddl_commands']))
                answer = None
            elif answer in ('e', 's'):
                ddl_commands = feedback['ddl_commands']
                self.m2ee.save_ddl_commands(ddl_commands)
                if answer == 'e':
                    m2eeresponse = self.m2ee.client.execute_ddl_commands()
                    m2eeresponse.display_error()
            else:
                print("Unknown option %s" % answer)
        return answer

    def _handle_admin_1(self, users):
        answer = None
        while not answer in ('c', 'a'):
            answer = raw_input("Do you want to (c)hange passwords or "
                               "(a)bort: ")
            if answer == 'a':
                pass
            elif answer == 'c':
                for username in users:
                    changed = False
                    while not changed:
                        newpw1 = getpass.getpass("Type new password for user "
                                                 "%s: " % username)
                        newpw2 = getpass.getpass("Type new password for user "
                                                 " %s again: " % username)
                        if newpw1 != newpw2:
                            print("The passwords are not equal!")
                        else:
                            m2eeresponse = self.m2ee.client.update_admin_user(
                                {"username": username, "password": newpw1})
                            m2eeresponse.display_error()
                            if not m2eeresponse.has_error():
                                changed = True
            else:
                print("Unknown option %s" % answer)
        return answer

    def do_create_admin_user(self, args=None):
        (pid_alive, m2ee_alive) = self.m2ee.check_alive()
        if not m2ee_alive:
            logger.warn("The application process needs to be running to "
                        "create a user object in the application.")
            return
        print("This option will create an administrative user account, using "
              "the preset username and user role settings.")
        newpw1 = getpass.getpass("Type new password for this user: ")
        newpw2 = getpass.getpass("Type new password for this user again: ")
        if newpw1 != newpw2:
            print("The passwords are not equal!")
        else:
            m2eeresponse = self.m2ee.client.create_admin_user(
                {"password": newpw1})
            m2eeresponse.display_error()

    def do_update_admin_user(self, args=None):
        (pid_alive, m2ee_alive) = self.m2ee.check_alive()
        if not m2ee_alive:
            logger.warn("The application process needs to be running to "
                        "change user objects in the application.")
            return
        print("Using this function you can reset the password of an "
              "administrative user account.")
        username = raw_input("User name: ")
        newpw1 = getpass.getpass("Type new password for user %s: " % username)
        newpw2 = getpass.getpass("Type new password for user %s again: " %
                                 username)
        if newpw1 != newpw2:
            print("The passwords are not equal!")
        else:
            m2eeresponse = self.m2ee.client.update_admin_user(
                {"username": username, "password": newpw1})
            m2eeresponse.display_error()

    def do_debug(self, args):
        answer = raw_input("This command will throw you into a local python "
                           "debug session inside the M2EE object! Continue "
                           "(y/N)?")
        if answer == 'y':
            import code
            code.interact(local=locals())

    def do_status(self, args):
        if self._report_not_running():
            return
        feedback = self.m2ee.client.runtime_status().get_feedback()
        logger.info("The application process is running, the MxRuntime has "
                    "status: %s" % feedback['status'])

        critlist = self.m2ee.client.get_critical_log_messages()
        if len(critlist) > 0:
            logger.error("%d critical error(s) were logged. Use show_critical"
                         "_log_messages to view them." % len(critlist))

        max_show_users = 10
        total_users = self._who(max_show_users)
        if total_users > max_show_users:
            logger.info("Only showing %s logged in users. Use who to see a "
                        "complete list." % max_show_users)

    def do_show_critical_log_messages(self, args):
        if self._report_not_running():
            return

        critlist = self.m2ee.client.get_critical_log_messages()
        if len(critlist) == 0:
            logger.info("No messages were logged to a critical loglevel since "
                        "starting the application.")
            return
        print("\n".join(critlist))

    def do_check_health(self, args):
        if self._report_not_implemented('2.5.4') or self._report_not_running():
            return
        health_response = self.m2ee.client.check_health()
        if not health_response.has_error():
            feedback = health_response.get_feedback()
            if feedback['health'] == 'healthy':
                logger.info("Health check microflow says the application is "
                            "healthy.")
            elif feedback['health'] == 'sick':
                logger.warning("Health check microflow says the application "
                               "is sick: %s" % feedback['diagnosis'])
            elif feedback['health'] == 'unknown':
                logger.info("Health check microflow is not configured, no "
                            "health information available.")
            else:
                logger.error("Unexpected health check status: %s" %
                             feedback['health'])
        else:
            runtime_version = self.m2ee.config.get_runtime_version()
            if (health_response.get_result() == 3
                    and runtime_version // ('2.5.4', '2.5.5')):
                # Because of an incomplete implementation, in Mendix 2.5.4 or
                # 2.5.5 this means that the runtime is health-check
                # capable, but no health check microflow is defined.
                logger.info("Health check microflow is probably not "
                            "configured, no health information available.")
            else:
                health_response.display_error()

    def do_statistics(self, args):
        if self._report_not_running():
            return
        stats = self.m2ee.client.runtime_statistics().get_feedback()
        stats.update(self.m2ee.client.server_statistics().get_feedback())
        pprint.pprint(stats)

    def do_munin_config(self, args):
        m2ee.munin.print_all(
            self.m2ee.client,
            self.m2ee.config,
            self.m2ee.config.get_munin_options(),
            args,
            print_config=True
        )

    def do_munin_values(self, args):
        m2ee.munin.print_all(
            self.m2ee.client,
            self.m2ee.config,
            self.m2ee.config.get_munin_options(),
            args
        )

    def do_nagios(self, args):
        logger.info("The nagios plugin will exit m2ee after running, this is "
                    "by design, don't report it as bug.")
        # TODO: implement as separate program after libraryfying m2ee
        sys.exit(m2ee.nagios.check(self.m2ee.runner, self.m2ee.client))

    def do_about(self, args):
        print('Using m2ee-tools version %s' % m2ee.__version__)
        if self._report_not_running():
            return
        feedback = self.m2ee.client.about().get_feedback()
        print("Using %s version %s" % (feedback['name'], feedback['version']))
        print(feedback['copyright'])
        if self.m2ee.config.get_runtime_version() // 2.5:
            if 'company' in feedback:
                print('Project company name is %s' % feedback['company'])
            if 'partner' in feedback:
                print('Project partner name is %s' % feedback['partner'])
        if self.m2ee.config.get_runtime_version() >= 4.4:
            if 'model_version' in feedback:
                print('Model version: %s' % feedback['model_version'])

    def do_show_license_information(self, args):
        if self._report_not_implemented(3) or self._report_not_running():
            return
        m2eeresp = self.m2ee.client.get_license_information()
        m2eeresp.display_error()
        if not m2eeresp.has_error():
            feedback = m2eeresp.get_feedback()
            if 'license' in feedback:
                logger.debug(yaml.safe_dump(feedback['license'],
                             allow_unicode=True))
                import copy
                licensecopy = copy.deepcopy(feedback['license'])
                self._print_license(licensecopy)
            elif 'license_id' in feedback:
                print("Unlicensed environment.")
                print("Server ID: %s" % feedback['license_id'])
            else:
                print("Unlicensed environment.")

    def _print_license(self, licensecopy):
        print("Server ID: %s" % licensecopy.pop('LicenseID', 'Unknown'))
        print("License Type: %s" % licensecopy.pop('LicenseType', 'Unknown'))
        if 'ExpirationDate' in licensecopy:
            print("Expiration Date: %s" %
                  datetime.datetime.fromtimestamp(
                  licensecopy.pop('ExpirationDate') / 1000)
                  .strftime("%a, %d %b %Y %H:%M:%S %z")
                  .rstrip())
        print("Runtime Mode: %s" % licensecopy.pop('RuntimeMode', 'Unknown'))
        print("Company: %s" % licensecopy.pop('Company', 'Unknown'))

        limitations = licensecopy.pop('UserLimitations', None)
        separate_anonymous = licensecopy.pop('SeparateAnonymousUsers', True)
        if limitations is not None:
            print("License Limitations:")
            for limitation in limitations:
                self._print_license_limitation(limitation, separate_anonymous)

        if len(licensecopy) > 1:
            print(yaml.safe_dump(licensecopy, allow_unicode=True))

    def _print_license_limitation(self, limitation, separate_anonymous):
        if limitation['LimitationType'] == 'Named':
            if limitation['AmountType'] == 'Unlimited':
                print("- Unlimited named %suser accounts allowed." %
                      ('' if separate_anonymous else "and anonymous "))
            else:
                print(" - %s named user account%s allowed" %
                      (limitation['NumberOfAllowedUsers'],
                       's' if limitation['NumberOfAllowedUsers'] != 1 else ''))
        elif limitation['LimitationType'] == 'Concurrent':
            if limitation['AmountType'] == 'Unlimited':
                print("- Unlimited concurrent named %suser sessions allowed."
                      % ("" if separate_anonymous else "and anonymous "))
            else:
                print("- %s concurrent named %suser session%s allowed." %
                      (limitation['NumberOfAllowedUsers'],
                      '' if separate_anonymous else "and anonymous ",
                      ('s' if limitation['NumberOfAllowedUsers'] != 1
                      else '')))
        elif (limitation['LimitationType'] == 'ConcurrentAnonymous' and
              separate_anonymous):
            if limitation['AmountType'] == 'Unlimited':
                print("- Unlimited concurrent anonymous user sessions "
                      "allowed.")
            else:
                print("- %s concurrent anonymous session%s allowed." %
                      (limitation['NumberOfAllowedUsers'],
                      ('s' if limitation['NumberOfAllowedUsers'] != 1
                      else '')))

    def do_activate_license(self, args):
        if self._report_not_implemented(3) or self._report_not_running():
            return
        print("The command activate_license will set the license key used in "
              "this application.")
        if self.m2ee.config.get_runtime_version() < 4.1:
            print("Mendix Runtime versions before 4.1 do not check the "
                  "submitted license key for validity, so incorrect input "
                  "will un-license your Mendix application without warning! "
                  "After setting the license, use show_license_information "
                  "to check the active license. Also... after setting the "
                  "license in versions before Mendix 4.1 you will need to "
                  "restart the application again to be sure it is fully "
                  "activated.")
            answer = raw_input("Do you want to continue anyway? (type YES if "
                               "you want to): ")
            if answer != 'YES':
                print("Aborting.")
                return
        if not args:
            license_key = raw_input("Paste your license key (a long text "
                                    "string without newlines) or empty input "
                                    "to abort: ")
        else:
            license_key = args
        if not license_key:
            print("Aborting.")
            return
        m2eeresp = self.m2ee.client.set_license({'license_key': license_key})
        m2eeresp.display_error()

    def do_enable_debugger(self, args):
        if self._report_not_implemented(4.3) or self._report_not_running():
            return

        if not args:
            debugger_password = raw_input(
                "Please enter the password to be used for remote debugger "
                "access from the modeler, or leave blank to auto-generate "
                "a password: ")
            if not debugger_password:
                debugger_password = ''.join(
                    random.choice(string.letters + string.digits)
                    for x in range(random.randint(20, 30)))
        else:
            debugger_password = args
        m2eeresp = self.m2ee.client.enable_debugger(
            {'password': debugger_password})
        m2eeresp.display_error()
        if not m2eeresp.has_error():
            logger.info("The remote debugger is now enabled, the password to "
                        "use is %s" % debugger_password)
            logger.info("You can use the remote debugger option in the Mendix "
                        "Business Modeler to connect to the /debugger/ sub "
                        "url on your application (e.g. "
                        "https://app.example.com/debugger/). ")

    def do_disable_debugger(self, args):
        if self._report_not_implemented(4.3) or self._report_not_running():
            return

        m2eeresp = self.m2ee.client.disable_debugger()
        if not m2eeresp.has_error():
            logger.info("The remote debugger is now disabled.")
        else:
            m2eeresp.display_error()

    def do_show_debugger_status(self, args):
        if self._report_not_implemented(4.3) or self._report_not_running():
            return

        m2eeresp = self.m2ee.client.get_debugger_status()
        if not m2eeresp.has_error():
            enabled = m2eeresp.get_feedback()['enabled']
            connected = m2eeresp.get_feedback()['client_connected']
            paused = m2eeresp.get_feedback()['number_of_paused_microflows']

            logger.info("The remote debugger is currently %s." %
                        ("enabled" if enabled else "disabled"))
            if connected:
                logger.info("A debugger session is connected.")
            elif enabled:
                logger.info("There is no connected debugger session.")
            if enabled and paused == 0:
                logger.info("There are no paused microflows.")
            elif paused == 1:
                logger.info("There is 1 paused microflow.")
            elif paused > 1:
                logger.info("There are %s paused microflows." % paused)
        else:
            m2eeresp.display_error()

    def do_who(self, args):
        if self._report_not_running():
            return
        if args:
            try:
                limitint = int(args)
                self._who(limitint)
            except ValueError:
                logger.warn("Could not parse argument to an integer. Use a "
                            "number as argument to limit the amount of logged "
                            "in users shown.")
        else:
            self._who()

    def do_w(self, args):
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
        pgutil.psql(self.m2ee.config)

    def do_dumpdb(self, args):
        if not self.m2ee.config.is_using_postgresql():
            logger.error("Only PostgreSQL databases are supported right now.")
            return
        pgutil.dumpdb(self.m2ee.config)

    def do_restoredb(self, args):
        if not self.m2ee.config.is_using_postgresql():
            logger.error("Only PostgreSQL databases are supported right now.")
            return
        if not args:
            logger.error("restoredb needs the name of a dump file in %s as arg"
                         "ument" % self.m2ee.config.get_database_dump_path())
            return
        (pid_alive, m2ee_alive) = self.m2ee.check_alive()
        if pid_alive or m2ee_alive:
            logger.warn("The application is still running, refusing to "
                        "restore the database right now.")
            return
        database_name = self.m2ee.config.get_pg_environment()['PGDATABASE']
        answer = raw_input("This command will restore this dump into database "
                           "%s. Continue? (y)es, (N)o? " % database_name)
        if answer != 'y':
            logger.info("Aborting!")
            return
        pgutil.restoredb(self.m2ee.config, args)

    def complete_restoredb(self, text, line, begidx, endidx):
        if not self.m2ee.config.is_using_postgresql():
            return []
        database_dump_path = self.m2ee.config.get_database_dump_path()
        return [f for f in os.listdir(database_dump_path)
                if os.path.isfile(os.path.join(database_dump_path, f)) and
                f.startswith(text) and
                f.endswith(".backup")]

    def do_emptydb(self, args):
        if not self.m2ee.config.is_using_postgresql():
            logger.error("Only PostgreSQL databases are supported right now.")
            return
        (pid_alive, m2ee_alive) = self.m2ee.check_alive()
        if pid_alive or m2ee_alive:
            logger.warn("The application process is still running, refusing "
                        "to empty the database right now.")
            return
        logger.info("This command will drop all tables and sequences in "
                    "database %s." %
                    self.m2ee.config.get_pg_environment()['PGDATABASE'])
        answer = raw_input("Continue? (y)es, (N)o? ")
        if answer != 'y':
            print("Aborting!")
            return
        pgutil.emptydb(self.m2ee.config)

    def do_unpack(self, args):
        if not args:
            logger.error("unpack needs the name of a model upload zipfile in "
                         "%s as argument" %
                         self.m2ee.config.get_model_upload_path())
            return
        (pid_alive, m2ee_alive) = self.m2ee.check_alive()
        if pid_alive or m2ee_alive:
            logger.error("The application process is still running, refusing "
                         "to unpack a new application model right now.")
            return
        logger.info("This command will replace the contents of the model/ and "
                    "web/ locations, using the files extracted from the "
                    "archive")
        answer = raw_input("Continue? (y)es, (N)o? ")
        if answer != 'y':
            logger.info("Aborting!")
            return
        self.m2ee.unpack(args)

    def complete_unpack(self, text, line, begidx, endidx):
        # these complete functions seem to eat exceptions, which is very bad
        # behaviour if anything here throws an excaption, you just won't get
        # completion, without knowing why
        model_upload_path = self.m2ee.config.get_model_upload_path()
        logger.trace("complete_unpack: Looking for %s in %s" %
                     (text, model_upload_path))
        return [f for f in os.listdir(model_upload_path)
                if os.path.isfile(os.path.join(model_upload_path, f))
                and f.startswith(text)
                and (f.endswith(".zip") or f.endswith(".mda"))]

    def do_log(self, args):
        if self._cleanup_logging():
            return
        logfile = self.m2ee.config.get_logfile()
        if not logfile:
            logger.warn("logfile location is not specified")
            return
        print("This command will start printing log information from the "
              "application right in the middle of all of the other output on "
              "your screen. This can be confusing, especially when you're "
              "typing something and everything gets messed up by the logging. "
              "Issuing the log command again will turn off logging output.")
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
            print("To adjust loglevels, use: loglevel <subscribername> "
                  "<lognodename> <level>")
            print("Available levels: NONE, CRITICAL, ERROR, WARNING, INFO, "
                  "DEBUG, TRACE")

    def _get_log_levels(self):
        log_levels = self.m2ee.get_log_levels()
        print("Current loglevels:")
        log_subscribers = []
        for (subscriber_name, node_names) in log_levels.iteritems():
            for (node_name, subscriber_level) in node_names.iteritems():
                log_subscribers.append("%s %s %s" %
                                       (subscriber_name,
                                        node_name,
                                        subscriber_level))
        log_subscribers.sort()
        print("\n".join(log_subscribers))

    def _set_log_level(self, subscriber, node, level):
        level = level.upper()
        response = self.m2ee.set_log_level(subscriber, node, level)
        if response.has_error():
            response.display_error()
            print("Remember, all parameters are case sensitive")
        else:
            logger.info("Loglevel for %s set to %s" % (node, level))

    def _report_not_implemented(self, avail_since):
        runtime_version = self.m2ee.config.get_runtime_version()
        if runtime_version is None:
            return False  # DUNNO
        if not runtime_version >= avail_since:
            logger.error("This action is not available in the Mendix Runtime "
                         "version you are currently using.")
            if isinstance(avail_since, tuple):
                if len(avail_since) > 2:
                    implemented_in = (
                        '%s, %s and %s' %
                        (', '.join(map(str, avail_since[:-2])),
                        avail_since[-2], avail_since[-1]))
                else:
                    implemented_in = '%s and %s' % avail_since
            else:
                implemented_in = avail_since
            logger.error("It was implemented in Mendix %s" % implemented_in)
            return True
        return False

    def _report_not_running(self):
        """
        To be used by actions to see whether m2ee is available for executing
        requests. Also prints a line when the application is not running.

        if self._report_not_running():
            return
        do_things_that_communicate_using_m2ee_client()

        returns True when m2ee is not available for requests, else False
        """
        (pid_alive, m2ee_alive) = self.m2ee.check_alive()
        if not pid_alive and not m2ee_alive:
            logger.info("The application process is not running.")
            return True
        # if pid is alive, but m2ee does not respond, errors are already
        # printed by check_alive
        if pid_alive and not m2ee_alive:
            return True
        return False

    def do_show_current_runtime_requests(self, args):
        if (self._report_not_implemented(('2.5.8', 3.1))
                or self._report_not_running()):
            return
        m2eeresp = self.m2ee.client.get_current_runtime_requests()
        m2eeresp.display_error()
        if not m2eeresp.has_error():
            feedback = m2eeresp.get_feedback()
            if not feedback:
                logger.info("There are no currently running runtime requests.")
            else:
                print("Current running Runtime Requests:")
                print(yaml.safe_dump(feedback))

    def do_show_all_thread_stack_traces(self, args):
        if self._report_not_implemented(3.2) or self._report_not_running():
            return
        m2eeresp = self.m2ee.client.get_all_thread_stack_traces()
        m2eeresp.display_error()
        if not m2eeresp.has_error():
            feedback = m2eeresp.get_feedback()
            print("Current JVM Thread Stacktraces:")
            print(pprint.pprint(feedback))

    def do_interrupt_request(self, args):
        if (self._report_not_implemented(('2.5.8', 3.1))
                or self._report_not_running()):
            return
        if args == "":
            logger.error("This function needs a request id as parameter")
            logger.error("Use show_current_runtime_requests to view currently "
                         "running requests")
            return
        m2eeresp = self.m2ee.client.interrupt_request({"request_id": args})
        m2eeresp.display_error()
        if not m2eeresp.has_error():
            feedback = m2eeresp.get_feedback()
            if feedback["result"] is False:
                logger.error("A request with ID %s was not found" % args)
            else:
                logger.info("An attempt to cancel the running action was "
                            "made.")

    def do_exit(self, args):
        return -1

    def do_quit(self, args):
        return -1

    def do_EOF(self, args):
        print
        return -1

    def do_profiler(self, args):
        print("The profiler module in this program is experimental "
              "functionality and should not be used in production "
              "environments. Incorrect use of the profiler can cause out of "
              "memory errors on applications that handle a lot of requests.")
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
        if limitint is not None:
            limit = {"limit": limitint}
        m2eeresp = self.m2ee.client.get_logged_in_user_names(limit)
        m2eeresp.display_error()
        if not m2eeresp.has_error():
            feedback = m2eeresp.get_feedback()
            logger.info("Logged in users: (%s) %s" %
                        (feedback['count'], feedback['users']))
            return feedback['count']
        return 0

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
        print("""Welcome to m2ee, the Mendix Runtime helper tools.

Available commands:
 unpack - unpack an uploaded Mendix Deployment Archive from data/model-upload
 start - try starting the application using the unpacked deployment files
 stop - stop the application
 restart - restart the application
 status - display Mendix Runtime status (is the application running?
 create_admin_user - create first user when starting with an empty database
 update_admin_user - reset the password of an application user
 who, w - show currently logged in users
 log - follow live logging from the application
 loglevel - view and configure loglevels
 about - show Mendix Runtime version information
 show_current_runtime_requests - show action stack of current running requests
 interrupt_request - cancel a running runtime request
 show_license_information - show details about current mendix license key
 exit, quit, <ctrl>-d - exit m2ee
""")

        if self.m2ee.config.is_using_postgresql():
            print("""When using PostgreSQL, you can also use:
 psql - start the postgresql shell
 dumpdb - create a database dump into the data/database folder
 emptydb - drop all tables and sequences from the database
 restoredb - restore a database dump from the data/database folder
""")

        if args == 'expert':
            print("""Advanced commands:
 statistics - show all application statistics that can be used for monitoring
 show_all_thread_stack_traces - show all low-level JVM threads with stack trace
 profiler - start the profiler (experimental)
 check_health - manually execute health check
 enable_debugger - enable remote debugger API
 disable_debugger - disable remote debugger API
 show_debugger_status - show whether debugger is enabled or not

Extra commands you probably don't need:
 debug - dive into a local python debug session inside this program
 dump_config - dump the yaml configuration information
 reload - reload configuration from yaml files (this is done automatically)
 munin_config - configure option for the built-in munin plugin
 munin_values - show monitoring output gathered by the built-in munin plugin
 nagios - execute the built-in nagios plugin (will exit m2ee)
 activate_license - DANGEROUS - replace/set license key
""")

        print("Hint: use tab autocompletion for commands!")

        if args != 'expert':
            print("Use help expert to show expert and debugging commands")

if __name__ == '__main__':
    from optparse import OptionParser
    parser = OptionParser()
    parser.add_option(
        "-c",
        action="append",
        type="string",
        dest="yaml_files"
    )
    parser.add_option(
        "-v",
        "--verbose",
        action="count",
        dest="verbose",
        help="increase verbosity of output (-vv to be even more verbose)"
    )
    parser.add_option(
        "-q",
        "--quiet",
        action="count",
        dest="quiet",
        help="decrease verbosity of output (-qq to be even more quiet)"
    )
    (options, args) = parser.parse_args()

    # how verbose should we be? see
    # http://docs.python.org/release/2.7/library/logging.html#logging-levels
    verbosity = 0
    if options.quiet:
        verbosity = verbosity + options.quiet
    if options.verbose:
        verbosity = verbosity - options.verbose
    verbosity = verbosity * 10 + 20
    if verbosity > 50:
        verbosity = 100
    if verbosity < 5:
        verbosity = 5
    logger.setLevel(verbosity)

    cli = CLI(yaml_files=options.yaml_files)
    atexit.register(cli._cleanup_logging)
    if args:
        cli.onecmd(' '.join(args))
    else:
        try:
            cli.cmdloop()
        except KeyboardInterrupt:
            print("^C")
            sys.exit(130)  # 128 + SIGINT
