#
# Copyright (C) 2021 Mendix. All rights reserved.
#
import datetime
import hashlib
import json
import logging
import m2ee
import re
from m2ee.exceptions import M2EEException

import requests

from os import path
from time import mktime
from time import time
from zipfile import ZipFile
from zipfile import ZIP_DEFLATED

try:
    import psycopg2.sql
    import psycopg2.extras
except ImportError:
    # We need psycopg2.sql to build queries for database statistics. However,
    # if psycopg2 is not available, we can ignore it here, since the function
    # to open a connection in the pgutil module will already bail out before
    # actually reaching the code that uses this import.
    pass

logger = logging.getLogger(__name__)
usage_metrics_schema_version = "1.2"


def export_usage_metrics(m2):
    check_prerequisites(m2)

    logger.info("Begin exporting usage metrics at {}".format(datetime.datetime.now()))

    # trying to get server_id at the very beginning to
    # drop futher execution if Mendix app is not running
    # and server_id is unavailable
    server_id = m2.client.get_license_information()["license_id"]

    config = m2.config
    db_conn = m2ee.pgutil.open_pg_connection(config)
    logger.debug("Usage metering: connected to database")

    try:
        with prepare_db_cursor_for_usage_query(config, db_conn) as db_cursor:
            # starting export
            is_subscription_service_available = check_subscription_service_availability(config)
            if is_subscription_service_available:
                # export to Subscription Service directly if it is available
                # (for connected environments)
                logger.info("Exporting to the Subscription Service")
                export_to_subscription_service(config, db_cursor, server_id)
            else:
                logger.info("Exporting to file")
                # export to file (for disconnected environments)
                export_to_file(config, db_cursor, server_id)
    except psycopg2.Error as pe:
        raise M2EEException("Exporting usage metrics failed: {}".format(pe)) from pe
    finally:
        db_conn.close()
        logger.debug("Usage metering: database is disconnected")

    logger.info("Finished exporting usage metrics at {}".format(datetime.datetime.now()))


def check_prerequisites(m2):
    mendix_version = m2.config.get_runtime_version()
    # available only for Mendix versions from v7.5.0 to v9.6, from v9.6 it has
    # been replaced by runtime micrometer:
    # https://docs.mendix.com/releasenotes/studio-pro/9.6#custom-metrics
    if mendix_version < 7.5 or mendix_version >= 9.6:
        raise M2EEException(
            "export_usage_metrics is supported only for the Mendix "
            "versions from 7.5.0 to 9.6. From version 9.6 and above use Micrometer instead: "
            "https://docs.mendix.com/releasenotes/studio-pro/9.6#custom-metrics")

    if not m2.has_license():
        raise M2EEException(
            "Your application has no active license. "
            "You can activate your license with `activate_license` m2ee command if you "
            "already have a license key. Otherwise, please contact your Mendix account "
            "manager or Mendix Support for further instructions about on premise licensing. "
            "See https://docs.mendix.com/developerportal/deploy/unix-like")


def prepare_db_cursor_for_usage_query(config, db_conn):
    logger.debug("Begin to prepare usage metering query {}".format(datetime.datetime.now()))

    # the base query
    query = psycopg2.sql.SQL("""
        SELECT
            u.name,
            u.lastlogin,
            u.webserviceuser,
            u.blocked,
            u.active,
            u.isanonymous,
            ur.usertype
            {email}
        FROM system$user u
        LEFT JOIN system$userreportinfo_user ur_u ON u.id = ur_u.system$userid
        LEFT JOIN system$userreportinfo ur ON ur.id = ur_u.system$userreportinfoid
        {extra_joins}
        WHERE u.name IS NOT NULL
        ORDER BY u.id
    """)

    # looking for email entities
    email_table_and_columns = get_email_columns(config, db_conn)

    # preparing found email tables and columns to join the query as {email} and {extra_joins}
    email_part, joins_part = \
        convert_found_user_attributes_to_query_additions(email_table_and_columns)

    # combining final query
    query = query.format(
        email=email_part,
        extra_joins=joins_part
    )

    logger.trace("Constructed query: {}".format(query.as_string(db_conn)))

    # executing query via separate db cursor since we use batching here
    batch_cur = get_batch_db_cursor(config, db_conn)
    batch_cur.execute(query)

    logger.debug("Usage metering query is ready {}".format(datetime.datetime.now()))

    return batch_cur


