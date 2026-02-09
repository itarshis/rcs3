# All DB operation functions and queries
# Import 3rd party modules
import logging
import pymysql
import os

# Configure logging
log_level = os.environ['log_level'] if 'log_level' in os.environ else "INFO"
logger = logging.getLogger()
logger.setLevel(log_level)

# A single structure to store all relevant queries
queries = {
  "insertNewCBAccountRecord": {
    "name": "insert-new-cb-account-record",
    "text": "INSERT INTO cb_account_info (cbid, ucd_account_num, account_name, ucd_budget_auth, sn_request_id, account_cloud, account_email, account_primary_admin, account_poc, account_status, account_est_spend, account_role, ucd_data_protection_level, ucd_data_availability_level, data_types, account_date_created) \
            VALUES (%(cbid)s, %(ucd_account_num)s, %(account_name)s, %(ucd_budget_auth)s, %(sn_request_id)s, %(account_cloud)s, %(account_email)s, %(account_primary_admin)s, %(account_poc)s, %(account_status)s, %(account_est_spend)s, %(account_role)s, %(ucd_data_protection_level)s, %(ucd_data_availability_level)s, %(data_types)s, %(account_date_created)s)"
  },
  "selectCBAccountRecord": {
    "name": "select-cb-account-record",
    "text": "SELECT * FROM cb_account_info WHERE cbid = %(cbid)s"
  },
  "updateCBAccountRecord": {
    "name": "update-cb-account-record",
    "update_queries": {
        "account_billing_poc": "UPDATE cb_account_info SET account_billing_poc = %(column_value)s WHERE cbid = %(cbid)s",
        "account_technical_poc": "UPDATE cb_account_info SET account_technical_poc = %(column_value)s WHERE cbid = %(cbid)s",
        "estimated_spend": "UPDATE cb_account_info SET account_est_spend = %(column_value)s WHERE cbid = %(cbid)s",
        "account_poc": "UPDATE cb_account_info SET account_poc = %(column_value)s WHERE cbid = %(cbid)s",
        "account_status": "UPDATE cb_account_info SET account_status = %(column_value)s WHERE cbid = %(cbid)s",
        "account_id": "UPDATE cb_account_info SET account_id = %(column_value)s WHERE cbid = %(cbid)s",
        "is_test": "UPDATE cb_account_info SET is_test = %(column_value)s WHERE cbid = %(cbid)s",
        "cb_new_account": "UPDATE cb_account_info SET cb_new_account = %(column_value)s WHERE cbid = %(cbid)s",
        "account_email": "UPDATE cb_account_info SET account_email = %(column_value)s WHERE cbid = %(cbid)s"
    }
  },
  "selectCBDuplicateCheck": {
    "name": "select-cb-duplicate-check",
    "text": "SELECT cbid FROM cb_account_info WHERE account_id = %(account_id)s && account_cloud = %(account_cloud)s"
  },
  "selectRecordsByStatus": {
    "name": "select-records-by-status",
    "text": "SELECT * FROM cb_account_info WHERE account_status = %(status)s"
  },
  "deleteCBRecord": {
    "name": "delete-cb-record",
    "text": "DELETE FROM cb_account_info WHERE cbid = %(cbid)s"
  }
}

# Generalized database interaction functions

def database_connect(db_host, db_user, db_pass, db_name, db_charset):
    con = pymysql.connect(
        host = db_host,
        user = db_user,
        password = db_pass,
        db = db_name,
        charset = db_charset,
        cursorclass = pymysql.cursors.DictCursor,
        autocommit = True
        )
    return con

def update_cb_record(cbid, column_name, column_value, db_con):
    update_cursor = db_con.cursor()
    update_queries = queries['updateCBAccountRecord']['update_queries']
    if column_name in update_queries:
        query = update_queries[column_name]
        try:
            update_cursor.execute(query, {"column_value": column_value, "cbid": cbid})
        except pymysql.InternalError as error:
            logger.error(error)
            raise
        else:
            return "SUCCESS"
    else:
        logger.warn("Column name" + column_name + "cannot be updated. No corresponding query found.")
        return "WARN"

def get_cb_record(cbid, db_con):
    select_cursor = db_con.cursor()
    select_query = queries['selectCBAccountRecord']['text']
    try:
        select_result = select_cursor.execute(select_query, {"cbid": cbid})
    except pymysql.InternalError as error:
        logger.error(error)
        raise
    else:
        if select_result > 1:
            raise error.ServerError("CB Database has more than one entry for %s. Please check DB to resolve conflict." % cbid)
        elif select_result == 0:
            raise error.ServerError("No CB DB entry found for %s. Please check to ensure input is correct." % cbid)
        elif select_result == 1:
            for item in select_cursor:
                return item

def get_account_cbid(account_id, db_con):
    select_cursor = db_con.cursor()
    select_query = queries['selectCBDuplicateCheck']['text']
    try:
        select_result = select_cursor.execute(select_query, {"account_id": account_id, "account_cloud": 'aws'})
    except pymysql.InternalError as error:
        logger.error(error)
        raise
    else:
        if select_result > 1:
            raise error.ServerError("CB Database has more than one entry for %s. Please check DB to resolve conflict." % account_id)
        elif select_result == 0:
            raise error.ServerError("No CB DB entry found for %s. Please check to ensure input is correct." % account_id)
        elif select_result == 1:
            for item in select_cursor:
                return item
