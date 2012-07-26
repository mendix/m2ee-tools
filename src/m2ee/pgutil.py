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

def dumpdb(pg_env, pg_dump_binary, database_dump_path):

    env = os.environ.copy()
    env.update(pg_env)
    
    db_dump_file_name = os.path.join(database_dump_path,
            "%s_%s.backup" % (env['PGDATABASE'], time.strftime("%Y%m%d_%H%M%S")))

    logger.info("Writing database dump to %s" % db_dump_file_name)
    cmd = (pg_dump_binary, "-O", "-x", "-F", "c")
    logger.trace("Executing %s" % str(cmd))
    proc = subprocess.Popen(cmd, env=env, stdout=open(db_dump_file_name, 'w+'))
    proc.communicate()

def restoredb(pg_env, pg_restore_binary, database_dump_path, dump_name):

    env = os.environ.copy()
    env.update(pg_env)

    answer = raw_input("This command will restore this dump into database %s. Continue? (y)es, (N)o? " % env['PGDATABASE'])
    if answer != 'y':
        logger.info("Aborting!")
        return

    db_dump_file_name = os.path.join(database_dump_path, dump_name)
    if not os.path.isfile(db_dump_file_name):
        logger.error("file %s does not exist: " % db_dump_file_name)
        return

    logger.debug("Restoring %s" % db_dump_file_name)
    cmd = (pg_restore_binary, "-d", env['PGDATABASE'], "-O", "-x", db_dump_file_name)
    logger.trace("Executing %s" % str(cmd))
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (stdout,stderr) = proc.communicate()

    if stderr != '':
        logger.error("An error occured while calling pg_restore: %s " % stderr)
        return

def complete_restoredb(database_dump_path,  text):
    return [f for f in os.listdir(database_dump_path)
            if os.path.isfile(os.path.join(database_dump_path, f))
            and f.startswith(text)
            and f.endswith(".backup")]

def emptydb(pg_env, psql_binary):

    env = os.environ.copy()
    env.update(pg_env)

    answer = raw_input("This command will drop all tables and sequences in database %s. Continue? (y)es, (N)o? " % env['PGDATABASE'])
    if answer != 'y':
        print "Aborting!"
        return
    
    logger.info("Removing all tables...")
    # get list of drop table commands
    cmd = (psql_binary, "-t", "-c",
        "SELECT 'DROP TABLE ' || n.nspname || '.' || c.relname || ' CASCADE;' FROM "
        "pg_catalog.pg_class AS c LEFT JOIN pg_catalog.pg_namespace AS n ON n.oid = "
        "c.relnamespace WHERE relkind = 'r' AND n.nspname NOT IN ('pg_catalog', "
        "'pg_toast') AND pg_catalog.pg_table_is_visible(c.oid)"
    )
    logger.trace("Executing %s, creating pipe for stdout,stderr" % str(cmd))
    proc1 = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (stdout,stderr) =  proc1.communicate()

    if stderr != '':
        logger.error("An error occured while calling psql: %s" % stderr)
        return
    
    stdin = stdout
    cmd = (psql_binary,)
    logger.trace("Piping stdout,stderr to %s" % str(cmd))
    proc2 = subprocess.Popen(cmd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (stdout,stderr) = proc2.communicate(stdin)
    
    if stderr != '':
        logger.error("An error occured while calling psql: %s" % stderr)
        return

    logger.info("Removing all sequences...")
    # get list of drop sequence commands
    cmd = (psql_binary, "-t", "-c",
        "SELECT 'DROP SEQUENCE ' || n.nspname || '.' || c.relname || ' CASCADE;' FROM "
        "pg_catalog.pg_class AS c LEFT JOIN pg_catalog.pg_namespace AS n ON n.oid = "
        "c.relnamespace WHERE relkind = 'S' AND n.nspname NOT IN ('pg_catalog', "
        "'pg_toast') AND pg_catalog.pg_table_is_visible(c.oid)"
    )
    logger.trace("Executing %s, creating pipe for stdout,stderr" % str(cmd))
    proc1 = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (stdout,stderr) =  proc1.communicate()

    if stderr != '':
        logger.error("An error occured while calling psql: %s" % stderr)
        return
    
    stdin = stdout
    cmd = (psql_binary,)
    logger.trace("Piping stdout,stderr to %s" % str(cmd))
    proc2 = subprocess.Popen(cmd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (stdout,stderr) = proc2.communicate(stdin)
    
    if stderr != '':
        logger.error("An error occured while calling psql: %s" % stderr)
        return

def psql(pg_env, psql_binary):
    env = os.environ.copy()
    env.update(pg_env)
    cmd = (psql_binary,)
    logger.trace("Executing %s" % str(cmd))
    subprocess.call(cmd, env=env)
