
import getpass
import os
import ConfigParser
from optparse import OptionParser
from m2ee import M2EE
from m2ee.log import logger

class API():

    def __init__(self, username, admin_port, password, runtime_port=None, 
            jid=None, jvm_size=128):
        (base, pid_file, policy_location, tmp_dir) = get_file_locations(username)
        logsubscriber_name = 'filesubscriber'
        config = {'mxnode' : 
                    { 'mxjar_repo' : '/usr/local/share/mendix/'},
                'm2ee' : 
                    {'app_name' : username, 'app_base' : base, 'admin_port' : admin_port, 
                        'admin_pass' : password, 'pidfile' : pid_file,
                        'appcontainer_version' : 'latest',
                     'javaopts' : ["-Djava.security.manager",
                                   "-Djava.security.policy=%s" % policy_location,
                                   "-Dfile.encoding=UTF-8",
                                   "-Dsun.io.useCanonPrefixCache=false",
                                   "-Djava.util.prefs.userRoot=%s" % base,
                                   "-Djava.io.tmpdir=%s" % tmp_dir,
                                   "-XX:MaxPermSize=128M",
                                   "-Xmx%sM" % jvm_size]
                     },
                'mxruntime' : { 'DTAPMode' : 'P' },
                'logging': [{
                    'name' : logsubscriber_name,
                    'type' : 'file',
                    'autosubscribe' : 'TRACE',
                    'filename' : '%s/data/log/logging.log' % base}],
                'mimetypes' : { 'bmp' : 'image/bmp', 'log' : 'text/plain'}
                }

        if jid:
            config['m2ee']['xmpp'] = {'jid' : jid, 'password' : password, 
                    'logsubscriber' : logsubscriber_name}
        if runtime_port is not None:
            config['m2ee']['runtime_port'] = runtime_port

        self.m2ee = M2EE(config=config)

    def start(self):
        return self.m2ee.start_appcontainer()

    def stop(self):
        return self.m2ee.runner._terminate()

def get_file_locations(username):
    slots_dir = '/srv/cloud/slots/'
    base = os.path.realpath(os.path.join(slots_dir, username, 'deploy'))
    if not base.startswith(slots_dir):
        raise Exception('Directory traversal attempt detected')
    policy_location = os.path.join(slots_dir, username, 'config', '.policy')
    if not policy_location.startswith(slots_dir):
        raise Exception('Directory traversal attempt detected')
    tmp_dir = os.path.join(base, 'data', 'tmp')
    pid_file = os.path.join(base, '%s.pid' % username)
    if not pid_file.startswith(slots_dir):
        raise Exception('Directory traversal attempt detected')
    return (base, pid_file, policy_location, tmp_dir)


def set_verbosity(options):
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

def start(username, admin_port, password, runtime_port, jid, jvm_size=None, verbosity=5):
    logger.setLevel(verbosity)
    return API(username, admin_port,  password, runtime_port=runtime_port, 
            jid=jid, jvm_size=jvm_size).start()

def stop(username, admin_port, password, verbosity=50):
    logger.setLevel(verbosity)
    return API(username, admin_port, password).stop()

if __name__ == '__main__':
    parser = OptionParser()
    parser.add_option("-v", "--verbose", action="count", dest="verbose",
            help="increase verbosity of output (-vv to be even more verbose)")
    parser.add_option("-q", "--quiet", action="count", dest="quiet",
            help="decrease verbosity of output (-qq to be even more quiet)")
    (options, args) = parser.parse_args()
    set_verbosity(options)

    username = getpass.getuser()
    config = ConfigParser.ConfigParser()
    config.read('/usr/local/etc/cloud.conf')
    jid = config.get('NodeController', 'jid')
    password = config.get('NodeController', 'jid_password')
    runtime_port = int(username[2:])
    admin_port = runtime_port + 1000


    API(username, admin_port, password, runtime_port, jid).start()

