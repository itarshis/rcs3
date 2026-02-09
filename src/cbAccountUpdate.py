
from cbuConnectAPI import uConnectAPI
from botocore.exceptions import ClientError
import datetime
import logging
import boto3
import json
import os


# Import internal modules (TO DO: fix function naming to remove dashes)
sso = __import__("cb-account-sso-main",
                 fromlist=['get_xaccount_session', 'fetch_metadata'])
import ddb
import aws
from cbuConnectAPI import uConnectAPI

# Record runtime
now = datetime.datetime.now()
timeString = datetime.datetime.utcnow().strftime("%y%m%d%H%M%S")

# Declare some global variables
stsClient = boto3.client("sts")
roleName = "OrganizationAccountAccessRole"
accountCloud = 'aws'
currentAccount = stsClient.get_caller_identity()["Account"]

# Fetch ENV variables
LOG_LEVEL = os.environ['log_level'] if 'log_level' in os.environ else "INFO"
METADATA_BUCKET = os.environ['metadata_bucket'] if 'metadata_bucket' in os.environ else 'ira-cb-adfs-metadata'
UCONNECT_API_CREDS = os.environ['uconnect_api_creds']
BOILERPLATE = '<font size="-2">This email was sent to you as an enrollee in the AggieCloud AWS GuardDuty program. Your email address will not be used for any purpose other than notices and communications to support your use of this System<br /><br />Note: This email address is unmonitored.</font>'
SESCONFIGSET = os.environ['ses_config_set']
GD_WELCOME_TEMPLATE = os.environ['gd_welcome_template']
# Configure our logger
logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)

# We'll determine the scope of the maintenance here and kick off subordinate functions


def handler(event, context):
    logger.info(event)
    target = event['target']
    logger.info(f"Conducting maintenance based on {event}")
    if ('ou' in target) or  ('all' in target):
        if 'all' in target:
            logger.info(
                "Target ALL selected. Maintenance will run against entire organization.")
            orgClient = boto3.client('organizations')
            paginator = orgClient.get_paginator('list_accounts')
            pages = paginator.paginate(MaxResults=10)
        elif 'ou' in target:
            targetOu = event['target']['ou']
            logger.info(
                "Target OU selected. Maintenance will run against OU: %s." % targetOu)
            orgClient = boto3.client('organizations')
            paginator = orgClient.get_paginator('list_accounts_for_parent')
            pages = paginator.paginate(MaxResults=10, ParentId=targetOu)
        for page in pages:
            logger.debug(page)
            for account in page['Accounts']:
                try:
                    maintenanceHandler(account, event)
                except:
                    raise
    elif 'account' in target.keys():
        targetAccount = target['account']
        logger.info(
            "Target ACCOUNT selected. Maintenance will run against account: %s" % targetAccount)
        orgClient = boto3.client('organizations')
        account = orgClient.describe_account(
            AccountId=targetAccount
        )
        try:
            maintenanceHandler(account['Account'], event)
        except:
            raise
    else:
        targetError = "Target not recognized or not present"
        logger.error(targetError)
        raise ServerError(targetError)

# Function to select our mode, initiate cross-account creds and triage maintenance action