def check_subscription_service_availability(config):
    url = config.get_metering_subscription_service_url()

    if not url:
        # no URL specified at all
        return False

    try:
        response = requests.post(url)
        if response.status_code == requests.codes.ok:
            logger.debug("Susbcription service at {} seems to be available!".format(url))
            return True
        logger.debug("Subscription service at {} is not available, status code: {}".format(
            url, response.status_code))
        return False
    except Exception as e:
        logger.debug("Subscription service at {} is not available: {}".format(url, e))


def export_to_subscription_service(config, db_cursor, server_id):
    # setting batch size if specified, otherwise default batch size will be used
    batch_size = config.get_metering_subscription_service_api_batch_size()
    # for incremental uploads and to prevent the same usage metrics processed
    # more than once
    created_at = str(datetime.datetime.now())

    # fetching query results in batches (psycopg does all the batching work implicitly)
    usage_metrics = []
    rows_processed = 1
    for usage_metric in db_cursor:
        metric_to_export = convert_data_for_export(usage_metric, server_id)
        usage_metrics.append(metric_to_export)
        if rows_processed % batch_size == 0:
            # submitting next batch data to the Subscription Service API
            send_to_subscription_service(config, server_id, usage_metrics, created_at)
            usage_metrics = []
        rows_processed += 1
    # submitting remaining data (in case of last batch is less then batch_size)
    if usage_metrics:
        send_to_subscription_service(config, server_id, usage_metrics, created_at)


def send_to_subscription_service(config, server_id, usage_metrics, created_at):
    headers = {
        'Content-Type': 'application/json',
        'Schema-Version': usage_metrics_schema_version
    }

    body = {}
    body["subscriptionSecret"] = server_id
    body["environmentName"] = ""
    body["projectID"] = config.get_project_id()
    body["created_at"] = created_at
    body["users"] = usage_metrics
    body = json.dumps(body)

    url = config.get_metering_subscription_service_url()
    subscription_service_timeout = config.get_metering_subscription_service_timeout()

    try:
        response = requests.post(
            url=url,
            data=body,
            headers=headers,
            timeout=subscription_service_timeout
        )
    except requests.exceptions.Timeout:
        message = "Subscription Service API does not respond. " \
                "Timeout reached after {} seconds.".format(subscription_service_timeout)
        logger.trace(message)
        raise M2EEException(message)
    except requests.exceptions.ConnectionError as ce:
        message = "Subscription Service API not available for requests: {}".format(ce)
        logger.trace(message)
        raise M2EEException(message)

    if response.status_code != requests.codes.ok:
        raise M2EEException("Subscription Service returned non OK http status code {}. "
                            "Headers: {} Body: {}".format(response.status_code, response.headers,
                                                          response.text))

    logger.trace("Subscription Service response: {}".format(response.text))
    response_json = response.json()

    if 'licensekey' in response_json:
        logger.debug("Usage metrics exported to Subscription Service at {}".format(
            datetime.datetime.now()))
    elif 'logmessages' in response_json:
        raise M2EEException("Subscription Service returned errors: {}".format(
            response_json['logmessages']))
    else:
        raise M2EEException("Unexpected error from Subscription Service, please report "
                            "this at Mendix Support.")


def export_to_file(config, db_cursor, server_id):
    # create file
    file_suffix = str(int(time()))
    output_file = path.join(config.get_metering_output_file_name() + "_" + file_suffix + ".json")

    with open(output_file, "w") as out_file:
        # dump usage metering data to file
        i = 1
        out_file.write("{\n")
        out_file.write('"subscriptionSecret": "{}",\n'.format(server_id))
        out_file.write('"environmentName": "",\n')
        out_file.write('"projectID": "{}",\n'.format(config.get_project_id()))
        # for incremental uploads and to prevent the same usage metrics processed more than once
        out_file.write('"timestamp": "{}",\n'.format(str(datetime.datetime.now())))
        out_file.write('"users": [\n')
        for usage_metric in db_cursor:
            export_data = convert_data_for_export(usage_metric, server_id, True)
            # no comma before the first element in JSON array
            if i > 1:
                out_file.write(",\n")
            i += 1
            # using json.dump() instead of json.dumps() and dump each row
            # separately here to reduce memory usage since json.dumps() could
            # consume a lot of memory for a large number of users (e.g. it
            # takes ~3Gb for 1 million users)
            json.dump(export_data, out_file, indent=4, sort_keys=True)
        out_file.write("\n]")
        out_file.write("\n}")

        logger.info("Usage metrics exported at {} to {}".format(
            datetime.datetime.now(), output_file))

    zip_file(output_file, file_suffix)


