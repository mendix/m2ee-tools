#
# Copyright (c) 2009-2012, Mendix bv
# All Rights Reserved.
#
# http://www.mendix.com/
#

import yaml
import os, sys, pwd
import re
import codecs
import subprocess
import simplejson
from log import logger
try:
    import sqlite3
    python_sqlite3 = True
except ImportError:
    # python 2.4, fall back to calling sqlite3 binary
    logger.debug("import sqlite3 failed, trying to use external sqlite3 binary")
    python_sqlite3 = False

class M2EEConfig:

    def __init__(self, yamlfiles=None):

        self._mtimes = {}

        self._conf = {}
        self._conf['mxnode'] = {}
        self._conf['m2ee'] = {}
        self._conf['mimetypes'] = {}
        self._conf['logging'] = []
        self._conf['mxruntime'] = {}
        self._conf['custom'] = {}

        if yamlfiles == None:
            yamlfiles = []
            # don't add deprecated m2eerc-file if yaml is present
            # (if both exist, probably one is a symlink to the other...)
            if os.path.isfile("/etc/m2ee/m2ee.yaml"):
                yamlfiles.append("/etc/m2ee/m2ee.yaml")
            elif os.path.isfile("/etc/m2ee/m2eerc"):
                yamlfiles.append("/etc/m2ee/m2eerc")

            homedir = pwd.getpwuid(os.getuid())[5]
            if os.path.isfile(os.path.join(homedir, ".m2ee/m2ee.yaml")):
                yamlfiles.append(os.path.join(homedir, ".m2ee/m2ee.yaml"))
            elif os.path.isfile(os.path.join(homedir, ".m2eerc")):
                yamlfiles.append(os.path.join(homedir, ".m2eerc"))

        for yamlfile in yamlfiles:
            self._load_config(yamlfile)

        # raises exception when important config is missing
        # also update basepath in mxruntime config
        self._check_config()

        # 3.0: application information (e.g. runtime version)
        # if this file does not exist (i.e. < 3.0) try_load_json returns {}
        self._model_metadata = self._try_load_json(os.path.join(self._conf['m2ee']['app_base'],'model','metadata.json'))
        # 3.0: config.json "contains the configuration settings of the active configuration (in the Modeler) at the time of deployment."
        # It also contains default values for microflow constants. D/T configuration is not stored in the mdp anymore, so for D/T
        # we need to insert it into the configuration we read from yaml (yay!)
        # { "Configuration": { "key": "value", ... }, "Constants": { "Module.Constant": "value", ... } }
        self._model_config = self._try_load_json(os.path.join(self._conf['m2ee']['app_base'],'model','config.json'))

        # Dirty hack to tell if we're on 2.5 or not
        self._dirty_hack_is_25 = len(self._model_metadata) == 0

        # look up MxRuntime version
        self._runtime_version = self._lookup_runtime_version()

        # if running from binary distribution, try to find where m2ee/runtime jars live
        if not self._conf['mxnode'].get('run_from_source', False):
            self._mxjar_path = self._lookup_mxjar_path()

        # 3.0: appcontainer information (e.g. M2EE main class name)
        self._appcontainer_environment = self._load_appcontainer_environment()

        # search for server files and build classpath
        self._classpath = self._setup_classpath()

    def _try_load_json(self, jsonfile):
        logger.debug("Loading json configuration from %s" % jsonfile)
        fd = None
        try:
            fd = open(jsonfile)
        except Exception, e:
            logger.debug("Error reading configuration file %s: %s; ignoring..." % (jsonfile, e))
            return {}

        config = None
        try:
            config = simplejson.load(fd)
        except Exception, e:
            logger.error("Error parsing configuration file %s: %s" % (jsonfile, e))
            return {}

        logger.trace("contents read from %s: %s" % (jsonfile, config))
        return config

    def mtime_changed(self):
        for yamlfile, mtime in self._mtimes.iteritems():
            if os.stat(yamlfile)[8] != mtime:
                return True
        return False

    def dump(self):
        print yaml.dump(self._conf)

    def _load_config(self, yamlfile):
        logger.debug("Loading configuration from %s" % yamlfile)
        fd = None
        try:
            fd = open(yamlfile)
        except Exception, e:
            logger.error("Error reading configuration file %s, ignoring..." % yamlfile)
            return

        config = None
        try:
            config = yaml.load(fd)
        except Exception, e:
            logger.error("Error parsing configuration file %s: %s" % (yamlfile, e))
            return

        # merge configuration, new replaces old when colliding
        for section in ['mxnode','m2ee','mimetypes','mxruntime','custom']:
            if section in config and type(config[section]) == dict:
                self._conf[section].update(config[section])
        for section in ['logging']:
            if section in config and type(config[section]) == list:
                self._conf[section].extend(config[section])
        
        self._mtimes[yamlfile] = os.stat(yamlfile)[8] # st_mtime

    def _check_config(self):
        # TODO: better exceptions

        # mxnode
        if self._conf['mxnode'].get('run_from_source', False):
            if not self._conf['mxnode'].get('source_workspace', None):
                logger.critical("Run from source was selected, but source_workspace is not specified!")
                sys.exit(1)
            if not self._conf['mxnode'].get('source_projects', None):
                logger.critical("Run from source was selected, but source_projects is not specified!")
                sys.exit(1)
        else:
            if not self._conf['mxnode'].get('mxjar_repo', None):
                logger.critical("mxnode/mxjar_repo is not specified!")
                sys.exit(1)
            # ensure mxjar_repo is a list, multiple locations are allowed for searching
            if not type(self._conf['mxnode']['mxjar_repo']) == list:
                self._conf['mxnode']['mxjar_repo'] = [self._conf['mxnode']['mxjar_repo']]

        # m2ee
        for option in ['app_name','app_base','admin_port','admin_pass','runtime_port','pidfile']:
            if not self._conf['m2ee'].get(option, None):
                logger.critical("Option %s in configuration section m2ee is not defined!" % option)
                sys.exit(1)

        # check some locations for existance and permissions
        basepath = self._conf['m2ee']['app_base']
        if not os.path.exists(basepath):
            logger.critical("Application base directory %s does not exist!" % basepath)
            sys.exit(1)

        self._conf['mxruntime'].setdefault('BasePath', self._conf['m2ee']['app_base'])

        self.fix_permissions()

        # database_dump_path
        if not 'database_dump_path' in self._conf['m2ee']:
            self._conf['m2ee']['database_dump_path'] = os.path.join(self._conf['m2ee']['app_base'], 'data', 'database')
        if not os.path.isdir(self._conf['m2ee']['database_dump_path']):
            logger.warn("Database dump path %s is not a directory" % self._conf['m2ee']['database_dump_path'])
        # model_upload_path
        if not 'model_upload_path' in self._conf['m2ee']:
            self._conf['m2ee']['model_upload_path'] = os.path.join(self._conf['m2ee']['app_base'], 'data', 'model-upload')
        if not os.path.isdir(self._conf['m2ee']['model_upload_path']):
            logger.warn("Model upload path %s is not a directory" % self._conf['m2ee']['model_upload_path'])

    def fix_permissions(self):
        basepath = self._conf['m2ee']['app_base']
        for dir, mode in {"model":0700, "web":0755, "data":0700}.iteritems():
            fullpath = os.path.join(basepath, dir)
            if not os.path.exists(fullpath):
                logger.critical("Directory %s does not exist!" % fullpath)
                sys.exit(1)
            # TODO: detect permissions and tell user if changing is needed
            os.chmod(fullpath, mode)

    def get_app_name(self):
        return self._conf['m2ee']['app_name']

    def get_app_base(self):
        return self._conf['m2ee']['app_base']

    def get_symlink_mxclientsystem(self):
        return self._conf['m2ee'].get('symlink_mxclientsystem', False)

    def get_post_unpack_hook(self):
        return self._conf['m2ee'].get('post_unpack_hook', False)

    def get_public_webroot_path(self):
        return self._conf['mxruntime'].get('PublicWebrootPath', os.path.join(self._conf['m2ee']['app_base'], 'web'))

    def get_real_mxclientsystem_path(self):
        if 'MxClientSystemPath' in self._conf['mxruntime']:
            return self._conf['mxruntime'].get('MxClientSystemPath')
        else:
            return os.path.join(self._mxjar_path, 'runtime', 'mxclientsystem')

    def get_mimetypes(self):
        return self._conf['mimetypes']

    def get_java_env(self):
        env = {}

        preserve_environment = self._conf['m2ee'].get('preserve_environment', False)
        if preserve_environment == True:
            env = os.environ.copy()
        elif preserve_environment == False:
            pass
        elif type(preserve_environment) == list:
            for varname in preserve_environment:
                if varname in os.environ:
                    env[varname] = os.environ[varname]
                else:
                    logger.warn("preserve_environment variable %s is not present in os.environ" % varname)
        else:
            logger.warn("preserve_environment is not a boolean or list")

        custom_environment = self._conf['m2ee'].get('custom_environment', {})
        if custom_environment != None:
            if type(custom_environment) == dict:
                env.update(custom_environment)
            else:
                logger.warn("custom_environment option in m2ee section in configuration is not a dictionary")

        env.update({
            'M2EE_ADMIN_PORT':str(self._conf['m2ee']['admin_port']),
            'M2EE_ADMIN_PASS':str(self._conf['m2ee']['admin_pass']),
            'M2EE_RUNTIME_PORT':str(self._conf['m2ee']['runtime_port']),
        })
        if 'monitoring_pass' in self._conf['m2ee']:
            env['M2EE_MONITORING_PASS'] = str(self._conf['m2ee']['monitoring_pass'])
        if 'runtime_blocking_connector' in self._conf['m2ee']:
            env['M2EE_RUNTIME_BLOCKING_CONNECTOR'] = str(self._conf['m2ee']['runtime_blocking_connector'])
        return env

    def get_java_opts(self):
        if 'javaopts' in self._conf['m2ee']:
            if type(self._conf['m2ee']['javaopts'] == list):
                return self._conf['m2ee']['javaopts']
            else:
                logger.warn("javaopts option in m2ee section in configuration is not a list")
        return None

    def get_admin_port(self):
        return self._conf['m2ee']['admin_port']

    def get_admin_pass(self):
        return self._conf['m2ee']['admin_pass']

    def get_pidfile(self):
        return self._conf['m2ee']['pidfile']

    def get_logfile(self):
        return self._conf['m2ee'].get('logfile', None)

    def get_runtime_config(self):
        if self._dirty_hack_is_25:
            return self._conf['mxruntime']

        # also... 3.0
        config = {}
        mfconstants = {}
        # if not in production seed config from config.json
        if not self.get_dtap_mode()[0] in ('A','P'):
            if 'Configuration' in self._model_config:
                config = self._model_config['Configuration']
            # read mf defaults/development mix from config.json
            if 'Constants' in self._model_config:
                mfconstants = self._model_config['Constants']
        # custom yaml section can override defaults
        mfconstants.update(self._conf['custom'])
        # 'MicroflowConstants' from runtime yaml section can override default/custom
        mxruntime_mfconstants = self._conf['mxruntime'].get('MicroflowConstants',{})
        if mxruntime_mfconstants: # can still be None!
            mfconstants.update(mxruntime_mfconstants)

        # merge all yaml runtime settings into config
        config.update(self._conf['mxruntime'])
        # replace 'MicroflowConstants' with mfconstants we figured out before to prevent dict-deepmerge-problems
        config['MicroflowConstants'] = mfconstants

        return config

    def get_custom_config(self):
        # 2.5 uses update_custom_configuration to send mfconstants to the runtime,
        #     which are only read from the custom yaml section
        # 3.0 puts them as a dict into 'MicroflowConstants' in update_configuration itself, see above
        if self._dirty_hack_is_25:
            return self._conf['custom']
        return None

    def get_logging_config(self):
        return self._conf['logging']

    def get_jetty_options(self):
        return self._conf['m2ee'].get('jetty', None)

    def get_munin_options(self):
        return self._conf['m2ee'].get('munin', None)

    def get_dtap_mode(self):
        # option is mandatory, fail if not present
        return self._conf['mxruntime']['DTAPMode']

    def allow_destroy_db(self):
        return self._conf['m2ee'].get('allow_destroy_db', False)

    def is_using_postgresql(self):
        return self._conf['mxruntime'].get('DatabaseType', None) == "PostgreSQL"

    def get_pg_environment(self):
        if not self.is_using_postgresql():
            logger.warn("Only PostgreSQL databases are supported right now.")
        # rip additional :port from hostName, but allow occurrence of plain ipv6 address
        # between []-brackets (simply assume [ipv6::] when ']' is found in string)
        # (also see JDBCDataStoreConfiguration in MxRuntime)
        host = self._conf['mxruntime']['DatabaseHost']
        port = "5432"
        ipv6end = host.rfind(']')
        lastcolon = host.rfind(':')
        if ipv6end != -1 and lastcolon > ipv6end:
            # "]" found and ":" exists after the "]"
            port = host[lastcolon+1:]
            host = host[1:ipv6end]
        elif ipv6end != -1:
            # "]" found but no ":" exists after the "]"
            host = host[1:ipv6end]
        elif ipv6end == -1 and lastcolon != -1:
            # no "]" found and ":" exists, simply split on ":"
            port = host[lastcolon+1:]
            host = host[:lastcolon]

        # TODO: sanity checks
        return {
            'PGHOST': host,
            'PGPORT': port,
            'PGUSER': self._conf['mxruntime']['DatabaseUserName'],
            'PGPASSWORD': self._conf['mxruntime']['DatabasePassword'],
            'PGDATABASE': self._conf['mxruntime']['DatabaseName'],
        }

    def get_psql_location(self):
        return self._conf['mxnode'].get('psql', 'psql')

    def get_pg_dump_location(self):
        return self._conf['mxnode'].get('pg_dump', 'pg_dump')

    def get_pg_restore_location(self):
        return self._conf['mxnode'].get('pg_restore', 'pg_restore')

    def get_database_dump_path(self):
        return self._conf['m2ee']['database_dump_path']

    def get_model_upload_path(self):
        return self._conf['m2ee']['model_upload_path']

    def get_runtime_version(self):
        return self._runtime_version

    def get_classpath(self):
        return self._classpath

    def get_appcontainer_mainclass(self):
        # 2.5
        if not 'version' in self._appcontainer_environment:
            return "com.mendix.m2ee.server.M2EE"
        # 3.0
        # TODO: implement version-handling
        return "com.mendix.m2ee.server.HttpAdminAppContainer"

    def _setup_classpath(self):
        """Returns the location of the mendix runtime files and the 
        java classpath or None if the classpath cannot be determined
        (i.e. the Mendix Runtime is not available on this system)"""

        classpath = []

        # when running from source, grab eclipse projects:
        if self._conf['mxnode'].get('run_from_source', False):
            logger.debug("Running from source.")

            wsp = self._conf['mxnode']['source_workspace']
            for proj in self._conf['mxnode']['source_projects']:
                classpath.append(os.path.join(wsp, proj, 'bin'))
                libdir = os.path.join(wsp, proj, 'lib')
                if os.path.isdir(libdir):
                    classpath.append(os.path.join(libdir, '*'))

        else:
            logger.debug("Running from binary distribution.")

            if not self._mxjar_path:
                logger.debug("mxjar_path is empty, no classpath can be determined")
                return None

            # TODO: do something with self._appcontainer_environment/version

            classpath.extend([
                os.path.join(self._mxjar_path,'server','*'),
                os.path.join(self._mxjar_path,'server','lib','*'),
                os.path.join(self._mxjar_path,'runtime','*'),
                os.path.join(self._mxjar_path,'runtime','lib','*'),
            ])

            # XXX
            if not 'RuntimePath' in self._conf['mxruntime']:
                self._conf['mxruntime']['RuntimePath'] = os.path.join(self._mxjar_path,'runtime')

        # put model lib into classpath
        model_lib = os.path.join(self._conf['m2ee']['app_base'],'model','lib')
        if os.path.isdir(model_lib):
            # put all jars into classpath
            classpath.append(os.path.join(model_lib, 'userlib', '*'))
            # put all directories as themselves into classpath
            classpath.extend(
            [os.path.join(model_lib, name)
             for name in os.listdir(model_lib)
             if os.path.isdir(os.path.join(model_lib, name))])
        else:
            logger.warn("model has no lib dir?")
        
        txtclasspath = ":".join(classpath)
        logger.debug("Using classpath: %s" % txtclasspath)
        return txtclasspath

    def _lookup_runtime_version(self):
        # force to a specific version
        if self._conf['m2ee'].get('runtime_version', None):
            return self._conf['m2ee']['runtime_version']

        # 3.0 has runtime version in metadata.json
        if 'RuntimeVersion' in self._model_metadata:
            return self._model_metadata['RuntimeVersion']

        # else, 2.5: try to read from model.mdp using sqlite
        model_mdp = os.path.join(self._conf['m2ee']['app_base'],'model','model.mdp')
        if not os.path.isfile(model_mdp):
            logger.warn("%s is not a file!" % model_mdp)
            return None
        version = None
        if python_sqlite3:
            try:
                conn = sqlite3.connect(model_mdp)
                c = conn.cursor()
                c.execute('SELECT _ProductVersion FROM _MetaData LIMIT 1;')
                version = c.fetchone()[0]
                c.close()
                conn.close()
            except sqlite3.Error, e:
                logger.error("An error occured while trying to read mendix version number from model.mdp: %s" % e)
                return None
        else:
            cmd = ("sqlite3", model_mdp, "SELECT _ProductVersion FROM _MetaData LIMIT 1;")
            proc = None
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except OSError, ose:
                if ose.errno == 2:
                    logger.error("sqlite3 binary not found, unable to read mendix version number from model.mdp")
                else:
                    logger.error("An error occured while trying to read mendix version number from model.mdp: %s" % ose)
                return None

            (stdout,stderr) = proc.communicate()

            if proc.returncode != 0:
                logger.error("An error occured while trying to read mendix version number from model.mdp:")
                if stdout != '':
                    logger.error(stdout)
                if stderr != '':
                    logger.error(stderr)
                return None

            version = stdout.strip()

        # hack: force convert sqlite string to ascii, this prevents syslog from stumbling over it
        # because a BOM will appear which messes up syslog
        # <U+FEFF><183>m2ee: (bofht) DEBUG - MxRuntime version listed in application model file: 2.5.3
        # also see http://en.wikipedia.org/wiki/Byte_order_mark
        version = version.encode('ascii', 'ignore')
        # TODO: is this only syslog cosmetics, or does splitting syslog into files based on progname
        # break here? needs a bit of testing...

        if not re.match(r'^[\w.-]+$', version): # non-release build
            logger.error("Invalid version number in model.mdp: %s (not a release build?)" % version)
            return None

        logger.debug("MxRuntime version listed in application model file: %s" % version)

        return version

    def _lookup_mxjar_path(self):
        if self._runtime_version == None:
            # this probably means reading version information from the modeler file failed
            logger.debug("Unable to look up mendix runtime files because product version is unknown.")
            return None # fail

        # else, search for binary distributions in mxjar_repo
        logger.debug("Searching for Mendix %s in mxjar repo locations..." % self._runtime_version)
        mxjar_path = None
        for repo in self._conf['mxnode']['mxjar_repo']:
            try_path = os.path.join(repo, self._runtime_version)
            if os.path.isdir(try_path):
                mxjar_path = try_path
        if mxjar_path == None:
            logger.warn("Mendix Runtime not found for version %s" % self._runtime_version)
            return None
        
        logger.debug("...using %s" % mxjar_path)
        return mxjar_path

    def _load_appcontainer_environment(self):
        # if running from source, search in workspace folder
        if self._conf['mxnode'].get('run_from_source', False):
            return self._try_load_json(os.path.join(self._conf['mxnode']['source_workspace'], 'environment.json'))

        # else if version is known, search in mxjar_path
        if self._mxjar_path:
            return self._try_load_json(os.path.join(self._mxjar_path, 'environment.json'))

        # else, nothing
        return {}

    def dirty_hack_is_25(self):
        return self._dirty_hack_is_25

if __name__ == '__main__':
    import sys
    config = M2EEConfig(sys.argv[1:])
    config.dump()

