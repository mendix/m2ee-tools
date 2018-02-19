#!/usr/bin/python
#
# Copyright (C) 2009 Mendix. All rights reserved.
#

from __future__ import print_function
import argparse
import atexit
import cmd
import datetime
import getpass
import logging
import os
import pwd
import random
import shlex
import signal
import string
import subprocess
import sys
import yaml

from m2ee import pgutil, M2EE, client_errno
import m2ee

logger = logging

if not sys.stdout.isatty():
    import codecs
    import locale
    sys.stdout = codecs.getwriter(locale.getpreferredencoding())(sys.stdout)


class CLI(cmd.Cmd, object):

    def __init__(self, yaml_files=None, yolo_mode=False):
        logger.debug('Using m2ee-tools version %s' % m2ee.__version__)
        cmd.Cmd.__init__(self)
        self.m2ee = M2EE(yaml_files=yaml_files)
        self.yolo_mode = yolo_mode
        self.prompt_username = pwd.getpwuid(os.getuid())[0]
        self._default_prompt = "m2ee(%s): " % self.prompt_username
        self.prompt = self._default_prompt
        self.nodetach = False

    def do_restart(self, args):
        if self._stop():
            self._start()

    def do_stop(self, args):
        self._stop()

    def do_start(self, args):
        self._start()

    def _stop(self):
        logger.debug("Trying to stop the application.")
        stopped = self.m2ee.stop()
        if stopped:
            return True

        answer = None
        while answer not in ('y', 'n'):
            answer = ('y' if self.yolo_mode
                      else raw_input("Do you want to try to signal the JVM "
                                     "process to stop immediately? (y)es, (n)o? "))
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
        while answer not in ('y', 'n'):
            answer = ('y' if self.yolo_mode
                      else raw_input("Do you want to kill the JVM process? "
                                     "(y)es, (n)o? "))
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

        if not self.m2ee.config.get_runtime_path():
            logger.error("It appears that the Mendix Runtime version which "
                         "has to be used for your application is not present "
                         "yet.")
            logger.info("You can try downloading it using the "
                        "download_runtime command.")
            return

        self.m2ee.start_appcontainer(detach=not self.nodetach)

        try:
            self.m2ee.send_runtime_config()
        except m2ee.client.M2EEAdminException as e:
            logger.error("Sending configuration failed: %s" % e.cause)
            logger.error("You'll have to fix the configuration and run start again...")
            self._stop()
            return

        abort = False
        fully_started = False
        params = {}
        while not (fully_started or abort):
            try:
                self.m2ee.start_runtime(params)
                fully_started = True
            except m2ee.client.M2EEAdminException as e:
                logger.error(e)
                if e.result == client_errno.start_NO_EXISTING_DB:
                    answer = self._ask_user_whether_to_create_db()
                    if answer == 'a':
                        abort = True
                elif e.result == client_errno.start_INVALID_DB_STRUCTURE:
                    answer = self._handle_ddl_commands()
                    if answer == 'a':
                        abort = True
                elif e.result == client_errno.start_MISSING_MF_CONSTANT:
                    logger.error("You'll have to add the constant definitions "
                                 "to the configuration in the "
                                 "MicroflowConstants section.")
                    abort = True
                elif e.result == client_errno.start_ADMIN_1:
                    users = e.feedback['users']
                    if self.yolo_mode:
                        self._handle_admin_1_yolo(users)
                    else:
                        answer = self._handle_admin_1(users)
                        if answer == 'a':
                            abort = True
                else:
                    abort = True

        if abort:
            self._stop()

    def _ask_user_whether_to_create_db(self):
        answer = None
        while answer not in ('c', 'r', 'a'):
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
                else:
                    # If in Development/Test, call execute_ddl_commands,
                    # this tries to create a database and
                    # immediately executes initial ddl commands
                    self.m2ee.client.execute_ddl_commands()
            else:
                print("Unknown option %s" % answer)
        return answer

    def _handle_ddl_commands(self):
        feedback = self.m2ee.client.get_ddl_commands({"verbose": True})
        answer = None
        while answer not in ('v', 's', 'e', 'a'):
            answer = ('e' if self.yolo_mode
                      else raw_input("Do you want to (v)iew queries, (s)ave them to "
                                     "a file, (e)xecute and save them, or (a)bort: "))
            if answer == 'a':
                pass
            elif answer == 'v':
                print('\n'.join(feedback['ddl_commands']))
                answer = None
            elif answer in ('e', 's'):
                ddl_commands = feedback['ddl_commands']
                self.m2ee.save_ddl_commands(ddl_commands)
                if answer == 'e':
                    self.m2ee.client.execute_ddl_commands()
            else:
                print("Unknown option %s" % answer)
        return answer

    def _handle_admin_1(self, users):
        answer = None
        while answer not in ('c', 'a'):
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
                            try:
                                self.m2ee.client.update_admin_user(
                                    {"username": username, "password": newpw1})
                                changed = True
                            except m2ee.client.M2EEAdminException as e:
                                logger.error(e)
            else:
                print("Unknown option %s" % answer)
        return answer

    def _handle_admin_1_yolo(self, users):
        for username in users:
            newpasswd = self._generate_password()
            logger.info("Changing password for user %s to %s" %
                        (username, newpasswd))
            self.m2ee.client.update_admin_user({
                "username": username,
                "password": newpasswd,
            })

    def _generate_password(self):
        newpasswd_list = []
        for choosefrom in [
            string.ascii_lowercase,
            string.ascii_uppercase,
            string.digits,
            string.punctuation,
        ]:
            newpasswd_list.extend([random.choice(choosefrom)
                                   for _ in range(random.randint(10, 20))])
        random.shuffle(newpasswd_list)
        return ''.join(newpasswd_list)

    def do_create_admin_user(self, args=None):
        if not self.m2ee.client.ping():
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
            self.m2ee.client.create_admin_user({"password": newpw1})

    def do_update_admin_user(self, args=None):
        if not self.m2ee.client.ping():
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
            self.m2ee.client.update_admin_user({"username": username, "password": newpw1})

    def do_debug(self, args):
        answer = raw_input("This command will throw you into a local python "
                           "debug session inside the M2EE object! Continue "
                           "(y/N)?")
        if answer == 'y':
            import code
            code.interact(local=locals())

    def do_status(self, args):
        feedback = self.m2ee.client.runtime_status()
        status = feedback['status']
        logger.info("The application process is running, the MxRuntime has status: %s" % status)

        if status != 'running':
            return

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
        errors = self.m2ee.client.get_critical_log_messages()
        if len(errors) == 0:
            logger.info("No messages were logged to a critical loglevel since "
                        "starting the application.")
            return
        for error in errors:
            errorline = []
            if 'message' in error and error['message'] != '':
                errorline.append("- %s" % error['message'])
            if 'cause' in error and error['cause'] != '':
                errorline.append("- Caused by: %s" % error['cause'])
            if len(errorline) == 0:
                errorline.append("- [No message or cause was logged]")
            errorline.insert(
                0,
                datetime.datetime.fromtimestamp(error['timestamp'] / 1000)
                .strftime("%Y-%m-%d %H:%M:%S")
            )
            print(' '.join(errorline))

    def do_check_health(self, args):
        feedback = self.m2ee.client.check_health()
        if feedback['health'] == 'healthy':
            logger.info("Health check microflow says the application is healthy.")
        elif feedback['health'] == 'sick':
            logger.warning("Health check microflow says the application "
                           "is sick: %s" % feedback['diagnosis'])
        elif feedback['health'] == 'unknown':
            logger.info("Health check microflow is not configured, no "
                        "health information available.")
        else:
            logger.error("Unexpected health check status: %s" % feedback['health'])

    def do_statistics(self, args):
        stats = self.m2ee.client.runtime_statistics()
        stats.update(self.m2ee.client.server_statistics())
        print(yaml.safe_dump(stats, default_flow_style=False))

    def do_show_cache_statistics(self, args):
        stats = self.m2ee.client.cache_statistics()
        print(yaml.safe_dump(stats, default_flow_style=False))

    def do_munin_config(self, args):
        m2ee.munin.print_config(
            self.m2ee,
            self.prompt_username,
        )

    def do_munin_values(self, args):
        m2ee.munin.print_values(
            self.m2ee,
            self.prompt_username,
        )

    def do_nagios(self, args):
        logger.info("The nagios plugin will exit m2ee after running, this is "
                    "by design, don't report it as bug.")
        # TODO: implement as separate program after libraryfying m2ee
        sys.exit(m2ee.nagios.check(self.m2ee.runner, self.m2ee.client))

    def do_about(self, args):
        print('Using m2ee-tools version %s' % m2ee.__version__)
        feedback = self.m2ee.client.about()
        print("Using %s version %s" % (feedback['name'], feedback['version']))
        print(feedback['copyright'])
        if self.m2ee.config.get_runtime_version() >= 4.4:
            if 'model_version' in feedback:
                print('Model version: %s' % feedback['model_version'])

    def do_show_license_information(self, args):
        feedback = self.m2ee.client.get_license_information()
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
                      licensecopy.pop('ExpirationDate') / 1000
                  )
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
                      (
                          limitation['NumberOfAllowedUsers'],
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
                      (
                          limitation['NumberOfAllowedUsers'],
                          ('s' if limitation['NumberOfAllowedUsers'] != 1
                           else '')))

    def do_activate_license(self, args):
        self.m2ee.client.require_action("set_license")
        print("The command activate_license will set the license key used in "
              "this application.")
        runtime_version = m2ee.version.MXVersion(self.m2ee.client.about()['version'])
        if runtime_version < 4.1:
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
        self.m2ee.client.set_license({'license_key': license_key})

    def do_enable_debugger(self, args):
        self.m2ee.client.require_action("enable_debugger")
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
        self.m2ee.client.enable_debugger({'password': debugger_password})
        logger.info("The remote debugger is now enabled, the password to "
                    "use is %s" % debugger_password)
        logger.info("You can use the remote debugger option in the Mendix "
                    "Business Modeler to connect to the /debugger/ sub "
                    "url on your application (e.g. "
                    "https://app.example.com/debugger/). ")

    def do_disable_debugger(self, args):
        self.m2ee.client.disable_debugger()
        logger.info("The remote debugger is now disabled.")

    def do_show_debugger_status(self, args):
        feedback = self.m2ee.client.get_debugger_status()
        enabled = feedback['enabled']
        connected = feedback['client_connected']
        paused = feedback['number_of_paused_microflows']

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

    def do_who(self, args):
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

    def do_set_database_password(self, args):
        password = getpass.getpass("Database password: ")
        self.m2ee.config.set_database_password(password)

    def do_psql(self, args):
        if not self.m2ee.config.is_using_postgresql():
            logger.error("Only PostgreSQL databases are supported right now.")
            return
        pgutil.psql(self.m2ee.config)

    def do_dumpdb(self, args):
        if not self.m2ee.config.is_using_postgresql():
            logger.error("Only PostgreSQL databases are supported right now.")
            return
        if len(args) > 0:
            pgutil.dumpdb(self.m2ee.config, args)
        else:
            pgutil.dumpdb(self.m2ee.config)

    def do_restoredb(self, args):
        if not self.m2ee.config.allow_destroy_db():
            logger.error("Refusing to do a destructive database operation "
                         "because the allow_destroy_db configuration option "
                         "is set to false.")
            return
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
        answer = ('y' if self.yolo_mode
                  else raw_input("This command will restore this dump into database "
                                 "%s. Continue? (y)es, (N)o? " % database_name))
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
        if not self.m2ee.config.allow_destroy_db():
            logger.error("Refusing to do a destructive database operation "
                         "because the allow_destroy_db configuration option "
                         "is set to false.")
            return
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
        answer = ('y' if self.yolo_mode
                  else raw_input("Continue? (y)es, (N)o? "))
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
        answer = ('y' if self.yolo_mode
                  else raw_input("Continue? (y)es, (N)o? "))
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

    def do_check_constants(self, args):
        constants_to_use, default_constants, obsolete_constants = self.m2ee.config.get_constants()
        if len(default_constants) > 0:
            logger.info('Missing constant definitions (model defaults will be used):')
            for name in sorted(default_constants.keys()):
                logger.info('- %s' % name)
        else:
            logger.info('All required constant definitions have explicit definitions.')
        if len(obsolete_constants) > 0:
            logger.info('Constants defined but not needed by the application:')
            for name in sorted(obsolete_constants.keys()):
                logger.info('- %s' % name)

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
        answer = ('y' if self.yolo_mode
                  else raw_input("Do you want to start log output (y/N): "))
        if answer == 'y':
            cmd = ("tail", "-F", logfile)
            proc = subprocess.Popen(cmd)
            self.m2ee._logproc = proc
            self.prompt = "LOG %s" % self._default_prompt

    def do_loglevel(self, args):
        try:
            args = shlex.split(args)
        except ValueError as ve:
            logger.error("Input cannot be parsed: %s" % ve.message)
            return
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
        try:
            self.m2ee.set_log_level(subscriber, node, level)
            logger.info("Loglevel for %s set to %s" % (node, level))
        except m2ee.client.M2EEAdminException as e:
            print("Remember, all parameters are case sensitive")
            raise e

    def do_show_current_runtime_requests(self, args):
        feedback = self.m2ee.client.get_current_runtime_requests()
        if len(feedback) == 0:
            logger.info("There are no currently running runtime requests.")
        else:
            print("Current running Runtime Requests:")
            print(yaml.safe_dump(feedback, default_flow_style=False))

    def do_show_all_thread_stack_traces(self, args):
        feedback = self.m2ee.client.get_all_thread_stack_traces()
        print("Current JVM Thread Stacktraces:")
        print(yaml.safe_dump(feedback, default_flow_style=False))

    def do_interrupt_request(self, args):
        if args == "":
            logger.error("This function needs a request id as parameter")
            logger.error("Use show_current_runtime_requests to view currently "
                         "running requests")
            return
        feedback = self.m2ee.client.interrupt_request({"request_id": args})
        if feedback["result"] is False:
            logger.error("A request with ID %s was not found" % args)
        else:
            logger.info("An attempt to cancel the running action was "
                        "made.")

    def do_nodetach(self, args):
        self.nodetach = True
        logger.info("Setting nodetach, application process will not run in the background.")

    def do_exit(self, args):
        return self._exit()

    def do_quit(self, args):
        return self._exit()

    def do_EOF(self, args):
        print("exit")
        return self._exit()

    def _exit(self):
        if self.m2ee.runner.check_attached_proc():
            logger.warning("There is still an attached application process running. "
                           "Stop it first.")
            return None
        return -1

    def do_download_runtime(self, args):
        if args:
            mxversion = m2ee.version.MXVersion(args)
        else:
            mxversion = self.m2ee.config.get_runtime_version()

        if mxversion is None:
            logger.info("You did not specify a Mendix Runtime version to "
                        "download, and no current unpacked application "
                        "model is available to determine the version from. "
                        "Specify a version number or use unpack first.")
            return

        if self.m2ee.config.lookup_in_mxjar_repo(str(mxversion)):
            logger.info("The Mendix Runtime for version %s is already "
                        "installed. If you want to download another Runtime "
                        "version, specify the version number as argument to "
                        "download_runtime." % mxversion)
            return
        self.m2ee.download_and_unpack_runtime(mxversion)

    def do_cleanup_runtimes(self, args):
        self.m2ee.cleanup_runtimes_except([])

    def do_cleanup_runtimes_except(self, args):
        self.m2ee.cleanup_runtimes_except(args.split())

    def complete_cleanup_runtimes_except(self, text, line, begidx, endidx):
        words = line[:len(line)-len(text)].split()
        found_versions = self.m2ee.list_installed_runtimes()
        return ["%s " % version for version in found_versions
                if version.startswith(text)
                and version not in words[1:]]

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
        feedback = self.m2ee.client.get_logged_in_user_names(limit)
        logger.info("Logged in users: (%s) %s" %
                    (feedback['count'], feedback['users']))
        return feedback['count']

    def precmd(self, line):
        self.m2ee.reload_config_if_changed()
        if line:
            logger.trace("Executing command: %s" % line)
        return line

    def cmdloop_handle_ctrl_c(self):
        quit = False
        while quit is not True:
            try:
                self.cmdloop()
                quit = True
            except KeyboardInterrupt:
                sys.stdout.write('\n')

    def onecmd(self, line):
        try:
            return super(CLI, self).onecmd(line)
        except m2ee.client.M2EEAdminNotAvailable:
            (pid_alive, m2ee_alive) = self.m2ee.check_alive()
            if not pid_alive and not m2ee_alive:
                logger.info("The application process is not running.")
        except m2ee.client.M2EEAdminException as e:
            logger.error(e)
        except m2ee.client.M2EEAdminHTTPException as e:
            logger.error(e)
        except m2ee.client.M2EERuntimeNotFullyRunning as e:
            logger.error(e)
        except m2ee.client.M2EEAdminTimeout as e:
            logger.error(e)
        except m2ee.exceptions.M2EEException as e:
            logger.error(e)

    # if the emptyline function is not defined, Cmd will automagically
    # repeat the previous command given, and that's not what we want
    def emptyline(self):
        pass

    def completenames(self, text, *ignored):
        do_text = "do_%s" % text
        suggestions = [a[3:] for a in self.get_names() if a.startswith(do_text)]
        if len(suggestions) == 1 \
                and "complete_%s" % suggestions[0] in self.get_names():
            suggestions[0] = "%s " % suggestions[0]
        return suggestions

    def do_help(self, args):
        print("""Welcome to m2ee, the Mendix Runtime helper tools.

Available commands:
 unpack - unpack an uploaded Mendix Deployment Archive from data/model-upload
 download_runtime - download a missing Mendix Runtime distribution
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
 check_constants - check for missing or unneeded constant definitions
 enable_debugger - enable remote debugger API
 disable_debugger - disable remote debugger API
 show_debugger_status - show whether debugger is enabled or not
 show_current_runtime_requests - show action stack of current running requests
 interrupt_request - cancel a running runtime request
 show_license_information - show details about current mendix license key
 show_cache_statistics - show details about the runtime object cache
 cleanup_runtimes - clean up downloaded Mendix Runtime versions, except the
     one currently in use
 cleanup_runtimes_except [<version> <version> ...] - clean up downloaded Mendix
     Runtime versions, except the one currently in use and other ones specified
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
 check_health - manually execute health check

Extra commands you probably don't need:
 debug - dive into a local python debug session inside this program
 dump_config - dump the yaml configuration information
 nodetach - do not detach the application process after starting
 reload - reload configuration from yaml files (this is done automatically)
 munin_config - configure option for the built-in munin plugin
 munin_values - show monitoring output gathered by the built-in munin plugin
 nagios - execute the built-in nagios plugin (will exit m2ee)
 activate_license - DANGEROUS - replace/set license key
""")

        print("Hint: use tab autocompletion for commands!")

        if args != 'expert':
            print("Use help expert to show expert and debugging commands")