def convert_data_for_export(usage_metric, server_id, to_file=False):
    converted_data = {}

    converted_data["active"] = usage_metric.active
    converted_data["blocked"] = usage_metric.blocked
    # prefer email from the name field over the email field
    converted_data["emailDomain"] = get_hashed_email_domain(usage_metric.name, usage_metric.email)
    # isAnonymous needs to be kept null if null, so possible values here are: true|false|null
    converted_data["isAnonymous"] = usage_metric.isanonymous
    # lastlogin needs to be kept null if null, so possible values here are: <epoch_time>|null
    if usage_metric.lastlogin:
        converted_data["lastlogin"] = convert_datetime_to_epoch(usage_metric.lastlogin)
    else:
        converted_data["lastlogin"] = None
    converted_data["name"] = hash_data(usage_metric.name)
    converted_data["usertype"] = usage_metric.usertype
    converted_data["webserviceuser"] = usage_metric.webserviceuser

    if to_file:
        # fields that needs only in file
        converted_data["created_at"] = str(datetime.datetime.now())
        converted_data["schema_version"] = usage_metrics_schema_version
        converted_data["server_id"] = server_id

    return converted_data


def get_hashed_email_domain(name, email):
    # prefer email from the name field over the email field
    hashed_email_domain = extract_and_hash_domain_from_email(name)
    if not hashed_email_domain:
        hashed_email_domain = extract_and_hash_domain_from_email(email)
    return hashed_email_domain


def convert_datetime_to_epoch(lastlogin):
    # Convert datetime in epoch format
    lastlogin_string = str(lastlogin)
    parsed_datetime = datetime.datetime.strptime(lastlogin_string, "%Y-%m-%d %H:%M:%S.%f")
    parsed_datetime_tuple = parsed_datetime.timetuple()
    epoch = mktime(parsed_datetime_tuple)
    return int(epoch)


def get_email_columns(config, db_conn):
    # simple cursor
    with db_conn.cursor() as db_cursor:
        email_table_and_columns = {}
        user_specialization_tables = get_user_specialization_tables(db_cursor)

        # exit if no entities found
        if len(user_specialization_tables) == 0:
            return email_table_and_columns

        query = psycopg2.sql.SQL("""
            SELECT  table_name, column_name
            FROM    information_schema.columns
            WHERE   table_name IN ({table_names})
                    {columns_clause}
        """)

        columns_clause = psycopg2.sql.SQL("AND column_name LIKE '%%mail%%'")

        # getting user defined email columns if they are provided
        user_custom_email_columns = \
            get_user_custom_email_columns(config, user_specialization_tables)

        #  changing query if user defined email columns provided and valid
        if len(user_custom_email_columns) > 0:
            columns_clause = psycopg2.sql.SQL(
                "AND (column_name LIKE '%%mail%%' OR column_name IN ({user_custom_columns}))"
            ).format(
                user_custom_columns=psycopg2.sql.SQL(', ').join(
                    psycopg2.sql.Literal(column) for column in user_custom_email_columns
                )
            )

        user_specialization_tables = psycopg2.sql.SQL(', ').join(
            psycopg2.sql.Literal(table) for table in user_specialization_tables
        )

        # combining final query
        query = query.format(
            table_names=user_specialization_tables,
            columns_clause=columns_clause
        )

        logger.debug("Executing query: %s", query.as_string(db_cursor))

        db_cursor.execute(query)
        result = db_cursor.fetchall()

        for row in result:
            table = row[0].strip().lower()
            column = row[1].strip().lower()
            if table and column:
                email_table_and_columns[table] = column

    logger.debug("Probable tables and columns that may have an email address are: {}".format(
        email_table_and_columns))

    return email_table_and_columns


def convert_found_user_attributes_to_query_additions(table_email_columns):
    # exit if there are no user email tables found
    if not table_email_columns:
        # since email is mandatory field for the Subscription Service,
        # setting email value to empty if there is no email columns at all
        return psycopg2.sql.SQL(", '' as email "), psycopg2.sql.SQL('')

    # making 'email attribute' and 'joins' part of the query
    projection = []
    joins = []

    # iterate over the table_email_columns to form the CONCAT and JOIN part of the query
    for i, (table, column) in enumerate(table_email_columns.items()):
        mailfield_prefix = "mailfield_" + str(i)

        projection.append(psycopg2.sql.SQL("{mailfield}.{column}").format(
            mailfield=psycopg2.sql.Identifier(mailfield_prefix),
            column=psycopg2.sql.Identifier(column)
        ))

        joins.append(psycopg2.sql.SQL(
            "LEFT JOIN {table} {mailfield} on {mailfield}.id = u.id").format(
            table=psycopg2.sql.Identifier(table),
            mailfield=psycopg2.sql.Identifier(mailfield_prefix)
        ))

        email_part = psycopg2.sql.SQL(", CONCAT({}) as email").format(
            psycopg2.sql.SQL(', ').join(projection))
    joins_part = psycopg2.sql.SQL(' ').join(joins)

    return email_part, joins_part


