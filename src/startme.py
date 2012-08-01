
import getpass
import ConfigParser
from optparse import OptionParser
from m2ee import M2EE
from m2ee.log import logger

class API():

    def __init__(self, username, admin_port, password, runtime_port=None, jid=None):
        base = '/srv/cloud/slots/%s/deploy/' % username
        pid_file = '%s/%s.pid' % (base, username)
        config = {'mxnode' : 
                    { 'mxjar_repo' : '/usr/local/share/mendix/'},
                'm2ee' : 
                    {'app_name' : username, 'app_base' : base, 'admin_port' : admin_port, 
                        'admin_pass' : password, 'pidfile' : pid_file,
                        'appcontainer_version' : 'latest'},
                'mxruntime' : { 'DTAPMode' : 'P' },
                'logging': [{
                    'name' : 'XMPPLogSubscriber',
                    'type' : 'file',
                    'autosubscribe' : 'INFO',
                    'filename' : '%s/data/log/logging.log' % base}],
                'mimetypes' : { 'bmp' : 'image/bmp', 'log' : 'text/plain'}
                }

        if jid is not None:
            config['m2ee']['jid'] = jid
        if runtime_port is not None:
            config['m2ee']['runtime_port'] = runtime_port

        self.m2ee = M2EE(config=config)

    def start(self):
        self.m2ee.start_appcontainer()

    def stop(self):
        self.m2ee._runner.terminate()

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

def start(username, admin_port, password, runtime_port, jid, verbosity=50):
    logger.setLevel(verbosity)
    API(username, admin_port,  password, runtime_port=runtime_port, jid=jid).start()
    return True


def stop(username, admin_port, runtime_port, verbosity=50):
    logger.setLevel(verbosity)
    API(username, admin_port, runtime_port).stop()
    return True

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


    API(username, admin_port, runtime_port, password, jid).start()