def maintenanceHandler(account, event):
    logger.debug(account)
    id = account['Id']
    email = account['Email']
    status = account['Status']
    name = account['Name']
    mode = event['component']
    logger.info("Maintenance %s will occur against account %s. Account name %s." % (
        mode, id, name))
    if currentAccount in id:
        logger.info(
            "Account %s %s is master. Will not perform maintenance." % (id, name))
        return
    else:
        try:
            session = sso.get_xaccount_session(id, roleName)
        except:
            sessionError = "Unable to instantiate admin session for account id %s" % id
            logger.warn(sessionError)
            return sessionError
        if 'saml_metadata' in mode:
            try:
                updateResponse = updateSAMLMetadata(id, session)
                logger.info(f"SAML update response: {updateResponse}")
            except:
                raise
            else:
                message = "Maintenance %s completed in account %s." % (
                    mode, id)
                logger.info(message)
                return message
        elif 'dry_run' in mode:
            try:
                dryRun(id, session)
            except:
                raise
            else:
                message = "Maintenance %s completed in account %s." % (
                    mode, id)
                logger.info(message)
                return message
        elif 'revoke_session' in mode:
            try:
                role = event['role']
                revokeResponse = revokeSession(role, session)
                logger.info(f'Revocation response: {revokeResponse}')
            except:
                raise
        elif 'guardduty_sns' in mode:
            try:
                guarddutySNSResponse = createGuardDutySNSTopic(
                    id, name, session)
                logger.info(f'GuardDuty SNS response: {guarddutySNSResponse}')
            except:
                raise
        elif 'guardduty_alert' in mode:
            try:
                region=event['gdRegion']
                guarddutyResponse = enableGuardDutyAlerts(id, name, session, region)
                logger.info(f'GuardDuty response: {guarddutyResponse}')
            except:
                raise
        elif 'guardduty_delete_sns' in mode:
            try:
                guarddutyRemovalResponse = deleteGuardDutySNSTopic(
                    id, name, session, os.environ['AWS_REGION']
                )
                logger.info(f'GuardDuty SNS removal response: {guarddutyRemovalResponse}')
            except:
                raise
        elif 'guardduty_delete_alert' in mode:
            try:
                region = event['gdRegion']
                guarddutyResponse = disableGuardDutyAlerts(id, name, session, region)
                logger.info(f'GuardDuty delete response: {guarddutyResponse}')
            except:
                raise
        elif 'guardduty_welcome' in mode:
            try:
                guarddutyEmailResponse = guarddutyWelcomeEmail(id)
                logger.info(f'GuardDuty delete response: {guarddutyEmailResponse}')
            except:
                raise
        else:
            componentError = "Requested component not recognized or not present"
            logger.error(componentError)
            raise ServerError(componentError)

########################################
# Maintenance functions ################
########################################

# Send Welcome email to GuardDuty clients
def guarddutyWelcomeEmail(targetAccount):
    try:
        keys = aws.get_secret(UCONNECT_API_CREDS)
        UCONNECT_API_PUBKEY = keys['adapi_public']
        UCONNECT_API_PRIVKEY = keys['adapi_private']
        UCONNECT_URL = keys['adapi_url']
        uc = uConnectAPI(pubkey=UCONNECT_API_PUBKEY,
                         privkey=UCONNECT_API_PRIVKEY, url=UCONNECT_URL)
    except:
      raise
    template = GD_WELCOME_TEMPLATE
    returnAddress = os.environ['email_return_address'] if 'email_return_address' in os.environ else 'itarshis@ucdavis.edu'
    logger.debug(f'Sending welcome email to {targetAccount} owners.')
    ownersGroup = f"AWS-{targetAccount}-UCD-Owner"
    ownersArray = []
    try:
      ownersRes, ownersBody = uc.get_group_by_samaccount(
          ownersGroup)
      ownersGuid = ownersBody['result']['objectGuid']
      ownersRes, ownersBody = uc.get_group_members_by_guid(
          ownersGuid)
      ownersMembers = ownersBody['result']
      logger.debug(f"Owner members result: {ownersMembers}")
      for owner in ownersMembers:
          logger.debug(f"Adding owner email address to array: {owner}")
          ownerInfoRes, ownerInfoBody = uc.get_user_by_guid(
              owner['objectGuid'])
          toAddress = ownerInfoBody['result']['mail']
          displayName = ownerInfoBody['result']['displayName']
          guarddutyTopic = f"GuardDuty Alerts - High Severity - {targetAccount}"
          logger.debug(
              f'Preparing to email owner {targetAccount} using template {template}. List of recipients: {toAddress}')
          sendEmail(template, returnAddress, toAddress, display_name=displayName, account_id=targetAccount, guardduty_sns_topic=guarddutyTopic, boilerplate=BOILERPLATE)
    except:
      raise