def get_batch_db_cursor(config, conn):
    # separate db cursor to use batches
    batch_cur = conn.cursor(
        # Cursor name should be provided here to use server-side cursor and
        # optimize memory usage: Psycopg2 will load all of the query into
        # memory if the name isn’t specified for the cursor object even in case
        # of fetchone() or fetchmany() and batch processing used. If name is
        # specified then cursor will be created on the server side that allows
        # to avoid additional memory usage.
        name="m2ee_metering_cursor",
        cursor_factory=psycopg2.extras.NamedTupleCursor
    )

    # setting batch size if specified, otherwise default batch=2000 will be used
    batch_size = config.get_metering_db_query_batch_size()

    if batch_size:
        batch_cur.itersize = batch_size

    return batch_cur


def get_user_specialization_tables(db_cursor):
    query = "SELECT DISTINCT submetaobjectname FROM system$user;"

    logger.debug("Executing query: %s", query)

    db_cursor.execute(query)
    result = [r[0] for r in db_cursor.fetchall()]

    logger.debug("User specialization tables are: <%s>", result)

    user_specialization_tables = []
    for submetaobject in result:
        # ignore the None values and System.User table
        if submetaobject is not None and submetaobject != "System.User":
            # cast user attribute names to Postgres syntax
            submetaobject = submetaobject.strip().lower().replace('.', '$')
            # ignore empty rows
            if submetaobject:
                # checking if user provided attribute is valid SQL literal and
                # adding it to the result array
                user_specialization_tables.append(submetaobject)

    return user_specialization_tables


# valid form is e.g. Module1.Entity1.Attribute1, or Module2.Entity2.Attribute2
# PostgreSQL rules also considered:
# https://www.postgresql.org/docs/current/sql-syntax-lexical.html#SQL-SYNTAX-IDENTIFIERS
re_validation_pattern = re.compile(r'^[a-zA-Z_]\w+\.[a-zA-Z_]\w+\.[a-zA-Z_]\w+$')


def get_user_custom_email_columns(config, user_specialization_tables):
    usage_metrics_email_fields = config.get_metering_email_fields()

    # exit if custom email fields are not provided
    if not usage_metrics_email_fields:
        return []

    invalid_fields = []

    # extract column names
    columnNames = []
    for field in usage_metrics_email_fields:
        if re.match(re_validation_pattern, field) is None:
            invalid_fields.append(field)
            continue

        separatorPosition = field.rindex(".")

        table = field[:separatorPosition]
        table = table.replace(".", "$").lower()

        column = field[separatorPosition+1:]

        # user custom attributes must be specializations of 'System.User'
        if table not in user_specialization_tables:
            invalid_fields.append(field)
            continue

        columnNames.append(column)

    if len(invalid_fields) > 0:
        raise M2EEException(
            "The following field names specified in the "
            "configuration of metering email fields are invalid, don't exist "
            "in the database or are not a 'System.User' specialization: {}".format(
                '; '.join(invalid_fields))
        )

    return columnNames


def extract_and_hash_domain_from_email(email):
    if not isinstance(email, str):
        return ""

    if not email:
        return ""

    domain = ""
    if email.find("@") != -1:
        domain = str(email).split("@")[1]

    if len(domain) >= 2:
        return hash_data(domain)
    else:
        return ""


def hash_data(name):
    salt = [53, 14, 215, 17, 147, 90, 22, 81, 48, 249, 140, 146, 201, 247, 182, 18, 218, 242, 114,
            5, 255, 202, 227, 242, 126, 235, 162, 38, 52, 150, 95, 193]
    salt_byte_array = bytes(salt)

    encoded_name = name.encode()
    byte_array = bytearray(encoded_name)

    h = hashlib.sha256()
    h.update(salt_byte_array)
    h.update(byte_array)

    return h.hexdigest()


def zip_file(file_path, file_suffix):
    archive_name = 'mendix_usage_metrics_' + file_suffix + '.zip'
    with ZipFile(archive_name, 'w', ZIP_DEFLATED) as zip_archive:
        zip_archive.write(file_path)
