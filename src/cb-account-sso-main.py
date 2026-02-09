# Import 3rd party modules needed for the app


import datetime
import logging
import boto3
import json
import time
import os

# Import custom modules modules for this app
import ddb
import aws
import iam_policies

# Import modules with naming issues
deploy = __import__("cb-account-deploy-main")

# Record runtime
now = datetime.datetime.now()
timestring = datetime.datetime.utcnow().strftime("%y%m%d%H%M%S")

# Configure logging
log_level = os.environ['log_level'] if 'log_level' in os.environ else "INFO"
logger = logging.getLogger()
logger.setLevel(log_level)

# Pull DB variables from environment variables in Lambda
METADATA_BUCKET = os.environ['metadata_bucket'] if 'metadata_bucket' in os.environ else 'ira-cb-adfs-metadata'
AD_GROUP_LAMBDA = os.environ['ad_group_lambda'] if 'ad_group_lambda' in os.environ else 'cb-deploy-group'
ORG_ROOT = os.environ['cb_root_org'] if 'cb_root_org' in os.environ else "org_root-test"
CB_OU = os.environ['cb_basic_ou'] if 'cb_basic_ou' in os.environ else "cb_ou-test"
azure_create_lambda = os.environ['azure_create_lambda']

# Our handler function
def handler(event, context):
    try:
        print(event)
        cbid = event['cbid']
    except:
        raise
    else:
        account_record = ddb.getAccountRecord(event['cbid'])
        if (account_record['account_cloud'] == 'azure'):
            azure_owner = account_record['account_primary_admin']
            azure_contributor = account_record['account_technical_poc']
            ucd_budget_auth = account_record['ucd_budget_auth']
            azure_display_name = account_record['account_name']
            azure_alias = account_record['account_name']
            azure_management_group = account_record['azure_default_management_group']
            payload = {
                "owner_upn": azure_owner,
                "contributor_upn": azure_contributor,
                "ucd_budget_auth": ucd_budget_auth,
                "azure_alias": azure_alias,
                "azure_display_name": azure_display_name,
                "azure_management_group": azure_management_group,
                "sub_id": None
            }
            payload['sub_id'] = account_record['account_id']
            deploy.invoke_lambda(azure_create_lambda, json.dumps(payload))
            message = {
                "account_info": {
                    "uuid": account_record['cbid'],
                    "account_name": account_record['account_name'],
                    "account_primary_admin": account_record['account_primary_admin'],
                    "account_status": account_record['account_status']
                }
            }
            return response_handler(200, message, "SUCCESS")
        try:
            saml_metadata = fetch_metadata(METADATA_BUCKET)
        except:
            raise
        try:
            #account_record = ddb.getAccountRecord(event['cbid'])
            account_id = account_record['account_id']
            account_name = account_record['account_name']
            role_name = account_record['account_role']
            provider_name = 'ucd-adfs'
        except:
            raise
        if "9-9999999" in account_record['ucd_account_num']:
            try:
                ddb.updateAccountRecord(
                    cbid, "account_status", "COMPLETE")
            except:
                raise
            else:
                message = {
                            "account_info": {
                                "account_email": account_record['account_email'],
                                "uuid": account_record['cbid'],
                                "account_name": account_record['account_name'],
                                "account_poc": account_record['account_poc'],
                                "account_status": account_record['account_status']
                            }
                          }
                return response_handler(200, message, "SUCCESS")
        if account_record['account_status'] not in [ "COMPLETE" ]:
            #return response_handler(200, message, "DEPLOYING")
            try:
                org_check = check_org_status(account_id)
            except Exception as e:
                ddb.updateAccountRecord(
                    cbid, "account_status", "ACCT_ORG_VALID_ERROR")
                logger.error(e)
                return response_handler(500, "ACCT_ADFS_CFG_ERROR", "FAILED")
            try:
                session = get_xaccount_session(account_id, role_name)
                org_account_saml = enable_idp(cbid, session, saml_metadata, account_id, provider_name)
            except Exception as e:
                ddb.updateAccountRecord(
                    cbid, "account_status", "ACCT_ADFS_CFG_ERROR")
                logger.error(e)
                return response_handler(500, "ACCT_ADFS_CFG_ERROR", "FAILED")
            try:
                create_default_roles(cbid, session, account_id, role_name, org_account_saml['SAMLProviderArn'])
            except Exception as e:
                ddb.updateAccountRecord(
                    cbid, "account_status", "ACCT_ROLE_CFG_ERROR")
                logger.error(e)
                return response_handler(500, "ACCT_ROLE_CFG_ERROR", "FAILED")
            try:
                create_account_alias(session, account_name)
                ddb.updateAccountRecord(
                    cbid, "account_status", "SSO_READY")
                move_result = move_org_account(cbid, account_id)
                logger.info(f"Move account result {move_result}")
            except Exception as e:
                ddb.updateAccountRecord(
                    cbid, "account_status", "ACCT_ALIAS_CFG_ERROR")
                logger.error(e)
                return response_handler(500, "ACCT_ALIAS_CFG_ERROR", "FAILED")
            try:
                payload = {
                            "cbid": cbid
                          }
                group_result = aws.invoke_lambda(AD_GROUP_LAMBDA, json.dumps(payload))
                logger.info(f"Group deploy result: {group_result}")
                message = {
                            "account_info": {
                                "account_email": account_record['account_email'],
                                "uuid": account_record['cbid'],
                                "account_name": account_record['account_name'],
                                "account_poc": account_record['account_poc'],
                                "account_status": account_record['account_status']
                            }
                          }
                return response_handler(200, message, "SUCCESS")
            except Exception as e:
                ddb.updateAccountRecord(
                    cbid, "account_status", "ACCT_AD_CFG_ERROR")
                logger.error(e)
                return response_handler(500, "ACCT_AD_CFG_ERROR", "FAILED")
            else:
                message = "Account %s deployment completed" % account_name
                logger.info(message)
        elif account_record['account_status'] == "COMPLETE":
            return response_handler(200, "COMPLETE", "SUCCESS")