# Enable GuardDuty notifications
def createGuardDutySNSTopic(targetAccount, accountName, session):
    snsClient = session.client('sns')
    eventClient = session.client('events')
    iamClient = session.client('iam')
    cbid = ddb.checkForDupes(targetAccount, accountCloud)
    accounts = [ddb.getAccountRecord(cbid)]
    try:
        keys = aws.get_secret(UCONNECT_API_CREDS)
        UCONNECT_API_PUBKEY = keys['adapi_public']
        UCONNECT_API_PRIVKEY = keys['adapi_private']
        UCONNECT_URL = keys['adapi_url']
        uc = uConnectAPI(pubkey=UCONNECT_API_PUBKEY,
                          privkey=UCONNECT_API_PRIVKEY, url=UCONNECT_URL)
    except:
      raise
    try:
        for account in accounts:
            logger.info(
                f"Checking account {account} to determine if it's our target.")
            try:
                accountId = account['account_id']
                if (accountId == targetAccount):
                    logger.info(f'Target account {account} found.')
                    accountName = account['account_name']
                    ownersGroup = f"AWS-{accountId}-UCD-Owner"
                    ownersArray = []
                    try:
                      ownersRes, ownersBody = uc.get_group_by_samaccount(
                        ownersGroup)
                      ownersGuid = ownersBody['result']['objectGuid']
                      ownersRes, ownersBody  = uc.get_group_members_by_guid(
                          ownersGuid)
                      ownersMembers = ownersBody['result']
                      logger.debug(f"Owner members result: {ownersMembers}")
                      for owner in ownersMembers:
                          logger.debug(f"Owner in process: {owner}")
                          ownerInfoRes, ownerInfoBody = uc.get_user_by_guid(owner['objectGuid'])
                          ownersArray.append(ownerInfoBody['result']['mail'])
                      logger.debug(f'The following owners will be subscribed to the GuardDuty \
                        SNS topic for {accountId}: {ownersArray}')
                    except:
                      raise
                    accountName = account['account_name']
                    try:
                        SNSAccessPolicy = {
                            "Version": "2008-10-17",
                            "Id": "EventBridgeAccess",
                            "Statement": [
                                {
                                    "Sid": "EventBridgeAccess1",
                                    "Effect": "Allow",
                                    "Principal": {
                                        "Service": "events.amazonaws.com"
                                    },
                                    "Action": "SNS:Publish",
                                    "Resource": "*"
                                }
                            ]
                        }
                        topicResult = snsClient.create_topic(
                            Name=accountName + "-GuardDutyAggieCloudAlertHigh",
                            Attributes={
                                'DisplayName':f"GuardDuty Alerts - High Severity - {targetAccount}",
                                'Policy': json.dumps(SNSAccessPolicy)
                            }
                        )
                        logger.debug(f'Topic result: {topicResult}')
                        for m in ownersArray:
                          subResult = snsClient.subscribe(
                              TopicArn=topicResult['TopicArn'],
                              Protocol='email',
                              Endpoint=m
                          )
                          logger.debug(f'Sub result: {subResult}')
                        lowTopicResult = snsClient.create_topic(
                            Name=accountName + "-GuardDutyAggieCloudAlertLow",
                            Attributes={
                                'DisplayName': f"GuardDuty Alerts - Low Severity - {targetAccount}",
                                'Policy': json.dumps(SNSAccessPolicy)
                            }
                        )
                        logger.debug(f'Topic result: {lowTopicResult}')
                        try:
                            eventBusResult = eventClient.create_event_bus(
                                Name=accountName + "-GuardDutyAggieCloudSNSEventBus"
                            )
                            eventBusRole = iamClient.create_role(
                                RoleName=accountName + "-GuardDutyEventBridgeAccessRole",
                                Description="Role used to allow cross-region submission of GuardDuty alert events. Created by AggieCloud.",
                                AssumeRolePolicyDocument=json.dumps({
                                    "Version": "2012-10-17",
                                    "Statement": [
                                        {
                                            "Effect": "Allow",
                                            "Principal": {
                                                "Service": "events.amazonaws.com"
                                            },
                                            "Action": "sts:AssumeRole"
                                        }
                                    ]
                                })
                            )
                            eventBusPolicy = iamClient.create_policy(
                                PolicyName=accountName + "-GuardDutyEventBridgeAccessPolicy",
                                Description="Policy used to allow cross-region submission of GuardDuty alert events. Created by AggieCloud.",
                                PolicyDocument=json.dumps({
                                    "Version": "2012-10-17",
                                    "Statement": [
                                        {
                                            "Effect": "Allow",
                                            "Action": [
                                                "events:PutEvents"
                                            ],
                                            "Resource": [
                                                eventBusResult['EventBusArn']
                                            ]
                                        }
                                    ]
                                })
                            )
                            eventBusPolicyAttach=iamClient.attach_role_policy(
                                RoleName=eventBusRole['Role']['RoleName'],
                                PolicyArn=eventBusPolicy['Policy']['Arn']
                            )
                            logger.debug(f"Event bus role result: {eventBusRole}. Event bus policy result: {eventBusPolicy}.")
                            eventBusPermissions = eventClient.put_permission(
                                EventBusName=accountName + "-GuardDutyAggieCloudSNSEventBus",
                                Action="events:PutEvents",
                                Principal=targetAccount,
                                StatementId="GuardDutyAggieCloudPermissions"
                            )
                            logger.debug(f"Event bus result: {eventBusResult}. Event bus permissions result: {eventBusPermissions}")
                            ruleName = accountName + "-GuardDutyAlerts-High"
                            ruleResult = eventClient.put_rule(
                                Name=ruleName,
                                EventPattern='{ "source": ["aws.guardduty"], "detail": { "severity": [4, 4.0, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 5, 5.0, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.7, 5.8, 5.9, 6, 6.0, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 7, 7.0, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 8, 8.0, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9] } }',
                                State='ENABLED',
                                EventBusName=eventBusResult['EventBusArn']
                            )
                            logger.debug(f'Rule result: {ruleResult}')
                            targetResult = eventClient.put_targets(
                                Rule=ruleName,
                                EventBusName=eventBusResult['EventBusArn'],
                                Targets=[
                                    {
                                        'Id': ruleName + '-SNS-Target',
                                        'Arn': topicResult['TopicArn'],
                                        'InputTransformer': {
                                            'InputPathsMap': {
                                                "severity": "$.detail.severity",
                                                "Finding_ID": "$.detail.id",
                                                "eventFirstSeen": "$.detail.service.eventFirstSeen",
                                                "eventLastSeen": "$.detail.service.eventLastSeen",
                                                "count": "$.detail.service.count",
                                                "Finding_Type": "$.detail.type",
                                                "region": "$.region",
                                                "Finding_description": "$.detail.description",
                                                "Account_Id": "$.detail.accountId"
                                            },
                                            'InputTemplate': "\"An AWS account assocaited with you (<Account_Id>) has received a severity <severity> GuardDuty finding of type <Finding_Type> in the region <region>.\""
                                                             "\"--- Finding details: <Finding_description>.\""
                                                             "\"--- The first occurrence was on <eventFirstSeen> and the most recent occurrence on <eventLastSeen>. The total occurrence is <count>.\""
                                                             "\"--- For more details open the GuardDuty console at https://console.aws.amazon.com/guardduty/home?region=<region>#/findings?search=id%3D<Finding_ID>.\""
                                        }
                                    }
                                ]
                            )
                            logger.debug(f'Target result: {targetResult}')
                            lowRuleName = accountName + "-GuardDutyAlerts-Low"
                            lowRuleResult = eventClient.put_rule(
                                Name=lowRuleName,
                                EventPattern='{ "source": ["aws.guardduty"], "detail": { "severity": [1, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2, 2.0, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.7, 2.8, 2.9, 3, 3.0, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9] } }',
                                State='ENABLED',
                                EventBusName=eventBusResult['EventBusArn']
                            )
                            lowTargetResult = eventClient.put_targets(
                                Rule=lowRuleName,
                                EventBusName=eventBusResult['EventBusArn'],
                                Targets=[
                                    {
                                        'Id': lowRuleName + '-SNS-Target',
                                        'Arn': lowTopicResult['TopicArn'],
                                        'InputTransformer': {
                                            'InputPathsMap': {
                                                "severity": "$.detail.severity",
                                                "Finding_ID": "$.detail.id",
                                                "eventFirstSeen": "$.detail.service.eventFirstSeen",
                                                "eventLastSeen": "$.detail.service.eventLastSeen",
                                                "count": "$.detail.service.count",
                                                "Finding_Type": "$.detail.type",
                                                "region": "$.region",
                                                "Finding_description": "$.detail.description",
                                                "Account_Id": "$.detail.accountId"
                                            },
                                            'InputTemplate': "\"An AWS account assocaited with you (<Account_Id>) has received a severity <severity> GuardDuty finding of type <Finding_Type> in the region <region>.\""
                                                             "\"--- Finding details: <Finding_description>.\""
                                                             "\"--- The first occurrence was on <eventFirstSeen> and the most recent occurrence on <eventLastSeen>. The total occurrence is <count>.\"" 
                                                             "\"--- For more details open the GuardDuty console at https://console.aws.amazon.com/guardduty/home?region=<region>#/findings?search=id%3D<Finding_ID>.\""
                                        }
                                    }
                                ]
                            )
                            logger.debug(f'Target result: {lowTargetResult}')
                        except:
                            raise
                        finally:
                          guarddutyEmailResponse = guarddutyWelcomeEmail(targetAccount)
                          logger.info(
                              f'GuardDuty welcome email response: {guarddutyEmailResponse}')
                        return
                    except:
                        raise
                else:
                    logger.info(f'Account {accountId} is not our target.')
            except KeyError:
                continue
        logger.error(f'Account {targetAccount} not found in the CB Info')
    except:
        raise


