# Import some necessary modules

import datetime
import logging
import boto3
import json
import os

# Import custom modules modules for this app
import ddb
import errors

# Record runtime
now = datetime.datetime.now()
timestring = datetime.datetime.utcnow().strftime("%y%m%d%H%M%S")

# Configure logging
log_level = os.environ['log_level'] if 'log_level' in os.environ else "INFO"
logger = logging.getLogger()
logger.setLevel(log_level)

def status_check(event, context):
    try:
        if 'cbid' in event["queryStringParameters"]:
            cbid_query = event["queryStringParameters"]["cbid"]
            status_result = ddb.getAccountRecord(cbid_query)
            status_return = { 'account_info': status_result }
            return response_handler('200', status_return)
        elif 'status' in event["queryStringParameters"]:
            status_query = event["queryStringParameters"]["status"]
            status_result = ddb.getAccountsByStatus(status_query)
            logger.info(status_result)
            return response_handler('200', status_result)
        elif ('accountid' in event['queryStringParameters'] and 'cloud' in event['queryStringParameters']):
            account_id_query = event["queryStringParameters"]["accountid"]
            cloud_query = event["queryStringParameters"]["cloud"]
            cbid = ddb.checkForDupes(account_id_query, cloud_query)
            status_result = [ddb.getAccountRecord(cbid)]
            logger.info(status_result)
            return response_handler('200', status_result)
        else:
            raise errors.BadRequest("Invalid or missing query parameter.")
    except:
        raise

def switch_query(query_param):
    switcher = {
        1: "status",
        2: "cbid",
        3: "acocunt_id",
        4: "account_poc"
    }
    return switcher.get(query_param, "INVALID")

def response_handler(status_code, message):
    response = {
        "isBase64Encoded": 'false',
        "statusCode": status_code,
        "body": json.dumps(message)
    }

    return response