def start_console_logging(level):
    logger = logging.getLogger()
    logger.setLevel(level)
    consolelogformatter = logging.Formatter("%(levelname)s: %(message)s")

    class M2EELogFilter(logging.Filter):
        def __init__(self, level, ge):
            self.level = level
            # log levels greater than and equal to (True), or below (False)
            self.ge = ge

        def filter(self, record):
            if self.ge:
                return record.levelno >= self.level
            return record.levelno < self.level

    # log everything below ERROR to to stdout
    stdoutlog = logging.StreamHandler(sys.stdout)
    stdoutlog.setFormatter(consolelogformatter)
    stdoutfilter = M2EELogFilter(logging.ERROR, False)
    stdoutlog.addFilter(stdoutfilter)

    # log everything that's ERROR and more serious to stderr
    stderrlog = logging.StreamHandler(sys.stderr)
    stderrlog.setFormatter(consolelogformatter)
    stderrfilter = M2EELogFilter(logging.ERROR, True)
    stderrlog.addFilter(stderrfilter)

    logger.addHandler(stdoutlog)
    logger.addHandler(stderrlog)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c",
        nargs=1,
        action="append",
        dest="yaml_files"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        dest="verbose",
        default=0,
        help="increase verbosity of output (-vv to be even more verbose)"
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="count",
        dest="quiet",
        default=0,
        help="decrease verbosity of output (-qq to be even more quiet)"
    )
    parser.add_argument(
        "-y",
        "--yolo",
        action="store_true",
        default=False,
        dest="yolo_mode",
        help="automatically answer all questions to run as non-interactively as possible"
    )
    parser.add_argument(
        "onecmd",
        nargs='*',
    )
    args = parser.parse_args()

    # how verbose should we be? see
    # http://docs.python.org/release/2.7/library/logging.html#logging-levels
    verbosity = args.quiet - args.verbose
    if args.quiet:
        verbosity = verbosity + args.quiet
    if args.verbose:
        verbosity = verbosity - args.verbose
    verbosity = verbosity * 10 + 20
    if verbosity > 50:
        verbosity = 100
    if verbosity < 5:
        verbosity = 5
    start_console_logging(verbosity)

    cli = CLI(
        yaml_files=args.yaml_files,
        yolo_mode=args.yolo_mode,
    )
    atexit.register(cli._cleanup_logging)
    if args.onecmd:
        cli.onecmd(' '.join(args.onecmd))
    else:
        logger.info("Application Name: %s" % cli.m2ee.config.get_app_name())
        cli.onecmd('status')
        cli.cmdloop_handle_ctrl_c()


if __name__ == '__main__':
    main()
