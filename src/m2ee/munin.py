#
# Copyright (c) 2009-2014, Mendix bv
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


default_stats = {
    "languages": ["en_US"],
    "entities": 0,
    "threadpool": {
        "threads_priority": 0,
        "max_threads": 0,
        "min_threads": 0,
        "max_idle_time_s": 0,
        "max_queued": -0,
        "threads": 0,
        "idle_threads": 0,
        "max_stop_time_s": 0
    },
    "memory": {
        "init_heap": 0,
        "code": 0,
        "used_heap": 0,
        "survivor": 0,
        "max_nonheap": 0,
        "committed_heap": 0,
        "tenured": 0,
        "permanent": 0,
        "used_nonheap": 0,
        "eden": 0,
        "init_nonheap": 0,
        "committed_nonheap": 0,
        "max_heap": 0
    },
    "sessions": {
        "named_users": 0,
        "anonymous_sessions": 0,
        "named_user_sessions": 0,
        "user_sessions": {}
    },
    "requests": {
        "": 0,
        "debugger/": 0,
        "ws/": 0,
        "xas/": 0,
        "ws-doc/": 0,
        "file": 0
    },
    "cache": {
        "total_count": 0,
        "disk_count": 0,
        "memory_count": 0
    },
    "jetty": {
        "max_idle_time_s": 0,
        "current_connections": 0,
        "max_connections": 0,
        "max_idle_time_s_low_resources": 0
    },
    "connectionbus": {
        "insert": 0,
        "transaction": 0,
        "update": 0,
        "select": 0,
        "delete": 0
    }
}


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
            try:
                fd = open(config_cache)
                stats = json.loads(fd.read())
                fd.close()
            except IOError, e:
                logger.error("Error reading munin cache file %s: %s" %
                             (config_cache, e))
                stats = default_stats
            except ValueError, e:
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

    # object cache
    if "cache" in stats:
        print("multigraph mxruntime_cache_%s" % name)
        funcs['cache'](name, stats)
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
%s.draw LINE1
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
%s.draw LINE1
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
named_user_sessions.draw LINE1
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
named_user_sessions.draw LINE1
named_user_sessions.info amount of concurrent named user sessions
anonymous_sessions.label concurrent anonymous user sessions
anonymous_sessions.draw LINE1
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
committed.draw LINE1
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
active_threads.label active threads
active_threads.draw LINE1
active_threads.info Active thread count
threadpool_size.label threadpool size
threadpool_size.draw LINE1
threadpool_size.info Current threadpool size""" % name)


def print_threadpool_values(name, stats):
    min_threads = stats['threadpool']['min_threads']
    max_threads = stats['threadpool']['max_threads']
    threadpool_size = stats['threadpool']['threads']
    idle_threads = stats['threadpool']['idle_threads']

    active_threads = threadpool_size - idle_threads

    print("min_threads.value %s" % min_threads)
    print("max_threads.value %s" % max_threads)
    print("active_threads.value %s" % active_threads)
    print("threadpool_size.value %s" % threadpool_size)


config_funcs['threadpool'] = print_threadpool_config
values_funcs['threadpool'] = print_threadpool_values


def print_cache_config(name, stats):
    print("""graph_args --base 1000 -l 0
graph_vlabel objects
graph_title %s - Object Cache
graph_category Mendix
graph_info This graph shows the total amount of objects in the runtime object cache
total.label Objects in cache
total.draw LINE1
total.info Total amount of objects""" % name)


def print_cache_values(name, stats):
    print("total.value %s" % stats['cache']['total_count'])

config_funcs['cache'] = print_cache_config
values_funcs['cache'] = print_cache_values
