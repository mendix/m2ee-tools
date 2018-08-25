#
# Copyright (C) 2009 Mendix. All rights reserved.
#

from __future__ import print_function
import json
import logging
import yaml
import os
import sys
import pwd
import copy

from collections import defaultdict
from m2ee.version import MXVersion
from m2ee.exceptions import M2EEException

logger = logging.getLogger(__name__)


class M2EEConfig:

    def __init__(self, yaml_files=None):
        if yaml_files is None:
            yaml_files = find_yaml_files()

        self._conf, self._mtimes = read_yaml_files(yaml_files)

        self._all_systems_are_go = True

        self._check_appcontainer_config()
        self._check_runtime_config()
        self._conf['mxruntime'].setdefault(
            'BasePath', self._conf['m2ee']['app_base'])

        self._conf['mxruntime']['DTAPMode'] = 'P'

        self.fix_permissions()

        self._model_metadata = self._try_load_json(
            os.path.join(
                self._conf['m2ee']['app_base'],
                'model',
                'metadata.json',
            ))

        self.runtime_version = self._lookup_runtime_version()

        self._runtime_path = None
        if self.runtime_version is None:
            logger.info("Unable to look up mendix runtime files "
                        "because product version is yet unknown.")
            self._all_systems_are_go = False
        else:
            self._runtime_path = self.lookup_in_mxjar_repo(
                str(self.runtime_version))
            if self._runtime_path is None:
                logger.warn("Mendix Runtime not found for version %s. "
                            "You can try downloading it using the "
                            "download_runtime command." %
                            str(self.runtime_version))
                self._all_systems_are_go = False
        if self.runtime_version < 7:
            self._setup_classpath()

        if self._runtime_path and 'RuntimePath' not in self._conf['mxruntime']:
            runtimePath = os.path.join(self._runtime_path, 'runtime')
            logger.trace("Setting RuntimePath runtime config option to %s"
                         % runtimePath)
            self._conf['mxruntime']['RuntimePath'] = runtimePath

    def _setup_classpath(self):
        logger.debug("Determining classpath to be used...")
        classpath = self._setup_classpath_runtime_binary()
        classpath.extend(self._setup_classpath_model())

        if 'extend_classpath' in self._conf['m2ee']:
            if isinstance(self._conf['m2ee']['extend_classpath'], list):
                classpath.extend(self._conf['m2ee']['extend_classpath'])
            else:
                logger.warn("extend_classpath option in m2ee section in "
                            "configuration is not a list")

        self._classpath = ":".join(classpath)
        if self._classpath:
            logger.trace("Using classpath: %s" % self._classpath)
        else:
            logger.debug("No classpath will be used")

    def _try_load_json(self, jsonfile):
        logger.debug("Loading json configuration from %s" % jsonfile)
        try:
            with open(jsonfile) as f:
                config = json.load(f)
            logger.trace("contents read from %s: %s" % (jsonfile, config))
            return config
        except IOError as e:
            logger.debug("Error reading configuration file %s: %s; "
                         "ignoring..." % (jsonfile, e))
            return {}
        except ValueError as e:
            logger.error("Error parsing configuration file %s: %s" %
                         (jsonfile, e))
            return {}

    def mtime_changed(self):
        for yamlfile, mtime in self._mtimes.items():
            if os.stat(yamlfile)[8] != mtime:
                return True
        return False

    def dump(self):
        print(yaml.dump(self._conf, default_flow_style=False))

    def _check_appcontainer_config(self):
        # did we load any configuration at all?
        if not self._conf:
            logger.critical("No configuration present. Please put a m2ee.yaml "
                            "configuration file at the default location "
                            "~/.m2ee/m2ee.yaml or specify an alternate "
                            "configuration file using the -c option.")
            sys.exit(1)

        # m2ee
        for option in ['app_base', 'admin_port', 'admin_pass']:
            if not self._conf['m2ee'].get(option, None):
                logger.critical("Option %s in configuration section m2ee is "
                                "not defined!" % option)
                sys.exit(1)

        # force admin_pass to a string, prevent TypeError when base64-ing it
        # before sending to m2ee api
        self._conf['m2ee']['admin_pass'] = str(
            self._conf['m2ee']['admin_pass'])

        # Mendix >= 4.3: admin and runtime port only bind to localhost by
        # default
        self._conf['m2ee']['admin_listen_addresses'] = (
            self._conf['m2ee'].get('admin_listen_addresses', ""))
        self._conf['m2ee']['runtime_listen_addresses'] = (
            self._conf['m2ee'].get('runtime_listen_addresses', ""))

        # check admin_pass 1 or password... refuse to accept when users don't
        # change default passwords
        if (self._conf['m2ee']['admin_pass'] == '1' or
                self._conf['m2ee']['admin_pass'] == 'password'):
            logger.critical("Using admin_pass '1' or 'password' is not "
                            "allowed. Please put a long, random password into "
                            "the admin_pass configuration option. At least "
                            "change the default!")
            sys.exit(1)

        # database_dump_path
        if 'database_dump_path' not in self._conf['m2ee']:
            self._conf['m2ee']['database_dump_path'] = os.path.join(
                self._conf['m2ee']['app_base'], 'data', 'database')
        if not os.path.isdir(self._conf['m2ee']['database_dump_path']):
            logger.warn("Database dump path %s is not a directory" %
                        self._conf['m2ee']['database_dump_path'])

    def _check_runtime_config(self):
        # ensure mxjar_repo is a list, multiple locations are allowed for searching
        if not self._conf.get('mxnode', {}).get('mxjar_repo', None):
            self._conf['mxnode']['mxjar_repo'] = []
        elif not type(self._conf.get('mxnode', {})['mxjar_repo']) == list:
            self._conf['mxnode']['mxjar_repo'] = [
                self._conf['mxnode']['mxjar_repo']]
        # m2ee
        for option in ['app_name', 'app_base', 'runtime_port']:
            if not self._conf['m2ee'].get(option, None):
                logger.warn("Option %s in configuration section m2ee is not "
                            "defined!" % option)
        # check some locations for existance and permissions
        basepath = self._conf['m2ee']['app_base']
        if not os.path.exists(basepath):
            logger.critical("Application base directory %s does not exist!" %
                            basepath)
            sys.exit(1)

        # model_upload_path
        if 'model_upload_path' not in self._conf['m2ee']:
            self._conf['m2ee']['model_upload_path'] = os.path.join(
                self._conf['m2ee']['app_base'], 'data', 'model-upload')
        if not os.path.isdir(self._conf['m2ee']['model_upload_path']):
            logger.warn("Model upload path %s is not a directory" %
                        self._conf['m2ee']['model_upload_path'])

        # magically add app_base/runtimes to mxjar_repo when it's present
        magic_runtimes = os.path.join(self._conf['m2ee']['app_base'],
                                      'runtimes')
        if ((magic_runtimes not in self._conf['mxnode']['mxjar_repo']
             and os.path.isdir(magic_runtimes))):
            self._conf['mxnode']['mxjar_repo'].insert(0, magic_runtimes)

        if 'DatabasePassword' not in self._conf['mxruntime']:
            logger.warn("There is no database password present in the configuration. Either add "
                        "it to the configuration, or use the set_database_password command to "
                        "set it before trying to start the application!")

        if len(self._conf['logging']) == 0:
            logger.warn("No logging settings found, this is probably not what you want.")

    def fix_permissions(self):
        basepath = self._conf['m2ee']['app_base']
        for directory, mode in {
                "model": 0o0700,
                "web": 0o0755,
                "data": 0o0700}.items():
            fullpath = os.path.join(basepath, directory)
            if not os.path.exists(fullpath):
                logger.critical("Directory %s does not exist!" % fullpath)
                sys.exit(1)
            # TODO: detect permissions and tell user if changing is needed
            os.chmod(fullpath, mode)

    def get_felix_config_file(self):
        return os.path.join(self._conf['m2ee']['app_base'], 'model', 'felixconfig.properties')

    def write_felix_config(self):
        felix_config_file = self.get_felix_config_file()
        felix_config_path = os.path.dirname(felix_config_file)
        if not os.access(felix_config_path, os.W_OK):
            raise M2EEException("felix_config_file is not in a writable location: %s" %
                                felix_config_path,
                                errno=M2EEException.ERR_INVALID_OSGI_CONFIG)

        project_bundles_path = os.path.join(
            self._conf['m2ee']['app_base'], 'model', 'bundles'
        )
        osgi_storage_path = os.path.join(
            self._conf['m2ee']['app_base'], 'data', 'tmp', 'felixcache'
        )
        felix_template_file = os.path.join(
            self._runtime_path,
            'runtime',
            'felixconfig.properties.template'
        )
        if os.path.exists(felix_template_file):
            logger.debug("writing felix configuration template from %s "
                         "to %s" % (felix_template_file, felix_config_file))
            try:
                with open(felix_template_file) as f:
                    template = f.read()
            except IOError as e:
                raise M2EEException("felix configuration template could not be read: %s", e)
            try:
                render = template.format(
                    ProjectBundlesDir=project_bundles_path,
                    InstallDir=self._runtime_path,
                    FrameworkStorage=osgi_storage_path
                )
                with open(felix_config_file, 'w') as f:
                    f.write(render)
            except IOError as e:
                raise M2EEException("felix configuration file could not be written: %s", e)
        else:
            raise M2EEException("felix configuration template is not a readable file: %s" %
                                felix_template_file)

    def get_app_name(self):
        return self._conf['m2ee']['app_name']

    def get_app_base(self):
        return self._conf['m2ee']['app_base']

    def get_default_dotm2ee_directory(self):
        dotm2ee = os.path.join(pwd.getpwuid(os.getuid())[5], ".m2ee")
        if not os.path.isdir(dotm2ee):
            try:
                os.mkdir(dotm2ee)
            except OSError as e:
                logger.debug("Got %s: %s" % (type(e), e))
                import traceback
                logger.debug(traceback.format_exc())
                logger.critical("Directory %s does not exist, and cannot be "
                                "created!")
                logger.critical("If you do not want to use .m2ee in your home "
                                "directory, you have to specify pidfile, "
                                "munin -> config_cache in your configuration "
                                "file")
                sys.exit(1)

        return dotm2ee

    def get_symlink_mxclientsystem(self):
        return self._conf['m2ee'].get('symlink_mxclientsystem', True)

    def get_post_unpack_hook(self):
        return self._conf['m2ee'].get('post_unpack_hook', False)

    def get_public_webroot_path(self):
        return self._conf['mxruntime'].get('PublicWebrootPath',
                                           os.path.join(
                                               self._conf['m2ee']['app_base'],
                                               'web'))

    def get_real_mxclientsystem_path(self):
        if 'MxClientSystemPath' in self._conf['mxruntime']:
            return self._conf['mxruntime'].get('MxClientSystemPath')
        else:
            return os.path.join(
                self._runtime_path,
                'runtime',
                'mxclientsystem')

    def get_mimetypes(self):
        return self._conf['mimetypes']

    def all_systems_are_go(self):
        return self._all_systems_are_go

    def get_java_env(self):
        env = {}

        preserve_environment = self._conf['m2ee'].get('preserve_environment',
                                                      False)
        if preserve_environment is True:
            env = os.environ.copy()
        elif preserve_environment is False:
            pass
        elif type(preserve_environment) == list:
            for varname in preserve_environment:
                if varname in os.environ:
                    env[varname] = os.environ[varname]
                else:
                    logger.warn("preserve_environment variable %s is not "
                                "present in os.environ" % varname)
        else:
            logger.warn("preserve_environment is not a boolean or list")

        custom_environment = self._conf['m2ee'].get('custom_environment', {})
        if custom_environment is not None:
            if type(custom_environment) == dict:
                env.update(custom_environment)
            else:
                logger.warn("custom_environment option in m2ee section in "
                            "configuration is not a dictionary")

        env.update({
            'M2EE_ADMIN_PORT': str(self._conf['m2ee']['admin_port']),
            'M2EE_ADMIN_PASS': str(self._conf['m2ee']['admin_pass']),
        })
        if self.runtime_version >= 4.3:
            env.update({
                'M2EE_ADMIN_LISTEN_ADDRESSES': str(
                    self._conf['m2ee']['admin_listen_addresses']),
                'M2EE_RUNTIME_LISTEN_ADDRESSES': str(
                    self._conf['m2ee']['runtime_listen_addresses']),
            })
        env['M2EE_RUNTIME_PORT'] = str(self._conf['m2ee']['runtime_port'])
        if 'monitoring_pass' in self._conf['m2ee']:
            env['M2EE_MONITORING_PASS'] = str(
                self._conf['m2ee']['monitoring_pass'])

        if self.runtime_version >= 7:
            env['MX_INSTALL_PATH'] = self._runtime_path

        return env

    def get_java_cmd(self):
        """
        Build complete JVM startup command line
        """
        cmd = flatten(self._conf['m2ee'].get('javabin', 'java'))

        if 'javaopts' in self._conf['m2ee']:
            if isinstance(self._conf['m2ee']['javaopts'], list):
                cmd.extend(self._conf['m2ee']['javaopts'])
            else:
                logger.warn("javaopts option in m2ee section in configuration "
                            "is not a list")
        if self.runtime_version >= 7:
            cmd.extend([
                '-jar',
                os.path.join(self._runtime_path, 'runtime/launcher/runtimelauncher.jar'),
                self.get_app_base(),
            ])
        elif self._classpath:
            cmd.extend(['-cp', self._classpath])
            if self.runtime_version >= 5:
                cmd.append('-Dfelix.config.properties=file:%s'
                           % self.get_felix_config_file())
            cmd.append(self._get_appcontainer_mainclass())
        else:
            logger.critical("Unable to determine JVM startup parameters.")
            return None

        return cmd

    def get_admin_port(self):
        return self._conf['m2ee']['admin_port']

    def get_admin_pass(self):
        return self._conf['m2ee']['admin_pass']

    def get_runtime_port(self):
        return self._conf['m2ee']['runtime_port']

    def get_runtime_listen_addresses(self):
        return self._conf['m2ee'].get('runtime_listen_addresses', '')

    def get_pidfile(self):
        return self._conf['m2ee'].get('pidfile',
                                      os.path.join(
                                          self.get_default_dotm2ee_directory(),
                                          'm2ee.pid'))

    def get_logfile(self):
        return self._conf['m2ee'].get('logfile', None)

    def get_runtime_config(self):
        return self._conf['mxruntime']

    def get_logging_config(self):
        return self._conf['logging']

    def get_jetty_options(self):
        jetty_opts = copy.deepcopy(self._conf['m2ee'].get('jetty'))
        if jetty_opts is None:
            jetty_opts = {}
        return jetty_opts

    def get_munin_options(self):
        return self._conf['m2ee'].get('munin', {})

    def allow_destroy_db(self):
        return self._conf['m2ee'].get('allow_destroy_db', True)

    def is_using_postgresql(self):
        databasetype = self._conf['mxruntime'].get('DatabaseType', None)
        return (isinstance(databasetype, str) and
                databasetype.lower() == "postgresql")

    def get_pg_environment(self):
        if not self.is_using_postgresql():
            logger.warn("Only PostgreSQL databases are supported right now.")
        # rip additional :port from hostName, but allow occurrence of plain
        # ipv6 address between []-brackets (simply assume [ipv6::] when ']' is
        # found in string (also see JDBCDataStoreConfiguration in MxRuntime)
        host = self._conf['mxruntime']['DatabaseHost']
        port = "5432"
        ipv6end = host.rfind(']')
        lastcolon = host.rfind(':')
        if ipv6end != -1 and lastcolon > ipv6end:
            # "]" found and ":" exists after the "]"
            port = host[lastcolon + 1:]
            host = host[1:ipv6end]
        elif ipv6end != -1:
            # "]" found but no ":" exists after the "]"
            host = host[1:ipv6end]
        elif ipv6end == -1 and lastcolon != -1:
            # no "]" found and ":" exists, simply split on ":"
            port = host[lastcolon + 1:]
            host = host[:lastcolon]

        # TODO: sanity checks
        pg_env = {
            'PGHOST': host,
            'PGPORT': port,
            'PGUSER': self._conf['mxruntime']['DatabaseUserName'],
            'PGPASSWORD': self._conf['mxruntime']['DatabasePassword'],
            'PGDATABASE': self._conf['mxruntime']['DatabaseName'],
        }
        logger.trace("PostgreSQL environment variables: %s" % str(pg_env))
        return pg_env

    def get_psql_binary(self):
        return self._conf['mxnode'].get('psql', 'psql')

    def get_pg_dump_binary(self):
        return self._conf['mxnode'].get('pg_dump', 'pg_dump')

    def get_pg_restore_binary(self):
        return self._conf['mxnode'].get('pg_restore', 'pg_restore')

    def get_first_writable_mxjar_repo(self):
        repos = self._conf['mxnode']['mxjar_repo']
        logger.debug("Searching for writeable mxjar repos... in %s"
                     % repos)
        repos = [repo for repo in repos if os.access(repo, os.W_OK)]
        if len(repos) > 0:
            found = repos[0]
            logger.debug("Found writable mxjar location: %s" % found)
            return found
        else:
            logger.debug("No writable mxjar location found")
            return None

    def get_runtime_download_url(self, version):
        url = self._conf['mxnode'].get(
            'download_runtime_url',
            'https://download.mendix.com/runtimes/'
        )
        if url[-1] != '/':
            url += '/'
        url += 'mendix-%s.tar.gz' % version
        return url

    def get_database_dump_path(self):
        return self._conf['m2ee']['database_dump_path']

    def get_model_upload_path(self):
        return self._conf['m2ee']['model_upload_path']

    def get_runtime_version(self):
        return self.runtime_version

    def get_classpath(self):
        return self._classpath

    def _get_appcontainer_mainclass(self):
        if self.runtime_version // 3 or self.runtime_version // 4:
            return "com.mendix.m2ee.server.HttpAdminAppContainer"
        if self.runtime_version // 5 or self.runtime_version // 6:
            return "org.apache.felix.main.Main"
        raise Exception("Trying to determine appcontainer main class for "
                        "runtime version %s. Please report this as a bug." %
                        self.runtime_version)

    def _setup_classpath_runtime_binary(self):
        """
        Returns the location of the mendix runtime files and the
        java classpath or None if the classpath cannot be determined
        (i.e. the Mendix Runtime is not available on this system)
        """

        logger.debug("Running from binary distribution.")
        classpath = []

        if not self._runtime_path:
            logger.debug("runtime_path is empty, no classpath can be "
                         "determined")
            return []

        if self.runtime_version < 5:
            classpath.extend([
                os.path.join(self._runtime_path, 'server', '*'),
                os.path.join(self._runtime_path, 'server', 'lib', '*'),
                os.path.join(self._runtime_path, 'runtime', '*'),
                os.path.join(self._runtime_path, 'runtime', 'lib', '*'),
            ])
        elif self.runtime_version // 5 or self.runtime_version // 6:
            classpath.extend([
                os.path.join(self._runtime_path, 'runtime', 'felix', 'bin',
                             'felix.jar'),
                os.path.join(self._runtime_path, 'runtime', 'lib',
                             'com.mendix.xml-apis-1.4.1.jar')
            ])
        else:
            raise Exception("Trying to determine runtime classpath for runtime version %s. "
                            "Please report this as a bug." % self.runtime_version)

        return classpath

    def _setup_classpath_model(self):

        classpath = []

        if self.runtime_version < 5:
            # put model lib into classpath
            model_lib = os.path.join(
                self._conf['m2ee']['app_base'],
                'model',
                'lib'
            )
            if os.path.isdir(model_lib):
                # put all jars into classpath
                classpath.append(os.path.join(model_lib, 'userlib', '*'))
                # put all directories as themselves into classpath
                classpath.extend(
                    [os.path.join(model_lib, name)
                        for name in os.listdir(model_lib)
                        if os.path.isdir(os.path.join(model_lib, name))
                     ])
            else:
                logger.info("No current unpacked application model is available. "
                            "Use the unpack command to unpack a mendix deployment "
                            "archive from %s" % self._conf['m2ee']['model_upload_path'])

        return classpath

    def _lookup_runtime_version(self):
        logger.debug("Determining runtime version to be used...")
        if 'RuntimeVersion' not in self._model_metadata:
            return None
        logger.debug("MxRuntime version listed in model metadata: %s" %
                     self._model_metadata['RuntimeVersion'])
        return MXVersion(self._model_metadata['RuntimeVersion'])

    def lookup_in_mxjar_repo(self, dirname):
        logger.debug("Searching for %s in mxjar repo locations..." % dirname)
        path = None
        for repo in self._conf['mxnode']['mxjar_repo']:
            try_path = os.path.join(repo, dirname)
            if os.path.isdir(try_path):
                path = try_path
                logger.debug("Using: %s" % path)
                break

        return path

    def get_runtime_path(self):
        return self._runtime_path

    def get_constants(self):
        logger.debug("Merging constant definitions...")
        model_constants = {}
        for metadata_constant in self._model_metadata['Constants']:
            model_constants[metadata_constant['Name']] = metadata_constant['DefaultValue']
        yaml_constants = self._conf['mxruntime']['MicroflowConstants']
        constants_to_use = {}
        default_constants = {}
        for name, value in model_constants.items():
            if name not in yaml_constants:
                default_constants[name] = value
                constants_to_use[name] = value
        obsolete_constants = {}
        for name, value in yaml_constants.items():
            if name in model_constants:
                constants_to_use[name] = value
            else:
                obsolete_constants[name] = value
        logger.trace("Constants to send to runtime: %s" % constants_to_use)
        logger.trace("Constants with default values: %s" % default_constants)
        logger.trace("Obsolete constant definitions: %s" % obsolete_constants)
        return constants_to_use, default_constants, obsolete_constants

    def set_database_password(self, password):
        self._conf['mxruntime']['DatabasePassword'] = password

    def get_max_active_db_connections(self):
        return self._conf['mxruntime'].get('ConnectionPoolingMaxActive', 50)


