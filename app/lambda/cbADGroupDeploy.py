# Import external modules
from time import sleep
import datetime
import logging
import base64
import boto3
import json
import os



# Import internal modules
import ddb
import aws
import errors
import iam_policies
from cbuConnectAPI import uConnectAPI

#Configure Logging
log_level = os.environ['log_level'] if 'log_level' in os.environ else "INFO"
logger = logging.getLogger()
logger.setLevel(log_level)

# Grab our ENV variables for use in the rest of the script
#UCONNECT_URL = os.environ['uconnect_url']
UCONNECT_API_CREDS = os.environ['uconnect_api_creds']
AD_CONTEXT = os.environ['ad_context'] if 'ad_context' in os.environ else 'dev'
ALT_MAIL_IDS = os.environ['alt_mail_ids'].split(",") if 'alt_mail_ids' in os.environ else "@ad3.ucdavis.edu,@mail.t3.ucdavis.edu".split(",")
UINFORM_API_SLEEP = os.environ['uinform_api_sleep'] if 'uinform_api_sleep' in os.environ else '10'
UINFORM_API_CYCLES = os.environ['uinform_api_cycles'] if 'uinform_api_cycles' in os.environ else '10'

# Grab constants from iam_policies file
UCD_OWNER = iam_policies.UCD_OWNER
UCD_FULL_ADMIN = iam_policies.UCD_FULL_ADMIN
UCD_BILLING = iam_policies.UCD_BILLING
UCD_BILLING_AZ = iam_policies.UCD_BILLING_AZ
UCD_READ_ONLY = iam_policies.UCD_READ_ONLY

