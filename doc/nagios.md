# Monitoring a Mendix application using Nagios

The Mendix m2ee-tools have built-in support for integrating Mendix applications into your existing monitoring and alerting infrastructure using Nagios, using the m2ee nagios command.

*This plugin uses the M2EE API which provides a lifecycle management and inspection interface to the application. It does NOT check availability of the application at the public interface used by e.g. an end user's web browser. This is by design.*

## Configuration

The following is a simple nagios plugin wrapper you can install at /usr/local/lib/nagios/plugins/check_mxruntime, which will trigger the m2ee tools script to output monitoring information:

    #!/bin/sh
    m2ee -qqq nagios
    exit $?

To make nagios nrpe execute this plugin, we need to define the command in nrpe, and use a minimal amount of sudo configuration to let nrpe execute the plugin using the application user account. The following configuration uses the 'Some Customer' application, running as local user somecust:

    command[check_mxruntime_somecust]=sudo -u somecust /usr/local/lib/nagios/plugins/check_mxruntime

The sudo configuration would look like this:

    nagios  ALL=(somecust) NOPASSWD: /usr/local/lib/nagios/plugins/check_mxruntime ""

A sample minimal nagios service check definition would be:

    define service {
        host_name               example.mendix.net.
        service_description     Mendix Runtime - Some Customer
        check_command           check_nrpe!check_mxruntime_somecust
    }

In case the application management interface does not respond, e.g. because this functionality was the victim of threads being killed during a JVM out of memory, you might get timeout messages from nrpe, instead of output from the monitoring plugin. A modified nrpe command and service definition, using a higher timeout of, say, 30 seconds would look like:

    define command {
        command_name    check_nrpe_timeout30
        command_line    /usr/lib/nagios/plugins/check_nrpe -H $HOSTADDRESS$ -c $ARG1$ -t 30
    }

    define service {
        host_name               example.mendix.net.
        service_description     Mendix Runtime - Some Customer
        check_command           check_nrpe_timeout30!check_mxruntime_somecust
    }

Using this extended timeout is recommended, unless you have a very large number of problematic crashed Mendix applications at the same time in your network (in which case you're probably suffering from another problem that needs attention...).

## Checks and plugin output

The monitoring plugin will execute several checks, according to which output is generated, and error codes are returned:

| Check  | Output | State | Explanation |
| ------ | ------ | ----- | ----------- |
| Application process is not running | Application is not running. | OK | The application was never started, or explicitely told to stop. |
| A JVM process exists, but the M2EE management interface does not respond to a simple 'ping' request. | Application process is running, but Admin API is not available. | CRITICAL | M2EE API inside the application platform does not respond, the Mendix application cannot be managed. This could been a result of random damage during a JVM out of memory incident. |
| A JVM process with a particular process id should exist, and should be our application process, but we cannot signal it, or it's not present. | Application should be running, but the application process has disappeared! | CRITICAL | This is likely the result from a configuration error, or the result of the JVM process being killed by an operating system OOM, or by a segmentation fault or something worse, if possible. |
| Log messages were logged to CRITICAL level | &lt;num&gt; critical error(s) were logged: &lt;logmessages follow on separate lines&gt; | CRITICAL | The CRITICAL log level is reserved for issuing messages in 'rare cases where the application may not be able to function reliably anymore', meaning e.g. there's a chance of data corruption when the application continues to be running. Internal JVM Errors are logged to this level. Out of Memory errors, which are JVM Errors must be treated as harmful for the stability and integrity of your mendix application process. |
| Lifecycle status is 'starting' | Application is still starting up... | WARNING | This application is taking a very long time to start... or it's waiting for interactive response to e.g. a question about executing database structure changes |
| Lifecycle status is not 'running' | Application is in state &lt;state&gt; | CRITICAL | The application failed to start, or fails to shut down when being asked to. |
| Health check microflow is configured, but does not return an empty string | Health: &lt;microflow output&gt; | WARNING | A health check microflow was implemented in the application model, but it detected a warning that needs to be reported, and returns this warning as string value when the microflow finishes. |

- - -

[Back to overview](README.md)
