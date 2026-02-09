# Import 3rd party modules needed for the app
import datetime
import logging
import json
import os
import re


# Import custom modules modules for this app
from cbuConnectAPI import uConnectAPI
import cbADGroupDeploy
import pre_flight
import aws
import ddb


# Import stupid badly named files
deploy = __import__("cb-account-deploy-main")

# Record runtime
now = datetime.datetime.now()
timestring = datetime.datetime.utcnow().strftime("%y%m%d%H%M%S")

# Configure logging
log_level = os.environ['log_level'] if 'log_level' in os.environ else "INFO"
UCONNECT_API_CREDS = os.environ['uconnect_api_creds']
azure_create_lambda = os.environ['azure_create_lambda']
env = os.environ['env'] if 'env' in os.environ else "test"
logger = logging.getLogger()
logger.setLevel(log_level)

# Deploy an azure account
def azure_deploy(event, context):
    try:
        # Initialize the uConnect API class. This is taken from cb-groups-api created by Blaise
        keys = aws.get_secret(UCONNECT_API_CREDS)
        UCONNECT_API_PUBKEY = keys['adapi_public']
        UCONNECT_API_PRIVKEY = keys['adapi_private']
        UCONNECT_URL = keys['adapi_url']
        uc = uConnectAPI(pubkey=UCONNECT_API_PUBKEY,
                            privkey=UCONNECT_API_PRIVKEY, url=UCONNECT_URL)
    except:
        raise
    try:
        print(event)
        response = pre_flight.input_validation(event, "input_mapping.json")
        db_dict = pre_flight.input_grooming(event, "input_mapping.json")
        if env == "test":
            for key in db_dict:
                db_dict[key] = db_dict[key].replace('@ucdavis.edu', '@mail.t3.ucdavis.edu')
        logger.info(f"DB Dict Info: {db_dict}")
        azure_owner = db_dict['account_primary_admin']
        azure_contributor = db_dict['account_technical_poc']
        ucd_budget_auth = db_dict['ucd_budget_auth']
        account_billing_poc = db_dict['account_billing_poc']
        azure_display_name = db_dict['account_name']
        azure_alias = db_dict['account_name']
        azure_account_type = db_dict['azure_account_type']

        azure_management_group = db_dict['azure_default_management_group']
        payload = {
            "owner_upn": azure_owner,
            "contributor_upn": azure_contributor,
            "ucd_budget_auth": ucd_budget_auth,
            "account_billing_poc": account_billing_poc,
            "azure_alias": azure_alias,
            "azure_display_name": azure_display_name,
            "azure_management_group": azure_management_group,
            "sub_id": None,
            "azure_account_type": azure_account_type
        }
        payload = payload_translate(payload, uc, db_dict)
        if re.fullmatch("^\w{8}-\w{4}-\w{4}-\w{4}-\w{12}$", db_dict['account_id']) is not None:
            dupe_record = ddb.checkForDupes(
                db_dict['account_id'], db_dict['account_cloud'])
            if "CHECK_PASSED" in dupe_record:
                db_dict = deploy.new_aws_account_record(db_dict)
                payload['cbid'] = db_dict['cbid']
                message = {
                    "account_name": db_dict['account_name'],
                    "account_email": db_dict['account_email'],
                    "uuid": db_dict['cbid'],
                }
                ddb.updateAccountRecord(db_dict['cbid'], 'account_status', 'PENDING')
                payload['sub_id'] = db_dict['account_id']
                deploy.invoke_lambda(azure_create_lambda, json.dumps(payload))
                return response_handler(200, message, "SUCCESS")
            else:
                azure_sub = db_dict['account_id']
                message = f'Azure subscription {azure_sub} already exists.'
                logger.error(message)
                #logger(f'Response {contributor_res}')
                return response_handler(400, message, "ACCOUNT_FAILED")
        elif db_dict['account_id'] == "":
            db_dict = deploy.new_aws_account_record(db_dict)
            payload['cbid'] = db_dict['cbid']
        else:
            message = "Subscription number format is incorrect"
            logger.error(message)
            return response_handler(400, message, "ACCOUNT_FAILED")
        try:
            deploy.invoke_lambda(azure_create_lambda, json.dumps(payload))
            message = {
                "account_name": db_dict['account_name'],
                "account_email": db_dict['account_email'],
                "uuid": db_dict['cbid'],
            }
            return response_handler(200, message, "SUCCESS")
        except:
            raise
    except:
        raise


def payload_translate(payload, uc, db_dict):
    azure_contributor = payload['contributor_upn']
    azure_owner = payload['owner_upn']
    azure_budget_auth = payload['ucd_budget_auth']
    account_billing_poc = payload['account_billing_poc']
    # Translate the owner value to UPN
    #owner_res, owner_body = uc.get_user_by_mail(azure_owner)
    owner_res, owner_body = cbADGroupDeploy.get_ad_user_by_email(uc, azure_owner)
    if owner_res.status_code == 200:
        logger.info(f"UPN query output for owner: {owner_body}")
        owner_upn = owner_body['result']['userPrincipalName']
        # Translate the budget authority value to UPN
        billing1_res, billing1_body = cbADGroupDeploy.get_ad_user_by_email(uc, azure_budget_auth)
        if owner_res.status_code == 200:
          logger.info(f"UPN query output for budget auth: {billing1_body}")
    else:
        message = f"Owner {azure_owner} not found in AD. Error details: {owner_res}."
        logger.error(message)
        return response_handler(400, message, "ACCOUNT_FAILED")
    payload['owner_upn'] = owner_upn
    logger.info(f"Owner UPN: {owner_upn}")
    # If there is a contributor, translate the contributor value to UPN
    if azure_contributor != "":
        contributor_res, contributor_body = cbADGroupDeploy.get_ad_user_by_email(
            uc, azure_contributor)
        if contributor_res.status_code == 200:
            contributor_upn = contributor_body['result']['userPrincipalName']
            payload['contributor_upn'] = contributor_upn
            logger.info(f"Contributor UPN: {contributor_upn}")
        else:
            message = f'Contributor {azure_contributor} not found in domain data.'
            logger.error(message)
            payload['contributor_upn'] = None
    else:
        contributor_upn = None
        payload['contributor_upn'] = contributor_upn
    # If there is a secondary billing PoC, translate the email address to UPN but don't die
    if account_billing_poc != "":
        billing_poc_res, billing_poc_body = cbADGroupDeploy.get_ad_user_by_email(
            uc, account_billing_poc)
        if billing_poc_res.status_code == 200:
            billing_poc_upn = billing_poc_body['result']['userPrincipalName']
            payload['account_billing_poc'] = billing_poc_upn
            logger.info(f"Billing PoC UPN: {billing_poc_upn}")
        else:
            message = f'Billing PoC {account_billing_poc} not found in domain data.'
            logger.error(message)
            payload['account_billing_poc'] = None
    else:
        billing_poc_upn = None
        payload['account_billing_poc'] = billing_poc_upn
    return payload

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
