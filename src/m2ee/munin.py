#
# Copyright (c) 2009-2013, Mendix bv
# All Rights Reserved.
#
# http://www.mendix.com/
#

import pwd
import os
import string

from m2ee.log import logger

# Use json if available. If not (python 2.5) we need to import the simplejson
# module instead, which has to be available.
try:
    import json
except ImportError:
    try:
        import simplejson as json
    except ImportError, ie:
        logger.critical("Failed to import json as well as simplejson. If "
                        "using python 2.5, you need to provide the simplejson "
                        "module in your python library path.")
        raise

config_funcs = {}
values_funcs = {}


def print_all(client, config, options, name, print_config=False):

    if name == "":
        name = pwd.getpwuid(os.getuid())[0]

    if print_config:
        funcs = config_funcs
    else:
        funcs = values_funcs

    if options is None:
        options = {}
    # place to store last known good statistics result to be used for munin
    # config when the app is down or b0rked
    config_cache = options.get('config_cache', os.path.join(
        config.get_default_dotm2ee_directory(), 'munin-cache.json'))
    graph_total_named_users = options.get('graph_total_named_users', True)

    # TODO: even better error/exception handling
    stats = {}
    try:
        logger.debug("trying to fetch runtime/server statistics")
        m2eeresponse = client.runtime_statistics()
        if not m2eeresponse.has_error():
            stats.update(m2eeresponse.get_feedback())
        m2eeresponse = client.server_statistics()
        if not m2eeresponse.has_error():
            stats.update(m2eeresponse.get_feedback())
        if type(stats['requests']) == list:
            # convert back to normal, whraagh
            bork = {}
            for x in stats['requests']:
                bork[x['name']] = x['value']
            stats['requests'] = bork
        # write last-known-good stats to cache
        try:
            file(config_cache, 'w+').write(json.dumps(stats))
        except Exception, e:
            logger.error("Error writing munin config cache to %s: %s",
                         (config_cache, e))
    except Exception, e:
        # assume something bad happened, like
        # socket.error: [Errno 111] Connection refused
        logger.error("Error fetching runtime/server statstics: %s", e)
        if print_config:
            logger.debug("Loading munin cache from %s" % config_cache)
            fd = None
            try:
                fd = open(config_cache)
            except Exception, e:
                logger.error("Error reading munin cache file %s: %s" %
                             (config_cache, e))
                return
            try:
                stats = json.loads(fd.read())
                fd.close()
            except Exception, e:
                logger.error("Error parsing munin cache file %s: %s" %
                             (config_cache, e))
                return
        else:
            return

    # requests
    print("multigraph mxruntime_requests_%s" % name)
    funcs['requests'](name, stats)
    print

    # connectionbus
    if "connectionbus" in stats:
        print("multigraph mxruntime_connectionbus_%s" % name)
        funcs['connectionbus'](name, stats)
        print

    # concurrent user sessions
    print("multigraph mxruntime_sessions_%s" % name)
    if type(stats['sessions']) != dict:
        funcs['sessions_pre254'](name, stats)
    else:
        funcs['sessions'](name, stats, graph_total_named_users)
    print

    # jvmheap
    print("multigraph mxruntime_jvmheap_%s" % name)
    funcs['jvmheap'](name, stats)
    print

    # threadpool
    if "threadpool" in stats:
        print("multigraph m2eeserver_threadpool_%s" % name)
        funcs['threadpool'](name, stats)
        print


def print_requests_config(name, stats):
    print("""graph_args --base 1000 -l 0
graph_vlabel Requests per second
graph_title %s - MxRuntime Requests
graph_category Mendix
graph_info This graph shows the amount of requests this MxRuntime handles""" %
          name)
    for sub in stats['requests'].iterkeys():
        substrip = '_' + string.strip(sub, '/').replace('-', '_')
        if sub != '':
            subname = sub
        else:
            subname = '/'
        print("""%s.label %s
%s.draw LINE2
%s.info amount of requests this MxRuntime handles on %s
%s.type DERIVE
%s.min 0""" % (substrip, subname, substrip, substrip, subname, substrip,
               substrip))


def print_requests_values(name, stats):
    for sub, count in stats['requests'].iteritems():
        substrip = '_' + string.strip(sub, '/').replace('-', '_')
        print("%s.value %s" % (substrip, count))

config_funcs['requests'] = print_requests_config
values_funcs['requests'] = print_requests_values


def print_connectionbus_config(name, stats):
    print("""graph_args --base 1000 -l 0
graph_vlabel Statements per second
graph_title %s - Database Queries
graph_category Mendix
graph_info This graph shows the amount of executed transactions and queries"""
          % name)
    for s in stats['connectionbus'].iterkeys():
        print("""%s.label %ss
%s.draw LINE2
%s.info amount of %ss
%s.type DERIVE
%s.min 0""" % (s, s, s, s, s, s, s))


def print_connectionbus_values(name, stats):
    for s, count in stats['connectionbus'].iteritems():
        print("%s.value %s" % (s, count))

config_funcs['connectionbus'] = print_connectionbus_config
values_funcs['connectionbus'] = print_connectionbus_values


