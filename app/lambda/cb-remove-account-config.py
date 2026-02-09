# Import 3rd party modules needed for the app
import os
import boto3
import base64
import logging
import datetime


# Import custom modules modules for this app
import ddb
import iam_policies

sso = __import__("cb-account-sso-main",
                 fromlist=['move_org_account'])

# Record runtime
now = datetime.datetime.now()
timestring = datetime.datetime.utcnow().strftime("%y%m%d%H%M%S")

# Configure logging
log_level = os.environ['log_level'] if 'log_level' in os.environ else "INFO"
logger = logging.getLogger()
logger.setLevel(log_level)

# Pull DB variables from environment variables in Lambda
METADATA_BUCKET = os.environ['metadata_bucket'] if 'metadata_bucket' in os.environ else 'ira-cb-adfs-metadata'
DEST_OU = os.environ['cb_root_org'] if 'cb_root_org' in os.environ else "org_root-test"
SOURCE_OU = os.environ['cb_basic_ou'] if 'cb_basic_ou' in os.environ else "cb_ou-test"

ORG_ROOT = SOURCE_OU
CB_OU = DEST_OU

# Our handler function
def handler(event, context):
    logger.info(event)
    try:
        account_id = event['query']['id']
    except:
        raise
    else:
        try:
            cbid = ddb.checkForDupes(account_id, 'aws')
            account_record = ddb.getAccountRecord(cbid)
            account_name = account_record['account_name']
            role_name = account_record['account_role']
            ucd_account_num = account_record['ucd_account_num']
            if role_name != 'OrganizationAccountAccessRole':
                role_name = "OrganizationAccountAccessRole"
        except:
            raise
        if ucd_account_num == "9-9999999":
            try:
                ddb.deleteAccountRecord(cbid)
                message = "Account %s rolled back to unconfigured state and removed from DB" % account_name
                return response_handler(200, message, "SUCCESS")
            except:
                message = f"Error deleting record from database for {account_id}. DB record does not exist"
                return response_handler(500, message, event)
        if account_record['account_status'] != "":
            try:
                session = get_xaccount_session(account_id, role_name)
                org_account_saml = delete_idp(account_id, 'ucd-adfs', session)
            except:
                ddb.updateAccountRecord(cbid, "account_status", "DELETE_IDP_ERROR")
                raise
            try:
                delete_default_roles(cbid, session, account_id, role_name)
            except:
                ddb.updateAccountRecord(cbid, "account_status", "DELETE_CB_ROLES_ERROR")
                raise
            try:
                move_account = sso.move_org_account(cbid, account_id)
                message = f"Account move result {move_account}"
                logger.info(message)
            except:
                ddb.updateAccountRecord(cbid, "account_status", "MOVE_CB_ACCOUNT_ERROR")
                raise
            else:
                ddb.deleteAccountRecord(cbid)
                message = "Account %s rolled back to unconfigured state and removed from DB" % account_name
                return response_handler(200, message, "SUCCESS")
        elif account_record['account_status'] == "DELETE_CB_ROLES_ERROR":
            try:
                session = get_xaccount_session(account_id, role_name)
                delete_default_roles(cbid, session, account_id, role_name)
            except:
                ddb.updateAccountRecord(cbid, "account_status", "DELETE_CB_ROLES_ERROR")
                raise
            try:
                move_account = sso.move_org_account(cbid, account_id)
                message = f"Account move result {move_account}"
                logger.info(message)
            except:
                ddb.updateAccountRecord(cbid, "account_status", "MOVE_CB_ACCOUNT_ERROR")
                raise
            else:
                ddb.deleteAccountRecord(cbid)
                message = "Account %s rolled back to unconfigured state and removed from DB" % account_name
                return response_handler(200, message, "SUCCESS")
        else:
            message = "ERROR: Account could not be rolled back. Status: %s" % account_record['account_status']
            logger.error(message)
            return response_handler(500, message, event)

def delete_idp(account_id, provider_name, session):
    try:
        iam_client = session.client('iam')
        org_account_saml = iam_client.delete_saml_provider(
            SAMLProviderArn="arn:aws:iam::" + account_id + ":saml-provider/" + provider_name
        )
    except iam_client.exceptions.NoSuchEntityException:
        pass
    except:
        raise
    else:
        logger.info("Account IDP deleted: " + account_id)

def get_saml_provider(session):
    try:
        iam_client = session.client('iam')
        response = iam_client.list_saml_providers()
    except:
        raise
    else:
        logger.info("SAML provider list: %s" % response )
        return response


def delete_default_roles(cbid, session, account_id, role_name):
    try:
        trust_policy = iam_policies.trust_policy['XAccount-Trust']
        iam_client = session.client('iam')
        role_list = iam_policies.role_defs
        role_list_keys = role_list.keys()
        for r in role_list_keys:
            detach_res = iam_client.detach_role_policy(
                RoleName=r,
                PolicyArn="arn:aws:iam::" + account_id + ":policy/" + r + "-Policy"
            )
            role_res = iam_client.delete_role(
                RoleName=r
            )
            policy_res = iam_client.delete_policy(
                PolicyArn="arn:aws:iam::" + account_id + ":policy/" + r + "-Policy"
            )
        iam_client.detach_role_policy(
            RoleName="UCD-Read-Only",
            PolicyArn='arn:aws:iam::aws:policy/ReadOnlyAccess'
        )
        read_only = iam_client.delete_role(
            RoleName="UCD-Read-Only"
        )
    except iam_client.exceptions.NoSuchEntityException:
        pass
    except:
        raise
    else:
        logger.info("Default roles have been deleted from account: %s" % account_id)

def get_xaccount_session(account_id, role_name):
    role_arn = ("arn:aws:iam::%s:role/%s" % (account_id, role_name))
    print(role_arn)
    try:
        sts_client = boto3.client('sts')
        res = sts_client.assume_role(
            RoleArn=role_arn.strip(),
            RoleSessionName="AssumeRoleSession1"
        )
        session = boto3.Session(
            aws_access_key_id=res['Credentials']['AccessKeyId'],
            aws_secret_access_key=res['Credentials']['SecretAccessKey'],
            aws_session_token=res['Credentials']['SessionToken']
        )
    except:
        raise
    else:
        logger.info("Cross-account role session created for account:" + account_id)
        return session

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
