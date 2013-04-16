import os
import shutil
import unittest2 as unittest
from m2ee import M2EE
import m2ee.client_errno as client_error_codes
import m2ee.nagios as nagios
import requests
from m2ee.log import logger

current_version = None
def get_m2ee(version):
    testdir = 'projects/%s' % version
    app_base = os.path.join(os.getcwd(), '%s/deployment' % testdir)
    with open('projects/m2ee.yaml.tmpl') as tmpl:
        with open('%s/m2ee.yaml' % testdir, 'w') as yaml:
            yaml.write(tmpl.read().format(app_base=app_base))
    m2ee = M2EE(yamlfiles=['%s/m2ee.yaml' % testdir])
    m2ee.admin_url = 'http://127.0.0.1:%d' % m2ee.config.get_admin_port()
    m2ee.runtime_url = 'http://127.0.0.1:%d' % m2ee.config.get_runtime_port()

    return m2ee

class M2EEApiTest(unittest.TestCase):

    def test_start(self):
        db_dir = os.path.join(self.m2ee.config.get_app_base(),
                              'data/database/hsqldb')
        for filename in os.listdir(db_dir):
            shutil.rmtree(os.path.join(db_dir, filename))
        self.assert_http_connection_error(self.m2ee.admin_url)
        self.assert_http_connection_error(self.m2ee.runtime_url)
        self.assertTrue(self.m2ee.start_appcontainer(),
                        "Failed to start appcontainer")
        self.assert_http_code(self.m2ee.admin_url)
        self.assert_http_code(self.m2ee.runtime_url, code=503)
        self.assertTrue(self.m2ee.send_runtime_config(),
                        "Failed to send runtime config")
        response = self.m2ee.start_runtime({})
        self.assertEqual(
            response.get_result(),
            client_error_codes.start_NO_EXISTING_DB,
            "Database was already present"
        )
        if self.m2ee.config.runtime_version // 2.5:
            response = self.m2ee.start_runtime({'autocreatedb': True})

        response = self.m2ee.client.execute_ddl_commands()
        response = self.m2ee.start_runtime({})
        self.assertEqual(
            response.get_result(),
            client_error_codes.SUCCESS,
            "Unable to start runtime: %s" % response.get_message()
        )
        self.assert_http_code(self.m2ee.runtime_url)

    def test_debugger(self):
        response = self.m2ee.client.enable_debugger({'password': 'password'})
        if self.m2ee.config.runtime_version < 4.3:
            self.assertEqual(
                response.get_result(),
                response.ERR_ACTION_NOT_FOUND,
                "Debugger present on < 4.3"
            )
        else:
            self.assertEqual(
                response.get_result(),
                0,
                "Could not start debugger: %s" % response.get_message()
            )
            response = self.m2ee.client.disable_debugger()
            self.assertEqual(
                response.get_result(),
                0,
                "Could not stop debugger: %s" % response.get_message()
            )

    def test_critical_logs(self):
        code, message = nagios._check_critical_logs(self.m2ee.client)
        self.assertEqual(code, nagios.STATE_OK, message)

    def test_health(self):
        code, message = nagios._check_health(self.m2ee.client)
        if self.m2ee.config.runtime_version < "2.5.8":
            self.assertEqual(code, nagios.STATE_OK, message)
        else:
            self.assertEqual(code, nagios.STATE_WARNING, message)

    def test_stop(self):
        self.assertTrue(self.m2ee.stop())
        self.assert_http_connection_error(self.m2ee.admin_url)
        self.assert_http_connection_error(self.m2ee.runtime_url)

    def assert_http_code(self, url, code=200, method='GET'):
        result = requests.request(method, url)
        self.assertEqual(
            result.status_code,
            code,
            "HTTP failed ({url}), got {result}, expected {expected}".format(
                url=url,
                result=result.status_code,
                expected=code
            )
        )

    def assert_http_connection_error(self, url):
        try:
            requests.get(url)
            self.assertTrue(False, "Could make connection to server %s" % url)
        except requests.ConnectionError:
            pass

if __name__ == '__main__':

    logger.setLevel(50)
    for version in sorted(os.listdir('projects')):
        if version == 'm2ee.yaml.tmpl' or version == '.gitignore':
            continue
        print("\nSTARTING TESTS FOR MENDIX %s" % version)
        suite = unittest.TestSuite()
        m2ee = get_m2ee(version)

        for test in ['start', 'debugger', 'critical_logs', 'health', 'stop']:
            test = M2EEApiTest('test_%s' % test)
            test.m2ee = m2ee
            suite.addTest(test)
        unittest.TextTestRunner(verbosity=2).run(suite)