def find_yaml_files():
    yaml_files = []
    if os.path.isfile("/etc/m2ee/m2ee.yaml"):
        yaml_files.append("/etc/m2ee/m2ee.yaml")

    homedir = pwd.getpwuid(os.getuid())[5]
    if os.path.isfile(os.path.join(homedir, ".m2ee/m2ee.yaml")):
        yaml_files.append(os.path.join(homedir, ".m2ee/m2ee.yaml"))
    return yaml_files


def read_yaml_files(yaml_files):
    config = defaultdict(dict)
    yaml_mtimes = {}

    for yaml_file in yaml_files:
        config, yaml_mtimes = load_yaml_file(yaml_file, config, yaml_mtimes)

    if 'include' in config:
        include = config['include']
        if isinstance(include, list):
            for include_file in include:
                config, yaml_mtimes = load_yaml_file(include_file, config, yaml_mtimes)
        else:
            logger.error("include present in config, but not a list, ignoring!")

    return (config, yaml_mtimes)


def load_yaml_file(yaml_file, config, yaml_mtimes):
    logger.debug("Loading configuration from %s" % yaml_file)
    try:
        with open(yaml_file) as f:
            additional_config = yaml.load(f)
        config = merge_config(config, additional_config)
        yaml_mtimes[yaml_file] = os.stat(yaml_file)[8]
    except Exception as e:
        logger.warn("Error reading configuration file %s: %s, ignoring..." % (yaml_file, e))
    return (config, yaml_mtimes)


def merge_config(initial_config, additional_config):
    result = copy.deepcopy(initial_config)
    if additional_config is None:
        return result
    additional_config = copy.deepcopy(additional_config)
    if initial_config is None:
        return additional_config

    for section in set(list(initial_config.keys()) + list(additional_config.keys())):
        if section in initial_config:
            if section in additional_config:
                if isinstance(additional_config[section], dict):
                    result[section] = merge_config(initial_config[section],
                                                   additional_config[section])
                elif isinstance(additional_config[section], list):
                    result[section] = (initial_config[section] +
                                       additional_config[section])
                else:
                    result[section] = additional_config[section]
        else:
            result[section] = additional_config[section]

    return result


def flatten(l):
    return [l] if not isinstance(l, list) else sum(map(flatten, l), [])


if __name__ == '__main__':
    config = M2EEConfig(sys.argv[1:])
    config.dump()
