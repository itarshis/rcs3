# Import 3rd party modules needed for the app

import datetime
import logging
import random
import boto3
import time
import os
import re

# Import custom modules modules for this app
import ddb

# Record runtime
now = datetime.datetime.now()
timestring = datetime.datetime.utcnow().strftime("%y%m%d%H%M%S")

# Configure logging
log_level = os.environ['log_level'] if 'log_level' in os.environ else "INFO"
logger = logging.getLogger()
logger.setLevel(log_level)

# Our handler function
def handler(event, context):
    try:
        cbid = event['uuid']
        if('test_error' in event):
            time.sleep(30)
            if (event['test_error'] == "FSSO"):
                error_state = "ACCT_SSO_CFG_ERROR"
            elif (event['test_error'] == "FACCT"):
                error_state = "ACCOUNT_FAILED"
            elif (event['test_error'] == "FADFS"):
                error_state = "ACCT_ADFS_CFG_ERROR"
            elif (event['test_error'] == "FROLE"):
                error_state = "ACCT_ROLE_CFG_ERROR"
            elif (event['test_error'] == "FNAME"):
                error_state = "ACCT_ALIAS_ERROR"
            else:
                error_state = "ACCOUNT_FAILED"
            ddb.updateAccountRecord(cbid, "account_status", error_state)
            logger.info("Updated %s account_status attribute to %s" % (cbid, event['test_error']))
            return "DONE"
        time.sleep(5) 
        ddb.updateAccountRecord(cbid, "account_status", "PENDING")
        ddb.updateAccountRecord(cbid, 'is_test', 1)
        time.sleep(60)
        account_id = "%0.12d" % random.randint(0, 999999999999)
        ddb.updateAccountRecord(cbid, "account_id", account_id)
        ddb.updateAccountRecord(cbid, "account_status", "DEPLOYED")
        time.sleep(10)
        ddb.updateAccountRecord(cbid, "account_status", "SSO_READY")
        time.sleep(120)
        ddb.updateAccountRecord(cbid, "account_status", "COMPLETE")
        return "DONE"
    except:
        raise

def response_handler(status_code, message, event):
    body = {
        "message": message,
        "deploy_status": event
    }

    response = {
        "statusCode": status_code,
        "body": body
    }

    return response
