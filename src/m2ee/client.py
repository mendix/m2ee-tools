#
# Copyright (C) 2009 Mendix. All rights reserved.
#

from base64 import b64encode
import logging

logger = logging.getLogger(__name__)

try:
    import requests
except ImportError:
    logger.critical("Failed to import requests. This module is needed by "
                    "m2ee. Please provide it on the python library path.")
    raise


class M2EEClient:

    def __init__(self, url, password):
        self.url = url
        self.headers = {
            'X-M2EE-Authentication': b64encode(bytearray(password, 'utf-8')),
        }
        # If there's proxy settings configured in the environment, we want to
        # make sure we ignore those for this localhost connection.
        self.proxies = {
            'http': None,
        }

    def request(self, action, params=None, timeout=None):
        body = {
            'action': action,
            'params': params if params is not None else {}
        }
        logger.trace("M2EE request body: {}".format(body))
        try:
            # We use a new connection for every request. We're in charge of
            # starting and stopping and dealing with broken situations of the
            # target of our calls, so let's reduce the amount of state that's
            # dragged around.  Also, the runner code uses os.fork, and then
            # accesses the Admin API using echo requests.
            with requests.Session() as session:
                response = session.post(
                    self.url,
                    headers=self.headers,
                    json=body,
                    timeout=timeout,
                    proxies=self.proxies,
                )
        except requests.exceptions.Timeout:
            message = "Admin API does not respond. " \
                "Timeout reached after {} seconds.".format(timeout)
            logger.trace(message)
            raise M2EEAdminTimeout(message)
        except requests.exceptions.ConnectionError as ce:
            message = "Admin API connection failed: {}".format(ce)
            logger.trace(message)
            raise M2EEAdminNotAvailable(message)

        if response.status_code != 200:
            raise M2EEAdminHTTPException(
                "Non OK http status code {}. Headers: {} Body: {}".format(
                    response.status_code, response.headers, response.text))

        response_json = response.json()
        logger.trace("M2EE response: {}".format(response_json))
        result = response_json['result']
        if result == M2EEAdminException.ERR_ACTION_NOT_FOUND and action != 'runtime_status':
            status = self.runtime_status()['status']
            if status != 'running':
                raise M2EERuntimeNotFullyRunning(status, action)
        if result != 0:
            raise M2EEAdminException(action, response_json)
        return response_json.get('feedback', {})

    def ping(self, timeout=5):
        try:
            self.echo(timeout=timeout)
            return True
        except (M2EEAdminException, M2EEAdminHTTPException,
                M2EEAdminNotAvailable, M2EEAdminTimeout):
            return False

    def echo(self, params=None, timeout=5):
        myparams = {"echo": "ping"}
        if params is not None:
            myparams.update(params)
        return self.request("echo", myparams, timeout)

    def require_action(self, action):
        feedback = self.get_admin_action_info()
        if action not in feedback['action_info']:
            raise M2EEAdminException(
                action,
                {"result": M2EEAdminException.ERR_ACTION_NOT_FOUND}
            )

    def get_admin_action_info(self, timeout=None):
        return self.request("get_admin_action_info", timeout=timeout)

    def get_critical_log_messages(self, timeout=None):
        echo_feedback = self.echo()
        if echo_feedback['echo'] != "pong":
            return echo_feedback['errors']
        return []

    def shutdown(self, timeout):
        logger.trace("Sending shutdown request: timeout=%s" % timeout)
        # Currently, the exception thrown is a feature, because the shutdown
        # action gets interrupted while executing. Even if an internal error
        # occurs in the runtime / appcontainer there's no point in trying to
        # handle it, if it would show up here, since there's an unforgiving
        # System.exit(0); in the finally clause of the shutdown action. ;-)
        try:
            self.request("shutdown", timeout=timeout)
        except Exception:
            pass

    def close_stdio(self, timeout=None):
        return self.request("close_stdio", timeout=timeout)

    def runtime_status(self, timeout=None):
        return self.request("runtime_status", timeout=timeout)

    def runtime_statistics(self, timeout=None):
        return self.request("runtime_statistics", timeout=timeout)

    def server_statistics(self, timeout=None):
        return self.request("server_statistics", timeout=timeout)

    def create_log_subscriber(self, params, timeout=None):
        return self.request("create_log_subscriber", params, timeout=timeout)

    def start_logging(self, timeout=None):
        return self.request("start_logging", timeout=timeout)

    def update_configuration(self, params, timeout=None):
        return self.request("update_configuration", params, timeout=timeout)

    def update_appcontainer_configuration(self, params, timeout=None):
        return self.request("update_appcontainer_configuration", params, timeout=timeout)

    def start(self, params=None, timeout=None):
        return self.request("start", params, timeout=timeout)

    def get_ddl_commands(self, params=None, timeout=None):
        return self.request("get_ddl_commands", params, timeout=timeout)

    def execute_ddl_commands(self, params=None, timeout=None):
        return self.request("execute_ddl_commands", params, timeout=timeout)

    def update_admin_user(self, params, timeout=None):
        return self.request("update_admin_user", params, timeout=timeout)

    def create_admin_user(self, params, timeout=None):
        return self.request("create_admin_user", params, timeout=timeout)

    def get_logged_in_user_names(self, params=None, timeout=None):
        return self.request("get_logged_in_user_names", params, timeout=timeout)

    def set_jetty_options(self, params=None, timeout=None):
        return self.request("set_jetty_options", params, timeout=timeout)

    def add_mime_type(self, params, timeout=None):
        return self.request("add_mime_type", params, timeout=timeout)

    def about(self, timeout=None):
        return self.request("about", timeout=timeout)

    def set_log_level(self, params, timeout=None):
        return self.request("set_log_level", params, timeout=timeout)

    def get_log_settings(self, params, timeout=None):
        return self.request("get_log_settings", params, timeout=timeout)

    def check_health(self, params=None, timeout=None):
        return self.request("check_health", params, timeout=timeout)

    def get_current_runtime_requests(self, timeout=None):
        return self.request("get_current_runtime_requests", timeout=timeout)

    def interrupt_request(self, params, timeout=None):
        return self.request("interrupt_request", params, timeout=timeout)

    def get_all_thread_stack_traces(self, timeout=None):
        return self.request("get_all_thread_stack_traces", timeout=timeout)

    def get_license_information(self, timeout=None):
        return self.request("get_license_information", timeout=timeout)

    def set_license(self, params, timeout=None):
        return self.request("set_license", params, timeout=timeout)

    def create_runtime(self, params, timeout=None):
        return self.request("createruntime", params, timeout=timeout)

    def enable_debugger(self, params, timeout=None):
        return self.request("enable_debugger", params, timeout=timeout)

    def disable_debugger(self, timeout=None):
        return self.request("disable_debugger", timeout=timeout)

    def get_debugger_status(self, timeout=None):
        return self.request("get_debugger_status", timeout=timeout)

    def cache_statistics(self, timeout=None):
        return self.request("cache_statistics", timeout=timeout)