def handler(event, context):
    logger.info(f"GROUPS: {UCD_OWNER}, {UCD_FULL_ADMIN}, {UCD_BILLING}, {UCD_READ_ONLY}")
    try:
        processLog = {}
        roleList= iam_policies.role_defs
        roles = list(roleList)
        roles.append(UCD_READ_ONLY)
        logger.debug("Roles: %s" % roles)
        cbid = event['cbid']
        account = ddb.getAccountRecord(event['cbid'])
    except:
        raise
    else:
        try:
            # Initialize the uConnect API class. This is taken from cb-groups-api created by Blaise
            keys = aws.get_secret(UCONNECT_API_CREDS)
            UCONNECT_API_PUBKEY = keys['adapi_public']
            UCONNECT_API_PRIVKEY = keys['adapi_private']
            UCONNECT_URL = keys['adapi_url']
            uc = uConnectAPI(pubkey=UCONNECT_API_PUBKEY,privkey=UCONNECT_API_PRIVKEY,url=UCONNECT_URL)
        except:
            ddb.updateAccountRecord(
                cbid, "account_status", "ACCT_AD_CFG_ERROR")
            raise
        else:
            logger.debug("uConnect class instantiated")
            logger.debug(f"Account details: {account}")
    for r in roles:
        logger.debug(f"Creating group for role {r}")
        group = account['account_cloud'].upper() + "-" + account['account_id'] + "-" + r
        result = createGroup(r, account, uc, cbid)
        sleep(int(UINFORM_API_SLEEP))
        logger.debug(f"Group creation process for role {r} is in status {result}")
        if (result == "failed"):
            ddb.updateAccountRecord(
                cbid, "account_status", "ACCT_AD_CFG_ERROR")
            raise errors.ServerError(f"Group creation failed for role {r} in account {account['account_name']}")
        elif (result == "complete"):
            logger.info(f"Group created for role {r} in account {account['account_name']}")
            processLog[group] = "COMPLETED"
        elif (result == "duplicate"):
            logger.info(f"Group already exists for role {r} in account {account['account_name']}")
            processLog[group] = "DUPLICATE"
        else:
            ddb.updateAccountRecord(
                cbid, "account_status", "ACCT_AD_CFG_ERROR")
            raise errors.ServerError(f"Group processing error: {result}")
        if (r == UCD_OWNER):
            #Populate the UCD-Owners group. If this fails, we raise an error.
            #Failure should be fatal and recorded
            member = account['account_poc']
            result = populateGroup(member, group, uc, cbid)
            if (result != "complete"):
                processLog[member] = "FAILED"
                ddb.updateAccountRecord(
                    cbid, "account_status", "ACCT_AD_CFG_ERROR")
                raise errors.ServerError(f"Failed to add {member} to group {group}. This is fatal. Error: {result}")
            else:
                logger.info(f"Added member {member} to group {group} successfully")
                processLog[member] = f"{r}"
        elif (r == UCD_FULL_ADMIN):
            #Populate the UCD-Full-Admin group with technical POCs
            #Failure should not be fatal, but should be recorded
            members = []
            if account['account_technical_poc']:
                members.append(account['account_technical_poc'])
            if account['account_primary_admin']:
                members.append(account['account_primary_admin'])
            for m in members:
                result = populateGroup(m, group, uc, cbid)
                if (result != "complete"):
                    logger.error(f"Failed to add {m} to group {group}. Error: {result}")
                    processLog[m] = "FAILED"
                else:
                    logger.info(f"Added member {m} to group {group} successfully")
                    processLog[m] = f"{r}"
        elif (r == UCD_BILLING):
            #Populate the UCD-Billing-Read group with budget authority and billing POC
            #Failure should be fatal for the ucd_budget_auth, but not for other members.
            members = []
            budget = account['ucd_budget_auth']
            result = populateGroup(budget, group, uc, cbid)
            if (result != "complete"):
                processLog[budget] = "FAILED"
                ddb.updateAccountRecord(
                    cbid, "account_status", "ACCT_AD_CFG_ERROR")
                raise errors.ServerError(f"Failed to add {budget} to group {group}. This is fatal. Error: {result}")
            else:
                logger.info(f"Added budget authority {budget} to group {group} successfully")
                processLog[budget] = f"{r}"
            if account['account_billing_poc']:
                members.append(account['account_billing_poc'])
            try:
                if account['account_budget_poc']:
                    members.append(account['account_budget_poc'])
            except KeyError:
                continue
            for m in members:
                result = populateGroup(m, group, uc, cbid)
                if (result != "complete"):
                    logger.error(f"Failed to add {m} to group {group}. This is fatal. Error: {result}")
                    processLog[m] = "FAILED"
                else:
                    logger.info(f"Added member {m} to group {group} successfully")
                    processLog[m] = f"{r}"
    for r in roles:
        logger.debug(f"Updating role {r} group for account {account}")
        id = account['account_id']
        cloud = "AWS"
        name = account['account_name']
        base = cloud + '-' + id
        group = cloud + '-' + id + '-' + r
        description = f"AWS account access for role {r}"
        updateResult = updateGroupInfo(group, account, r, description, base, uc, cbid)
        if ("failed" == updateResult):
            ddb.updateAccountRecord(
                cbid, "account_status", "ACCT_AD_CFG_ERROR")
            raise errors.ServerError(f"Failed to add details to group {group}. This is fatal. Error: {result}. Processing state: {processLog}")
        else:
            logger.info(f"Group updated for role {r} in account {account['account_name']}")
            processLog[group] = "UPDATED"
    processLogJson = json.dumps(processLog, sort_keys=True, indent=2)
    logger.info(f"Group deployment result: \n{processLogJson}")
    ddb.updateAccountRecord(cbid, "account_status", "COMPLETE")
    return response_handler(200, processLogJson, "SUCCESS")


