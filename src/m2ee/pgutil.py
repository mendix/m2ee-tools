#
# Copyright (c) 2009-2012, Mendix bv
# All Rights Reserved.
#
# http://www.mendix.com/
#

import os
import subprocess
import time
from log import logger

class M2EEPgUtil:

    def __init__(self, config):
        self._config = config

    def dumpdb(self):

        pgenv = os.environ.copy()
        pgenv.update(self._config.get_pg_environment())
        pg_dump_location = self._config.get_pg_dump_location()
        
        db_dump_file_name = os.path.join(self._config.get_database_dump_path(),
                "%s_%s.backup" % (pgenv['PGDATABASE'], time.strftime("%Y%m%d_%H%M%S")))

        logger.info("Writing database dump to %s" % db_dump_file_name)
        cmd = (pg_dump_location, "-O", "-x", "-F", "c")
        proc = subprocess.Popen(cmd, env=pgenv, stdout=open(db_dump_file_name, 'w+'))
        proc.communicate()

    def restoredb(self, dump_name):
        if not self._config.allow_destroy_db():
            logger.error("Destructive database operations are turned off.")
            return

        pgenv = os.environ.copy()
        pgenv.update(self._config.get_pg_environment())
        pg_restore_location = self._config.get_pg_restore_location()

        answer = raw_input("This command will restore this dump into database %s. Continue? (y)es, (N)o? " % pgenv['PGDATABASE'])
        if answer != 'y':
            logger.info("Aborting!")
            return

        db_dump_file_name = os.path.join(self._config.get_database_dump_path(), dump_name)
        if not os.path.isfile(db_dump_file_name):
            logger.error("file %s does not exist: " % db_dump_file_name)
            return

        logger.debug("Restoring %s" % db_dump_file_name)
        cmd = (pg_restore_location, "-d", pgenv['PGDATABASE'], "-O", "-x", db_dump_file_name)
        proc = subprocess.Popen(cmd, env=pgenv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (stdout,stderr) = proc.communicate()

        if stderr != '':
            logger.error("An error occured while calling pg_restore: %s " % stderr)
            return

    def complete_restoredb(self, text):
        db_dump_path = self._config.get_database_dump_path()
        return [f for f in os.listdir(db_dump_path)
                if os.path.isfile(os.path.join(db_dump_path, f))
                and f.startswith(text)
                and f.endswith(".backup")]

    def emptydb(self):
        if not self._config.allow_destroy_db():
            logger.error("Destructive database operations are turned off.")
            return

        pgenv = os.environ.copy()
        pgenv.update(self._config.get_pg_environment())
        psql_location = self._config.get_psql_location()

        answer = raw_input("This command will drop all tables and sequences in database %s. Continue? (y)es, (N)o? " % pgenv['PGDATABASE'])
        if answer != 'y':
            print "Aborting!"
            return
        
        logger.info("Removing all tables...")
        # get list of drop table commands
        cmd = (psql_location, "-t", "-c",
            "SELECT 'DROP TABLE ' || n.nspname || '.' || c.relname || ' CASCADE;' FROM "
            "pg_catalog.pg_class AS c LEFT JOIN pg_catalog.pg_namespace AS n ON n.oid = "
            "c.relnamespace WHERE relkind = 'r' AND n.nspname NOT IN ('pg_catalog', "
            "'pg_toast') AND pg_catalog.pg_table_is_visible(c.oid)"
        )
        proc1 = subprocess.Popen(cmd, env=pgenv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (stdout,stderr) =  proc1.communicate()

        if stderr != '':
            logger.error("An error occured while calling psql: %s" % stderr)
            return
        
        stdin = stdout
        cmd = (psql_location,)
        proc2 = subprocess.Popen(cmd, env=pgenv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (stdout,stderr) = proc2.communicate(stdin)
        
        if stderr != '':
            logger.error("An error occured while calling psql: %s" % stderr)
            return

        logger.info("Removing all sequences...")
        # get list of drop sequence commands
        cmd = (psql_location, "-t", "-c",
            "SELECT 'DROP SEQUENCE ' || n.nspname || '.' || c.relname || ' CASCADE;' FROM "
            "pg_catalog.pg_class AS c LEFT JOIN pg_catalog.pg_namespace AS n ON n.oid = "
            "c.relnamespace WHERE relkind = 'S' AND n.nspname NOT IN ('pg_catalog', "
            "'pg_toast') AND pg_catalog.pg_table_is_visible(c.oid)"
        )
        proc1 = subprocess.Popen(cmd, env=pgenv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (stdout,stderr) =  proc1.communicate()

        if stderr != '':
            logger.error("An error occured while calling psql: %s" % stderr)
            return
        
        stdin = stdout
        cmd = (psql_location,)
        proc2 = subprocess.Popen(cmd, env=pgenv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (stdout,stderr) = proc2.communicate(stdin)
        
        if stderr != '':
            logger.error("An error occured while calling psql: %s" % stderr)
            return

    def psql(self):
        pgenv = os.environ.copy()
        pgenv.update(self._config.get_pg_environment())
        psql_location = self._config.get_psql_location()
        subprocess.call((psql_location,), env=pgenv)
