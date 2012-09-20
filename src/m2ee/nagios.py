#
# Copyright (c) 2009-2012, Mendix bv
# All Rights Reserved.
#
# http://www.mendix.com/
#

STATE_OK=0
STATE_WARNING=1
STATE_CRITICAL=2
STATE_UNKNOWN=3
STATE_DEPENDENT=4

RUNNING=-1

def check(runner, client):

    runtime_state = check_process(runner, client)
    if runtime_state != RUNNING:
        return runtime_state

    runtime_health = check_health(client)

    if runtime_health != STATE_OK:
        return runtime_health

	critical_log_status = check_critical_logs(client)
	if critical_log_status != STATE_OK:
		return critical_log_status

    # everything seems to be fine, print version info and exit
    about_feedback = client.about().get_feedback()
    print "MxRuntime OK: healthy, using version %s" % about_feedback['version']
    return STATE_OK

def check_process(runner, client):
    pid = runner.get_pid()

    if pid == None:
        print "MxRuntime OK: Not running."
        return STATE_OK
    pid_alive = runner.check_pid()
    m2ee_alive = client.ping()

    if pid_alive and not m2ee_alive:
        print "MxRuntime CRITICAL: pid %s is alive, but m2ee does not respond." % pid
        return STATE_CRITICAL

    if not pid_alive and not m2ee_alive:
        print "MxRuntime CRITICAL: pid %s is not available, m2ee does not respond." % pid
        return STATE_CRITICAL

    if not pid_alive and m2ee_alive:
        print "MxRuntime WARNING: pid %s is not available, but m2ee responds." % pid
        return STATE_WARNING

    # right here, m2ee is alive
    if not m2ee_alive:
        print "MxRuntime WARNING: plugin has broken logic, m2ee should be alive"
        return STATE_WARNING

    status_feedback = client.runtime_status().get_feedback()
    if status_feedback['status'] == 'starting':
        print "MxRuntime WARNING: application is still starting up..."
        return STATE_WARNING
    elif status_feedback['status'] != 'running':
        print "MxRuntime CRITICAL: application is in state %s" % status_feedback['status']
        return STATE_CRITICAL

    return RUNNING

def check_health(client):
    health_response = client.check_health()
    if not health_response.has_error():
        feedback = health_response.get_feedback()
        if feedback['health'] == 'healthy':
            pass
        elif feedback['health'] == 'sick':
            print "MxRuntime WARNING: Health: %s" % feedback['diagnosis']
            return STATE_WARNING
        elif feedback['health'] == 'unknown':
            # no health check action was configured
            pass
        else:
            print "MxRuntime WARNING: Unexpected health check status: %s" % feedback['health']
            return STATE_WARNING
    else:
        # Yes, we need API versioning!
        if health_response.get_result() == 3 and health_response.get_cause() == "java.lang.IllegalArgumentException: Action should not be null":
            # b0rk, b0rk, b0rk, in 2.5.4 or 2.5.5 this means that the runtime is health-check
            # capable, but no health check microflow is defined
            pass
        elif health_response.get_result() == health_response.ERR_ACTION_NOT_FOUND:
            # Admin action 'check_health' does not exist.
            pass
        else:
            print "MxRuntime WARNING: Health check failed unexpectedly: %s" % health_response.get_error()
            return STATE_WARNING
    return STATE_OK

def check_critical_logs(client):
    errors = client.get_critical_log_messages()
    if len(errors) != 0:
        print "MxRuntime CRITICAL: %d critical error(s) were logged" % len(errors)
        print '\n'.join(errors)
        return STATE_CRITICAL
	return STATE_OK