# Disable GuardDuty Alerts
def deleteGuardDutySNSTopic(targetAccount, accountName, session, region):
    accounts = []
    snsClient = session.client('sns')
    eventClient = session.client('events')
    iamClient = session.client('iam')
    cbid = ddb.checkForDupes(targetAccount, accountCloud)
    accounts = [ddb.getAccountRecord(cbid)]
    logger.debug(f"Account query result: {accounts}")
    try:
        for account in accounts:
            logger.info(
                f"Checking account {account} to determine if it's our target.")
            try:
                accountId = account['account_id']
                if (accountId == targetAccount):
                    logger.info(f'Target account {account} found.')
                    accountName = account['account_name']
                    try:
                        logger.debug("Deleting high severity topic")
                        highTopicDelete = snsClient.delete_topic(
                            TopicArn=f"arn:aws:sns:{region}:{accountId}:{accountName}-GuardDutyAggieCloudAlertHigh"
                        )
                        logger.debug(f'Topic result: {highTopicDelete}')
                        lowTopicDelete = snsClient.delete_topic(
                            TopicArn=f"arn:aws:sns:{region}:{accountId}:{accountName}-GuardDutyAggieCloudAlertLow"
                        )
                        logger.debug(f'Topic result: {lowTopicDelete}')
                        try:
                            try:
                                eventBusDetach = iamClient.detach_role_policy(
                                    RoleName=accountName + "-GuardDutyEventBridgeAccessRole",
                                    PolicyArn=f"arn:aws:iam::{accountId}:policy/{accountName}-GuardDutyEventBridgeAccessPolicy"
                                )
                                eventBusRole = iamClient.delete_role(
                                    RoleName=accountName + "-GuardDutyEventBridgeAccessRole"
                                )
                            except iamClient.exceptions.NoSuchEntityException as err:
                                logger.debug("IAM role not present proceeding with the rest of removal")
                                pass
                            finally:
                                try:
                                    eventBusPolicy = iamClient.delete_policy(
                                        PolicyArn=f"arn:aws:iam::{accountId}:policy/{accountName}-GuardDutyEventBridgeAccessPolicy"
                                    )
                                except iamClient.exceptions.NoSuchEntityException as err:
                                    logger.debug("IAM Policy not present proceeding with the rest of removal")
                                    pass
                                ruleName = accountName + "-GuardDutyAlerts-High"
                                eventBus = accountName + "-GuardDutyAggieCloudSNSEventBus"
                                try:
                                    targetList = eventClient.list_targets_by_rule(
                                        Rule=ruleName,
                                        EventBusName=eventBus
                                    )
                                    for target in targetList['Targets']:
                                        logger.debug(f"Removing target {target}")
                                        eventClient.remove_targets(
                                            Rule=ruleName,
                                            EventBusName=eventBus,
                                            Ids=[
                                                target['Id']
                                            ],
                                            Force=True
                                        )
                                    ruleResult = eventClient.delete_rule(
                                        Name=ruleName,
                                        EventBusName=eventBus,
                                        Force=True
                                    )
                                    logger.debug(f'High rule delete result: {ruleResult}')
                                except eventClient.exceptions.ResourceNotFoundException as err:
                                    logger.debug(
                                        "High priority event rule not present proceeding with the rest of removal")
                                    pass
                                try:
                                    lowRuleName = accountName + "-GuardDutyAlerts-Low"
                                    targetList = eventClient.list_targets_by_rule(
                                        Rule=lowRuleName,
                                        EventBusName=eventBus
                                    )
                                    for target in targetList['Targets']:
                                        logger.debug(f"Removing target {target}")
                                        eventClient.remove_targets(
                                            Rule=lowRuleName,
                                            EventBusName=eventBus,
                                            Ids=[
                                                target['Id']
                                            ],
                                            Force=True
                                        )
                                    lowRuleResult = eventClient.delete_rule(
                                        Name=lowRuleName,
                                        EventBusName=accountName + "-GuardDutyAggieCloudSNSEventBus",
                                        Force=True
                                    )
                                    logger.debug(
                                        f'Low rule delete result: {lowRuleResult}')
                                except eventClient.exceptions.ResourceNotFoundException as err:
                                    logger.debug(
                                        "Low priority event rule not present proceeding with the rest of removal")
                                    pass
                                try:
                                    eventBusResult = eventClient.delete_event_bus(
                                        Name=accountName + "-GuardDutyAggieCloudSNSEventBus"
                                    )
                                    logger.debug(f"Event bus removal result: {eventBusResult}")
                                except eventClient.exceptions.ResourceNotFoundException as err:
                                    logger.debug(
                                        "Event bus not present proceeding with the rest of removal")
                                    pass
                        except:
                            raise
                        return
                    except:
                        raise
                else:
                    logger.info(f'Account {accountId} is not our target.')
            except KeyError:
                continue
        logger.error(f'Account {targetAccount} not found in the CB Info')
    except:
        raise

