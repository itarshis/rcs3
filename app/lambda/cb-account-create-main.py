# Import 3rd party modules needed for the app

import datetime
import logging
import boto3
import json
import time
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

# Pull DB variables from environment variables in Lambda
METADATA_BUCKET = os.environ['metadata_bucket'] if 'metadata_bucket' in os.environ else 'ira-cb-adfs-metadata'
SSO_CONFIG_LAMBDA = os.environ['sso_config_lambda'] if 'sso_config_lambda' in os.environ else 'cb-account-deploy-dev-account_sso'

# Our handler function to trigger the check on the account creation status
def handler(event, context):
    try:
        req_id = event['req_id']
        cbid = event['cbid']
        check_result = check_org_account(cbid, req_id)
        logger.info(check_result)
    except:
        raise
    else:
        try:
            logger.info("Invoking SSO Lambda.")
            payload = {
                        "cbid": event['cbid']
                        }
            sso_invoke_response = invoke_lambda(SSO_CONFIG_LAMBDA, json.dumps(payload))
        except:
            logger.error("ERROR calling SSO config lambda: %s" % sso_invoke_response)
            raise
        else:
            logger.info(sso_invoke_response)
            message = "Account deployment succeeded."
            return response_handler(200, message, "SUCCESS")

def check_org_account(cbid, req_id):
    """
    Use the RequestId to check the status of the account creation 
    process and update our database status accordingly
    """
    org_client = boto3.client('organizations')
    req_stat = 'IN_PROGRESS'
    ddb.updateAccountRecord(cbid, "account_status", "PENDING")
    while req_stat == 'IN_PROGRESS':
        status = org_client.describe_create_account_status(
            CreateAccountRequestId=req_id
        )
        req_stat = status['CreateAccountStatus']['State']
        logger.info("Waiting for org account creation. Reference: " + cbid)
        time.sleep(10)
    if req_stat == 'SUCCEEDED':
        try:
            ddb.updateAccountRecord(cbid, "account_status", "DEPLOYED")
        except:
            raise
        else:
            try:
                ddb.updateAccountRecord(
                    cbid, "account_id", status['CreateAccountStatus']['AccountId'])
            except:
                raise
            else:
                return status
    else:
        message = 'Account creation failed cbid:' + cbid + '. Failure reason is:' + status['CreateAccountStatus']['FailureReason'] + '.'
        logger.error(message)
        ddb.updateAccountRecord(cbid, "account_status", "ACCT_FAILED")
        raise errors.ServerError(message)

def invoke_lambda(lambda_name, payload):
    client = boto3.client('lambda')
    message = "Invoking lambda: %s" % lambda_name
    logger.info(message)
    try:
        response = client.invoke(
            FunctionName = lambda_name,
            InvocationType = 'RequestResponse',
            LogType = 'None',
            Payload = payload
        )
    except:
        raise
    else:
        logger.info(response)
        return response

# Error handling functions

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