def createGroup(role, account, uc, cbid):
    #Create a group with account details in ExtensionAttribute6
    logger.debug(f"Creating role {role} group for account {account}")
    id = account['account_id']
    cloud = account['account_cloud']
    group = account['account_cloud'].upper() + '-' + id + '-' + role
    description = f"{cloud} account access for role {role}"
    logger.info(f"Creating group {group} now.")
    res, body = uc.create_group(group, displayname=role, description=description, max_members=0)
    if res.status_code != 200:
        logger.error(f"Error response: {res} \nError details: {body}")
        if ("A group already exists with that name." == body['error']['message']):
            logger.debug(f"The group {group} cannot be deployed because it already exists. Attempting to update with CB details.")
            return("duplicate")
        else:
                logger.error(body['error']['message'])
                return("failed")
    else:
        logger.debug(f"Full group creation response: {body}")
        req = body['result']['requestGuid']
        result = checkRequestStatus(req, uc, cbid)
        if result != "complete":
            return("failed")
        else:
            return("complete")

def populateGroup(member, group, uc, cbid):
    #Add a member to a given group after first getting GUIDs for both objects
    logger.debug(f"Adding users {member} to group {group}")
    res, body = get_ad_user_by_email(uc, member)
    if res.status_code != 200:
        return "user_failure"
    else:
        userGuid = body['result']['objectGuid']
    res, body = uc.get_group_by_samaccount(group)
    if res.status_code != 200:
        if (res.status_code == 404):
            tries = 5
            pause = 5
            while (tries > 0):
                res, body = uc.get_group_by_samaccount(group)
                if res.status_code == 404:
                    sleep(pause)
                    tries -= 1
                    continue
                elif res.status_code == 200:
                    break
                else:
                    logger.error(f"Error response: {res} \nError details: {body}")
                    return "group_failure"
        else:
            logger.error(f"Error response: {res} \nError details: {body}")
            return "group_failure"
    groupGuid = body['result']['objectGuid']
    add_res, add_body = uc.add_group_membership_by_guid(userGuid, groupGuid)
    if add_res.status_code != 200:
        logger.error(f"Error response: {add_res} \nError details: {add_body}")
        return "add_failure"
    else:
        req = add_body['result']['requestGuid']
        result = checkRequestStatus(req, uc, cbid)
        if result != "complete":
            return ("request_failure")
        else:
            return("complete")


def checkRequestStatus(req, uc, cbid, tries=int(UINFORM_API_CYCLES), pause=int(UINFORM_API_SLEEP)):
    logger.debug(f"Checking request {req} status")
    res, body = uc.get_requests_by_guid(req)
    logger.debug(f"Full request response: {body}")
    logger.info(f"Request {req} status is {body['result']['status']} (status code {body['result']['statusId']})")
    while (tries > 0):
        res, body = uc.get_requests_by_guid(req)
        if (body['result']['statusId'] == 4):
            logger.info(f"Request {req} completed with status {body['result']['status']}")
            return "complete"
        elif (body['result']['statusId'] == 5):
            logger.error(f"Request {req} failed with status {body['result']['status']}")
            try:
                res, body = uc.get_requests_log(req)
            except:
                logger.error(f"Request {req} error details unavailable.")
                return "incomplete"
            else:
                logger.error(f"Request {req} error details: {body}")
                ddb.updateAccountRecord(
                    cbid, "account_status", "ACCT_AD_CFG_ERROR")
                errors.ServerError(f"Request failed. Log info: {body}")
        else:
            sleep(pause)
            tries -= 1
            continue
    return "incomplete"