def print_sessions_pre254_config(name, stats):
    """
    concurrent user sessions for mxruntime < 2.5.4
    named_user_sessions counts names as well as anonymous sessions
    !! you stil need to rename the rrd files in /var/lib/munin/ !!
    """
    print("""graph_args --base 1000 -l 0
graph_vlabel Concurrent user sessions
graph_title %s - MxRuntime Users
graph_category Mendix
graph_info This graph shows the amount of concurrent user sessions
named_user_sessions.label concurrent user sessions
named_user_sessions.draw LINE2
named_user_sessions.info amount of concurrent user sessions""" % name)


def print_sessions_pre254_values(options, stats):
    print("named_user_sessions.value %s" % stats['sessions'])

config_funcs['sessions_pre254'] = print_sessions_pre254_config
values_funcs['sessions_pre254'] = print_sessions_pre254_values


def print_sessions_config(name, stats, graph_total_named_users):
    print("""graph_args --base 1000 -l 0
graph_vlabel Concurrent user sessions
graph_title %s - MxRuntime Users
graph_category Mendix
graph_info This graph shows the amount of user accounts and sessions""" % name)
    if graph_total_named_users:
        print("""named_users.label named users
named_users.draw LINE1
named_users.info total amount of named users in the application""")
    print("""named_user_sessions.label concurrent named user sessions
named_user_sessions.draw LINE2
named_user_sessions.info amount of concurrent named user sessions
anonymous_sessions.label concurrent anonymous user sessions
anonymous_sessions.draw LINE2
anonymous_sessions.info amount of concurrent anonymous user sessions""")


def print_sessions_values(name, stats, graph_total_named_users):
    if graph_total_named_users:
        print("named_users.value %s" % stats['sessions']['named_users'])
    print("named_user_sessions.value %s" %
          stats['sessions']['named_user_sessions'])
    print("anonymous_sessions.value %s" %
          stats['sessions']['anonymous_sessions'])

config_funcs['sessions'] = print_sessions_config
values_funcs['sessions'] = print_sessions_values


def print_jvmheap_config(name, stats):
    print("""graph_args --base 1024 -l 0
graph_vlabel Bytes
graph_title %s - JVM Memory Usage
graph_category Mendix
graph_info This graph shows memory pool information on the Java JVM
permanent.label permanent generation
permanent.draw AREA
permanent.info Non-heap memory used to store bytecode versions of classes
code.label code cache
code.draw STACK
code.info Non-heap memory used for compilation and storage of native code
tenured.label tenured generation
tenured.draw STACK
tenured.info Old generation of the heap that holds long living objects
survivor.label survivor space
survivor.draw STACK
survivor.info Survivor Space of the Young Generation
eden.label eden space
eden.draw STACK
eden.info Objects are created in Eden
free.label unused
free.draw STACK
free.info Unused memory allocated for use by this JVM
committed.label allocated memory
committed.draw LINE2
committed.info Allocated size of memory for all memory pools
max.label max memory
max.draw LINE1
max.info Total maximum size of memory that could be allocated for this JVM""" %
          name)


def print_jvmheap_values(name, stats):
    memory = stats['memory']
    used = 0
    for k in ['permanent', 'code', 'tenured', 'survivor', 'eden']:
        used = used + memory[k]
        print('%s.value %s' % (k, memory[k]))

    committed = 0
    free = 0
    maxx = 0

    committed = memory['committed_nonheap'] + memory['committed_heap']
    free = committed - used
    maxx = memory['max_nonheap'] + memory['max_heap']

    print("free.value %s" % free)
    print("committed.value %s" % committed)
    print("max.value %s" % maxx)

config_funcs['jvmheap'] = print_jvmheap_config
values_funcs['jvmheap'] = print_jvmheap_values


def print_threadpool_config(name, stats):
    print("""graph_args --base 1000 -l 0
graph_vlabel Jetty Threadpool
graph_title %s - Jetty Threadpool
graph_category Mendix
graph_info This graph shows threadpool usage information on Jetty
min_threads.label min threads
min_threads.draw LINE1
min_threads.info Minimum number of threads
max_threads.label max threads
max_threads.draw LINE1
max_threads.info Maximum number of threads
queue_size.label queue size
queue_size.draw STACK
queue_size.info Job queue size
threadpool_size.label threadpool size
threadpool_size.draw LINE2
threadpool_size.info Current threadpool size
active_threads.label active threads
active_threads.draw LINE2
active_threads.info Active thread count
max_threads_and_queue.label max threads and queue
max_threads_and_queue.draw LINE1
max_threads_and_queue.info Maximum number of threads and queue size""" % name)


def print_threadpool_values(name, stats):
    min_threads = stats['threadpool']['min_threads']
    max_threads = stats['threadpool']['max_threads']
    #queue_size = stats['threadpool']['??']
    threadpool_size = stats['threadpool']['threads']
    idle_threads = stats['threadpool']['idle_threads']
    max_queued = stats['threadpool']['max_queued']

    active_threads = threadpool_size - idle_threads

    print("min_threads.value %s" % min_threads)
    print("max_threads.value %s" % max_threads)
    #print("queue_size.value %s" % queue_size)
    print("threadpool_size.value %s" % threadpool_size)
    print("active_threads.value %s" % active_threads)

    if max_queued != -1:
        print("max_threads_and_queue %s" % max_threads + max_queued)

config_funcs['threadpool'] = print_threadpool_config
values_funcs['threadpool'] = print_threadpool_values