class M2EEAdminHTTPException(Exception):
    pass


class M2EEAdminNotAvailable(Exception):
    pass


class M2EEAdminTimeout(Exception):
    pass


class M2EERuntimeNotFullyRunning(Exception):
    def __init__(self, status, action):
        self.status = status
        self.action = action

    def __str__(self):
        return "The Mendix Runtime is not fully running, but reporting status '%s'. " \
               "Unable to execute action %s." % (self.status, self.action)


class M2EEAdminException(Exception):

    ERR_REQUEST_NULL = -1
    ERR_CONTENT_TYPE = -2
    ERR_HTTP_METHOD = -3
    ERR_FORBIDDEN = -4
    ERR_ACTION_NOT_FOUND = -5
    ERR_READ_REQUEST = -6
    ERR_WRITE_REQUEST = -7

    # Note: if an action gets introduced in multiple Mendix versions,
    # they can be specified as a tuple, like:
    # "get_current_runtime_requests": ('2.5.8', '3.1'),
    implemented_in = {
        "cache_statistics": '4',
        "enable_debugger": '4.3',
        "disable_debugger": '4.3',
        "get_debugger_status": '4.3',
        "get_current_runtime_requests": '3.1',
        "interrupt_request": '3.1',
        "get_all_thread_stack_traces": '3.2',
    }

    def __init__(self, action, json):
        self.action = action
        self.json = json
        self.result = json['result']
        self.feedback = json.get('feedback', {})
        self.message = json.get('message', None)
        self.cause = json.get('cause', None)
        self.stacktrace = json.get('stacktrace', None)

    def __str__(self):
        if ((self.result == M2EEAdminException.ERR_ACTION_NOT_FOUND
             and self.action in M2EEAdminException.implemented_in)):
            avail_since = M2EEAdminException.implemented_in[self.action]
            if isinstance(avail_since, tuple):
                if len(avail_since) > 2:
                    implemented_in_msg = (
                        '%s, %s and %s' %
                        (
                            ', '.join(map(str, avail_since[:-2])),
                            avail_since[-2], avail_since[-1]
                        )
                    )
                else:
                    implemented_in_msg = '%s and %s' % avail_since
            else:
                implemented_in_msg = avail_since
            return ("This action is not available in the Mendix Runtime "
                    "version you are currently using. It was implemented "
                    "in Mendix %s" % implemented_in_msg)
        else:
            error = "Executing %s did not succeed: result: %s, message: %s" % (
                self.action, self.result, self.message)
            if self.cause is not None:
                error = "%s, caused by: %s" % (error, self.cause)
            return error
