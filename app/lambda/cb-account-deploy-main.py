# Import 3rd party modules needed for the app


import datetime
import logging
import boto3
import uuid
import json
import os
import re



# Import custom modules modules for this app
import pre_flight
import errors
import ddb

# Record runtime
now = datetime.datetime.now()
timestring = datetime.datetime.utcnow().strftime("%y%m%d%H%M%S")
datestring = datetime.datetime.utcnow().strftime("%Y-%m-%d")

# Configure logging
log_level = os.environ['log_level'] if 'log_level' in os.environ else "INFO"
logger = logging.getLogger()
logger.setLevel(log_level)

# Pull DB variables from environment variables in Lambda
ACCOUNT_CREATE_LAMBDA = os.environ['account_create_lambda'] if 'account_create_lambda' in os.environ else 'cb-account-create-main'
SSO_CONFIG_LAMBDA = os.environ['sso_config_lambda'] if 'sso_config_lambda' in os.environ else 'cb-account-sso-main'
TESTER_LAMBDA = os.environ['tester_lambda'] if 'tester_lambda' in os.environ else 'cb-deploy-tester'

role_name = "OrganizationAccountAccessRole"
# Our handler function
def account_deploy(event, context):
    # Fetch DB credentials from AWS Secrets Manager (the execution context should have permission)
    try:
        print(event)
        response = pre_flight.input_validation(event, "input_mapping.json" )
        db_dict = pre_flight.input_grooming(event, "input_mapping.json")
        db_dict['account_role'] = role_name
        if re.search("9-9999999", db_dict['ucd_account_num']):
            # Determine if this is a test run by detecting 9-9999999 as the account string
            message = "This is a test run..."
            logger.info(message)
            if re.search((r"9-9999999-"), db_dict['ucd_account_num']):
                # Determine if this is a test run to generate a predetermined error
                test_error = db_dict['ucd_account_num'].split('-')[2]
                logger.info(test_error)
            else:
                test_error = ""
            if(test_error != ""):
                message = "This is an error test run..."
                logger.info(message)
                if(test_error == "FINIT"):
                    return response_handler(500, message, "FAILURE")
                else:
                    account_values = new_aws_account_record(db_dict)
                    message = {
                                "account_email": account_values['account_email'],
                                "uuid": account_values['cbid'],
                                "account_name": account_values['account_name'],
                                "test_error": test_error
                              }
                    invoke_lambda(TESTER_LAMBDA, json.dumps(message))
                    return response_handler(200, message, "SUCCESS")
            account_values = new_aws_account_record(db_dict)
            message = {
                        "account_email": account_values['account_email'],
                        "uuid": account_values['cbid'],
                        "account_name": account_values['account_name']
                      }
            invoke_lambda(TESTER_LAMBDA, json.dumps(message))
            return response_handler(200, message, "SUCCESS")
        if re.fullmatch("^\d{12}$", db_dict['account_id']) is not None:
            # Check for an account number
            logger.info("Account ID: %s detected in JSON object, checking database for record..." % db_dict['account_id'])
            dupe_record = ddb.checkForDupes(db_dict['account_id'], db_dict['account_cloud'])
            # Check to determine if we already have the account number in our database
            if "CHECK_PASSED" in dupe_record:
                account_values = new_aws_account_record(db_dict)
                try:
                    ddb.updateAccountRecord(account_values['cbid'], "account_id", account_values['account_id'])
                except:
                    raise
                else:
                    logger.info("Record added to DB. Attempting to configure account for SSO...")
                    try:
                        ddb.updateAccountRecord(account_values['cbid'], "account_status", "DEPLOYED")
                        ddb.updateAccountRecord(account_values['cbid'], "cb_new_account", 0)
                        ddb.updateAccountRecord(account_values['cbid'], "account_email", db_dict["existing_account_email"])
                        payload = {
                                    "cbid": account_values['cbid']
                                  }
                        invoke_lambda(SSO_CONFIG_LAMBDA, json.dumps(payload))
                    except:
                        message = "Account %s successfully added to DB as record %s, but an error occurred with the SSO deployment. Check account status in DB, review logs and call SSO config separately to restart." % (account_values['account_id'], account_values['cbid'])
                        raise
                    else:
                        message = {
                                    "account_name": account_values['account_name'],
                                    "account_email": account_values['account_email'],
                                    "uuid": account_values['cbid'],
                                  }
                        return response_handler(200, message, "SUCCESS")
            else:
                message = "Duplicate record found. CBID: %s" % dupe_record
                raise errors.ServerError(message)
        elif (db_dict['ucd_account_num'] != "9-9999999" and db_dict['account_id'] == ""):
            # If the run is not a test and if there is no existing account specified, proceed to deploy a new account
            logger.info("No account id detected in JSON object, creating new account for %s" % db_dict['account_primary_admin'])
            account_values = new_aws_account_record(db_dict)
            ddb.updateAccountRecord(
                account_values['cbid'], "cb_new_account", "TRUE")
            # Trigger the creation of a new account
            account_creation_response = create_org_account(account_values['cbid'], account_values['account_email'], role_name, account_values['account_name'])
            req_id = account_creation_response['CreateAccountStatus']['Id']
            payload = {
                        "req_id": req_id,
                        "cbid": account_values['cbid'],
                        "account_name": account_values['account_name']
                      }
            # Pass the request ID to our account creation lambda to continue the provisioning
            # process and return a SUCCESS response to the API caller with the CBID of the account record
            # so that the caller can check the status of the deployment as it proceeds
            create_response = invoke_lambda(ACCOUNT_CREATE_LAMBDA, json.dumps(payload))
            logger.info(payload)
            logger.info(create_response)
            message = {
                        "account_name": account_values['account_name'],
                        "account_email": account_values['account_email'],
                        "uuid": account_values['cbid'],
                        "req_id": req_id
                      }
            return response_handler(200, message, "SUCCESS")
        else:
            message = "Account ID is not valid for AWS"
            errors.ServerError(message)
    except:
        raise