def check_org_status(account_id):
    org_client = boto3.client('organizations')
    try:
        org_client.describe_account(
            AccountId=account_id
        )
    except:
        raise
    else:
        logger.info(f"Account {account_id} is an organization member account")

def move_org_account(cbid, account_id):
    org_client = boto3.client('organizations')
    try:
        org_client.move_account(
            AccountId=account_id,
            SourceParentId=ORG_ROOT,
            DestinationParentId=CB_OU
        )
    except Exception as e:
        logger.error(e)
        return "FAILURE"
    else:
        logger.info(f"Account {account_id} moved to {CB_OU} from {ORG_ROOT}.")
        return "SUCCESS"

def check_org_account(cbid, req_id):
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
        return message

def fetch_metadata(metadata_bucket):
    s3_client = boto3.client('s3')
    s3_client.download_file(metadata_bucket, "FederationMetadata.xml", '/tmp/metadata.xml')
    #metadata = open('/tmp/metadata.xml', 'r')
    #return metadata
    with open('/tmp/metadata.xml', 'r') as fin:
        metadata = fin.read()
    return metadata

def enable_idp(cbid, session, saml_metadata, account_id, provider_name):
    try:
        iam_client = session.client('iam')
        org_account_saml = iam_client.create_saml_provider(
            SAMLMetadataDocument=saml_metadata,
            Name=provider_name
        )
    except iam_client.exceptions.EntityAlreadyExistsException:
        logger.info(f"SAML provider ucd-adfs already exists. Continuing...")
        return {'SAMLProviderArn': f"arn:aws:iam::{account_id}:saml-provider/{provider_name}"}
    except:
        raise
    else:
        logger.info("Account enabled for sso. Reference cbid:" + cbid + ".")
        return org_account_saml

def get_saml_provider(session):
    try:
        iam_client = session.client('iam')
        response = iam_client.list_saml_providers()
    except:
        raise
    else:
        logger.info("SAML provider list: %s" % response )
        return response


def create_default_roles(cbid, session, account_id, role_name, saml_arn):
    try:
        trust_policy = iam_policies.trust_policy['XAccount-Trust']
        iam_client = session.client('iam')
        role_list = iam_policies.role_defs
        role_list_keys = role_list.keys()
        for r in role_list_keys:
            try:
                policy_res = iam_client.create_policy(
                    PolicyName=r + "-Policy",
                    PolicyDocument=json.dumps(role_list[r])
                )
                role_res = iam_client.create_role(
                    RoleName=r,
                    AssumeRolePolicyDocument=json.dumps(trust_policy) % saml_arn,
                )
                iam_client.attach_role_policy(
                    RoleName=role_res['Role']['RoleName'],
                    PolicyArn=policy_res['Policy']['Arn']
                )
            except iam_client.exceptions.EntityAlreadyExistsException:
                logger.info(f"Roles {r} already exists. Continuing...")
                continue
            except:
                raise
        read_only = iam_client.create_role(
            RoleName="UCD-Read-Only",
            AssumeRolePolicyDocument=json.dumps(trust_policy) %saml_arn
        )
        iam_client.attach_role_policy(
            RoleName=read_only['Role']['RoleName'],
            PolicyArn='arn:aws:iam::aws:policy/ReadOnlyAccess'
        )
    except iam_client.exceptions.EntityAlreadyExistsException:
        logger.info(f"Roles 'UCD-Read-Only' already exists. Continuing...")
        pass
    except:
        raise
    else:
        logger.info("Default roles have been deployed to account: %s" % account_id)

def create_account_alias(session, account_short_name):
    iam_client = session.client('iam')
    try:
        iam_client.create_account_alias(
            AccountAlias=account_short_name
        )
    except iam_client.exceptions.EntityAlreadyExistsException:
        logger.info(f"Alias {account_short_name} already exists. Continuing...")
        pass
    except:
        logger.error("ERROR creating alias %s" % account_short_name)
        raise
    else:
        logger.info("Account alias %s created" % account_short_name)
        return "SUCCESS"

def get_xaccount_session(account_id, role_name):
    # Role ARN here is created dynamically because the accounts can vary
    # This could be encapsulated in an ENV variable in it's entirety for a single other account
    role_arn = (f"arn:aws:iam::{account_id}:role/{role_name}")
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
    except Exception as e:
        logger.error("Error creating cross account IAM session.")
        raise Exception(f"Session creation error: {e}")
    else:
        logger.info(f"Cross-account role session created for account: {account_id}")
        return session

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