def updateGroupInfo(group, account, role, description, base, uc, cbid):
    logger.debug(f"Updating group {group}. Role is {role}. Description is {description}. Base is {base}")
    try:
        res, body = uc.get_group_by_samaccount(group)
    except:
        raise
    else:
        logger.debug("Group info:")
        logger.debug(body)
        owner = base + "-" + UCD_OWNER
        admin = base + "-" + UCD_FULL_ADMIN
        guid = body['result']['objectGuid']
        accountId = account['account_id']
        account = account['account_name']
        try:
            res, body = uc.get_group_by_samaccount(owner)
            ownerGuid = body['result']['objectGuid']
        except:
            logger.error(f"Unable to get owner guid for group {group}. Error details: {body}")
            ownerGuid = ""
        else:
            try:
                res, body = uc.get_group_by_samaccount(admin)
                adminGuid = body['result']['objectGuid']
            except:
                logger.error(f"Unable to get owner guid for group {group}. Error details: {body}")
                adminGuid = ""
            else:
                logger.info(f"Successfully assigned owner and admin GUIDs. Admin GUID: {adminGuid}. Owner GUID: {ownerGuid}.")
    try:
        if (role == UCD_OWNER):
            logger.debug("Role is owner.")
            isOwner = 1
            isAdmin = 0
            isBillingRead = 0
        elif (role == UCD_FULL_ADMIN):
            logger.debug("Role is admin.")
            isOwner = 0
            isAdmin = 1
            isBillingRead = 0
        elif (role == UCD_BILLING or role == UCD_BILLING_AZ):
            logger.debug("Role is billing read.")
            isOwner = 0
            isAdmin = 0
            isBillingRead = 1
        else:
            logger.debug("Role is not owner or admin.")
            isOwner = 0
            isAdmin = 0
            isBillingRead = 0
        extension = json.dumps(
            {"account": account, "accountId": accountId, "isOwner": isOwner, "isAdmin": isAdmin, "isBillingRead": isBillingRead, "cbid": cbid, "ownerGuids": ownerGuid, "adminGuids": adminGuid})
        logger.debug(f"Extension: {extension}")
    except:
        logger.error(f"Unable to determine role for group {group}")
        raise
    else:
        res, body = uc.update_group_by_guid(guid, displayname=role, description=description, extension=extension)
        if res.status_code != 200:
            logger.error(f"Error response: {res} \nError details: {body}")
            return "failed"
        else:
            logger.debug(f"Full group update response: {body}")
            req = body['result']['requestGuid']
            result = checkRequestStatus(req, uc, cbid)
            if result != "complete":
                logger.error("Incomplete")
            else:
                return("complete")

def get_ad_user_by_email(uc, member):
    r, b = uc.get_user_by_mail(member)
    logger.debug(f"Result: {r}. Body {b}")
    if r.status_code != 200:
        logger.error(
            f"Error response: {r} \nError details: {b}")
        r, b = uc.get_user_by_email(member)
        if r.status_code != 200:
            if AD_CONTEXT != "prod":
                for mail_id in ALT_MAIL_IDS:
                    member = member.split("@")[0] + mail_id
                    r, b = uc.get_user_by_mail(member)
                    if r.status_code != 200:
                        r, b = uc.get_user_by_email(member)
                        if r.status_code != 200:
                            logger.error(
                                f"Error finding user {mail_id} response: {r} \nError details: {b}")
                            continue
                        else:
                            logger.debug(
                              f"Found user {member} in proxyAddresses field. Status: {r}. Body: {b}")
                            return r, b
                    else:
                        logger.debug(
                            f"Found user {member} in mail field. Status: {r}. Body: {b}")
                        return r, b
                logger.error(f"Unable to find the user. Result: {r}. Body: {b}.")
                return r, b
            else:
              logger.error(f"Unable to find the user. Result: {r}. Body: {b}.")
              return r, b
        else:
            logger.debug(f"Found user {member} in proxyAddresses field. Status: {r}. Body: {b}")
            return r, b
    else:
        logger.debug(f"Found user {member} in mail field. Status: {r}. Body: {b}")
        return r, b

def get_secret(secret_name):

    region_name = os.environ['AWS_REGION']

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )
    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except:
        raise
    else:
        # Decrypts secret using the associated KMS CMK.
        # Depending on whether the secret is a string or binary, one of these fields will be populated.
        if 'SecretString' in get_secret_value_response:
            secret = get_secret_value_response['SecretString']
        else:
            decoded_binary_secret = base64.b64decode(get_secret_value_response['SecretBinary'])
    return secret


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