# Enable GuardDuty regional EventBridge rules
def enableGuardDutyAlerts(targetAccount, accountName, session, region):
    eventClient = session.client('events', region_name=region)
    cbid = ddb.checkForDupes(targetAccount, accountCloud)
    accounts = [ddb.getAccountRecord(cbid)]
    try:
        for account in accounts:
            accountName = account['account_name']
            snsEventRouter = "arn:aws:events:us-west-2:" + targetAccount + \
                ":event-bus/" + accountName + "-GuardDutyAggieCloudSNSEventBus"
            eventBusRoleArn = "arn:aws:iam::" + targetAccount + ":role/" + accountName + "-GuardDutyEventBridgeAccessRole"
            logger.info(f"Checking account {account} to determine if it's our target.")
            try:
                accountId = account['account_id']
                if (accountId == targetAccount):
                    logger.info(f'Target account {account} found.')
                    accountName= account['account_name']
                    try:
                        ruleName = accountName + "-GuardDutyAlerts"
                        ruleResult = eventClient.put_rule(
                            Name=ruleName,
                            EventPattern='{ "source": ["aws.guardduty"] }',
                            State='ENABLED'
                        )
                        logger.debug(f'Rule result: {ruleResult}')
                        targetResult = eventClient.put_targets(
                            Rule=ruleName,
                            Targets=[{
                                'Id': accountName + "SNS-Event-Router",
                                'Arn': snsEventRouter,
                                'RoleArn': eventBusRoleArn
                            }]
                        )
                        logger.debug(f"Topic result {targetResult}")
                        return
                    except:
                        raise
                else:
                    logger.info(f'Account {accountId} is not our target.')
            except KeyError:
                continue
        logger.error(f'Account {targetAccount} not found in the CB Info')
    except:
        raise

