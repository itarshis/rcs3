# Import 3rd party modules needed for the app

import create_azure_sub
import datetime
import logging
import os


# Import custom modules modules for this app
import create_azure_sub
import ddb

# Record runtime
now = datetime.datetime.now()
timestring = datetime.datetime.utcnow().strftime("%y%m%d%H%M%S")

# Configure logging
log_level = os.environ['log_level'] if 'log_level' in os.environ else "DEBUG"
logger = logging.getLogger()
logger.setLevel(log_level)

def handler(event, context):
    logger.info(event)
    owner = event['owner_upn']
    azure_billing_reader = [event['ucd_budget_auth'], event['account_billing_poc']]
    azure_display_name = event['azure_display_name']
    azure_alias = event['azure_alias']
    azure_management_group = event['azure_management_group']
    cbid = event['cbid']
    contributor = event['contributor_upn']
    sub_id = event['sub_id']
    account_type = event['azure_account_type']

    if azure_management_group == "College of Agricultural and Environmental Sciences":
        azure_management_group_id = "CAES"
    else:
        azure_management_group_id = "AggieCloud"

    try:
        sub_id = create_azure_sub.create_account(
            owner, azure_billing_reader, azure_display_name, azure_alias, azure_management_group_id, cbid, contributor, sub_id, account_type)
        return
    except:
        raise