def invoke_lambda(lambda_name, payload):
    client = boto3.client('lambda')
    message = "Invoking lambda: %s" % lambda_name
    logger.info(message)
    response = client.invoke(
        FunctionName = lambda_name,
        InvocationType = 'Event',
        LogType = 'None',
        Payload = payload
    )
    logger.info(response)
    return response

def new_aws_account_record(values_dict):
    # Function takes a database input dictionary, adds a cbid to it and passes it to a new record query
    # Populate the values_dict with some cloud specific values
    values_dict['account_status'] = 'INIT'
    timestring = datetime.datetime.utcnow().strftime("%y%m%d%H%M%S")
    datestring = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    values_dict['account_date_created'] = datestring
    # Create a new CBID UUID (this should be used for all record updates going forward)
    cbid = str(uuid.uuid4())
    values_dict['cbid'] = cbid

    # Create the account alias, which we'll use as the account 'friendly' name
    # Do this by attaching the last 4 chars of the cbid to the account_name

    values_dict['account_name'] = values_dict['account_name'] + "-" + cbid[-4:]

    # Create a root email address for the account creation portion of the script
    user_short = values_dict["account_primary_admin"].split('@')[0]
    root_email = "cloudbroker" + "+" + user_short + "-" + timestring + "@ucdavis.edu"
    values_dict['account_email'] = root_email
    values_dict['account_status'] = "INIT"
    try:
        logger.info(f'Account data: {values_dict}')
        insertResult = ddb.insertNewAccountRecord(values_dict)
        logger.info(f'Insert result {insertResult}')
        return values_dict
    except:
        raise

def create_org_account(cbid, root_email, role_name, account_name):
    org_client = boto3.client('organizations')
    try:
        res = org_client.create_account(
            Email=root_email,
            AccountName=account_name,
            RoleName=role_name,
            IamUserAccessToBilling='ALLOW'
        )
    except:
        raise
    else:
        ddb.updateAccountRecord(cbid, "account_status", "PENDING")
        return res

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