# Disable GuardDuty regional EventBridge rules
def disableGuardDutyAlerts(targetAccount, accountName, session, region):
    eventClient = session.client('events', region_name=region)
    accounts = ddb.getAccountsByStatus('COMPLETE')
    try:
        for account in accounts:
            logger.info(
                f"Checking account {account} to determine if it's our target.")
            try:
                accountId = account['account_id']
                if (accountId == targetAccount):
                    logger.info(f'Target account {account} found.')
                    accountName = account['account_name']
                    ruleName = accountName + "-GuardDutyAlerts"
                    try:
                        targetList = eventClient.list_targets_by_rule(
                            Rule=ruleName
                        )
                        for target in targetList['Targets']:
                            logger.debug(f"Removing target {target}")
                            targetResult = eventClient.remove_targets(
                                Rule=ruleName,
                                Ids=[
                                    target['Id']
                                ],
                                Force=True
                            )
                            logger.debug(f"Topic result {targetResult}")
                    except eventClient.exceptions.ResourceNotFoundException as err:
                        logger.debug(
                            f"Event bus not present proceeding with the rest of removal. {err}")
                        pass
                    try:
                        ruleResult = eventClient.delete_rule(
                            Name=ruleName,
                            Force=True
                        )
                        logger.debug(f'Rule delete result: {ruleResult}')
                        return
                    except eventClient.exceptions.ResourceNotFoundException as err:
                        logger.debug(
                            "Event bus not present proceeding with the rest of removal")
                        pass
                    except:
                        raise
                else:
                    logger.info(f'Account {accountId} is not our target.')
            except KeyError:
                continue
        logger.error(f'Account {targetAccount} not found in the CB Info')
    except:
        raise

