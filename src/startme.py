
import ConfigParser
from m2ee.client import M2EEClient
from m2ee.runner import M2EERunner
from m2ee.config import M2EEConfig
from m2ee.log import logger
import os

class API():

    def __init__(self, username, runtime_port, admin_port, password):
        base = '/srv/cloud/slots/%s/deploy/' % username
        pid_file = '%s/%s.pid' % (base, username)
        config = {'mxnode' : 
                    { 'mxjar_repo' : '/usr/local/share/mendix/'},
                'm2ee' : 
                    {'app_name' : username, 'app_base' : base, 'admin_port' : admin_port, 
                        'admin_pass' : password, 'runtime_port' : runtime_port, 'pidfile' : pid_file},
                'mxruntime' : {}    
                }
        self._config = M2EEConfig(config=config)
        self._client = M2EEClient('http://127.0.0.1:%s/' % admin_port, password)
        self._runner = M2EERunner(self._config, self._client)

    def start(self):
        logger.debug("Checking if the runtime is already alive...")
        (pid_alive, m2ee_alive) = self._check_alive()
        if not pid_alive and not m2ee_alive:
            logger.info("Trying to start the MxRuntime...")
            if not self._runner.start():
                return
        elif not m2ee_alive:
            return

        # check if Appcontainer startup went OK
        m2eeresponse = self._client.runtime_status()
        if m2eeresponse.has_error():
            m2eeresponse.display_error()
            return

        # go do startup sequence
        #self._configure_logging()
        #self._send_jetty_config()
        #self._send_mime_types()

        xmpp_credentials = self._config.get_xmpp_credentials()
        if xmpp_credentials:
            self._client.connect_xmpp(xmpp_credentials)

        # when running hybrid appcontainer, we need to create the runtime ourselves
        if self._config.get_appcontainer_version():
            self._client.create_runtime({
                "runtime_path": os.path.join(self._config.get_runtime_path(),'runtime'),
                "port": self._config.get_runtime_port(),
                "application_base_path": self._config.get_app_base(),
                "use_blocking_connector": self._config.get_runtime_blocking_connector(),
            })

        # check status, if it's created or starting, go on, else stop
        m2eeresponse = self._client.runtime_status()
        status = m2eeresponse.get_feedback()['status']
        if not status in ['created','starting']:
            logger.error("Cannot start MxRuntime when it has status %s" % status)
            return
        logger.debug("MxRuntime status: %s" % status)
        self._client.start()

    def _check_alive(self):
        pid_alive = self._runner.check_pid()
        m2ee_alive = self._client.ping()

        if pid_alive and not m2ee_alive:
            logger.error("The application process seems to be running (pid %s is alive), but does not respond to administrative requests." % self._runner.get_pid())
            logger.error("This could be caused by JVM Heap Space / Out of memory errors. Please review the application logfiles.")
            logger.error("You should consider restarting the application process, because it is likely to be in an undetermined broken state right now.")
        elif not pid_alive and m2ee_alive:
            logger.error("pid %s is not available, but m2ee responds" % self._runner.get_pid())
        return (pid_alive, m2ee_alive)

if __name__ == '__main__':
    username = 'tr10000'
    config = ConfigParser.ConfigParser()
    config.read('/usr/local/etc/cloud.conf')
    password = config.get('NodeController', 'jid_password')
    runtime_port = int(username[2:])
    admin_port = runtime_port + 1000


    API(username, admin_port, runtime_port, password).start()