# Update SAML Metadata
def updateSAMLMetadata(accountId, session):
    samlMetadata = sso.fetch_metadata(METADATA_BUCKET)
    logger.info("Updating SAML metadata for %s" % accountId)
    logger.debug("SAML Metadata: %s" % samlMetadata)
    logger.debug("Session info: %s" % session)
    iamClient = session.client('iam')
    samlArn = "arn:aws:iam::%s:saml-provider/ucd-adfs" % accountId
    logger.debug("SAML Arn: %s" % samlArn)
    try:
        metadataUpdateResult = iamClient.update_saml_provider(
            SAMLMetadataDocument=samlMetadata,
            SAMLProviderArn=samlArn
        )
        logger.info("Metadata update result: %s" % metadataUpdateResult)
        return metadataUpdateResult
    except iamClient.exceptions.NoSuchEntityException:
        logger.warn(
            "SAML Provider not found in account %s. Will require investigation." % accountId)
    except ClientError as e:
        logger.error("There was an error updating SAML provider: %s" % e)
        raise e

# Dry run to test cross-account access
def dryRun(accountId, session):
    logger.info("Dry run initializing")
    logger.debug("Session info: %s" % session)
    iamClient = session.client('iam')
    samlArn = "arn:aws:iam::%s:saml-provider/ucd-adfs" % accountId
    logger.debug("SAML Arn: %s" % samlArn)
    try:
        dryRunResult = iamClient.get_saml_provider(
            SAMLProviderArn=samlArn
        )
        logger.debug("Dry run result: %s" % dryRunResult)
        return dryRunResult
    except ClientError as e:
        logger.error("There was an error fetching SAML provider: %s" % e)
        return e

# Revoke client sessions
def revokeSession(roleName, session):
    iamClient = session.client('iam')
    nowTime = now.isoformat()
    logger.info(f"Revocation time: {nowTime}")

    iamPolicy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Deny",
                "Action": [
                    "*"
                ],
                "Resource": [
                    "*"
                ],
                "Condition": {
                    "DateLessThan": {
                        "aws:TokenIssueTime": nowTime
                    }
                }
            }
        ]
    }
    try:
        iamResult = iamClient.put_role_policy(
            RoleName=roleName,
            PolicyName="RevokeSessions",
            PolicyDocument=json.dumps(iamPolicy)
        )
        logger.debug(iamResult)
    except ClientError as e:
        logger.error(f"There was an error revoking sessions:{e}")
        return e


def sendEmail(template, returnAddress, toAddress, **kwargs):
    try:
        templateData = json.dumps(kwargs)
        # templateData = json.loads(templateData)
        # template_data.update({"client_name": clientName})
        # template_data.update({"client_address": clientAddress})
        # template_data.update({"client_phone": clientPhone})
        # template_data.update({"boilerplate": emailBoilerplate})
        # templateData = json.dumps(templateData)
        ses = boto3.client('ses')

        email_response = ses.send_templated_email(
            Source=returnAddress,
            Destination={
                'ToAddresses': [toAddress],
                'CcAddresses': [],
                'BccAddresses': [returnAddress]
            },
            ReplyToAddresses=[returnAddress],
            ReturnPath=returnAddress,
            Template=template,
            TemplateData=templateData,
            ConfigurationSetName=SESCONFIGSET
        )
    except ses.exceptions.MessageRejected as err:
        logger.error(
            f"Sending welcome email to {toAddress} rejected. Error: {err}.")
        pass
    except:
        raise
    else:
        logger.info(
            f'Operation complete. Email sent. Response: {email_response}')

# Class for raising custom errors
class ServerError(Exception):
    pass
