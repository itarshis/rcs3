
from cbADGroupDeploy import createGroup, populateGroup, updateGroupInfo
from cbuConnectAPI import uConnectAPI
from azure_rest import Azure
from aws import get_secret
from time import sleep
import iam_policies
import pprint
import uuid
import ddb
import os


def create_account(owner, billing_reader, displayname, alias, group_id, cbid, contributor=None, sub_id=None, account_type="Production"):
    
    ddb.updateAccountRecord(cbid, 'account_status', 'PENDING')
    # Seconds to sleep per iteration - the subscription creation takes a long time
    sleepytime = 20

    # Create AggieCloud groups for managing account data in the Accounts Management App
    # We need to get our populate our group list and retrieve creds for talking to th UC API
    UCONNECT_API_CREDS = os.environ['uconnect_api_creds']
    AD_CONTEXT = os.environ['ad_context'] if 'ad_context' in os.environ else 'dev'
    keys = get_secret(UCONNECT_API_CREDS)
    UCONNECT_API_PUBKEY = keys['adapi_public']
    UCONNECT_API_PRIVKEY = keys['adapi_private']
    UCONNECT_URL = keys['adapi_url']
    uc = uConnectAPI(pubkey=UCONNECT_API_PUBKEY,privkey=UCONNECT_API_PRIVKEY,url=UCONNECT_URL)
    account = ddb.getAccountRecord(cbid)

    azure_secret = os.environ['azure_secret']
    azure_secret_info = get_secret(azure_secret)
    azure_client_id = azure_secret_info.get('azure_client_id')
    azure_client_password = azure_secret_info.get('azure_client_password')
    azure_creator_account = azure_secret_info.get('azure_creator_account')
    azure_tenant_id = azure_secret_info.get('azure_tenant_id')
    azure_tenant_name = azure_secret_info.get('azure_tenant_name')
    azure_billing_account = azure_secret_info.get('azure_billing_account')
    azure_enrollment_id = azure_secret_info.get('azure_enrollment_id')

    a = Azure(client_id=azure_client_id, password=azure_client_password, tenant_id=azure_tenant_id, creator_account=azure_creator_account, tenant_name=azure_tenant_name, billing_account=azure_billing_account, enrollment_id=azure_enrollment_id)
    if type(billing_reader) is not list:
        raise Exception('billing_reader must be an array')

    # Get auth token for graph api
    try:
        a.graph_get_token()
    except:
        ddb.updateAccountRecord(cbid, 'account_status', 'TOKEN_ERROR')
        raise

    lookup_array = list()
    id_list = list()
    try:
        r_owner = a.graph_get_user(owner)
        pprint.pprint(r_owner.json())
        lookup_array.append([r_owner,'Owner'])
        if contributor:
            r_contrib = a.graph_get_user(contributor)
            lookup_array.append([r_contrib, 'Contributor'])
        r_bill = a.graph_get_user(billing_reader[0])
        pprint.pprint(r_bill.json())

        lookup_array.append([r_bill,'Billing Reader'])
    except:
        ddb.updateAccountRecord(cbid, 'account_status', 'ACCT_LOOKUP_ERROR')
        raise

    # Second billing reader is optional, and may not be a mailid. Ignore errors
    billing2_id = None
    if len(billing_reader) > 1:
        try:
            r_bill2 = a.graph_get_user(billing_reader[1])
            billing2_id = r_bill2.json().get('id')
        except:
            pass

    for r, name in lookup_array:
        if r.status_code != 200:
            if r.status_code == 404:
                print(f'{name} not found')
                return False
            else:
                r.raise_for_status()

    owner_id = r_owner.json().get('id')
    if not owner_id:
        ddb.updateAccountRecord(cbid, 'account_status', 'ACCT_LOOKUP_ERROR')
        raise Exception('owner_id not properly retrieved')
    id_list.append((owner_id, 'Owner'))

    if contributor:
        contrib_id = r_contrib.json().get('id')
        if not contrib_id:
            ddb.updateAccountRecord(cbid, 'account_status', 'ACCT_LOOKUP_ERROR')
            raise Exception('contrib_id not properly retrieved')
        id_list.append((contrib_id, 'Contributor'))

    billing_id = r_bill.json().get('id')
    if not billing_id:
        ddb.updateAccountRecord(cbid, 'account_status', 'ACCT_LOOKUP_ERROR')
        raise Exception('billing_id not properly retrieved')
    id_list.append((billing_id, 'Billing Reader'))


    # Get auth token for management api
    try:
        a.management_get_token()
    except:
        ddb.updateAccountRecord(cbid, 'account_status', 'TOKEN_ERROR')
        raise

    a.set_api_version('2020-09-01')
    if sub_id == None:
        try:
            sub_r = a.create_subscription(displayname=displayname, alias=alias, environment=account_type)
            sub_r_status = sub_r.status_code
        except:
            ddb.updateAccountRecord(cbid, 'account_status', 'CREATE_SUB_ERROR')
            raise

        j = sub_r.json()
        pprint.pprint(j)
        sub_id = j.get('properties', {}).get('subscriptionId')
        ddb.updateAccountRecord(cbid, 'account_id',
            sub_id)
        sub_state = j.get('properties', {}).get('provisioningState', '')
        if not sub_id:
            ddb.updateAccountRecord(cbid, 'account_status', 'SUBSCRIPTION_ERROR: no subscription id found')
            raise Exception(f'Failed to get subscription ID for {displayname}, {alias}')

        counter = 0
    else:
        print(f'Subscription ID {sub_id} already provided')
        ddb.updateAccountRecord(cbid, 'account_id',
            sub_id)
        ad_group_result = populateADGroups(cbid, uc)
        ddb.updateAccountRecord(cbid, 'account_status', 'COMPLETE')
        return
    if sub_r_status == 201:
        while counter <= 20:
            try:
                sub_r = a.get_subscription(sub_id, 'unmanaged')
                print(f'Subscription response: {sub_r}')
            except:
                if sub_r.status_code != 404:
                    #ddb.updateAccountRecord(cbid, 'account_status',
                    #        'SUBSCRIPTION_ERROR: get_sub failed while waiting for subscription to be fully created')
                    print(f'Subscription {sub_id} not available yet. Continuing')
                    #continue
            if sub_r.status_code == 200:
                print('\n\n\n\nfound subscription in unmanaged\n\n\n\n')
                print(sub_r.json())
                sleep(sleepytime)
                break
            print(f'get_subscription sub_r: {sub_r} {sub_r.json()}')
            sleep(sleepytime)
            counter += 1
        else:
            ddb.updateAccountRecord(cbid, 'account_status', 'SUBSCRIPTION_ERROR: Subscription not found')
            return
            
    print(f'Waited {counter * sleepytime} seconds for subscription')
    
    # Set management group
    try:
        add_sub_r = a.add_sub_to_management_group(sub_id, group_id)
    except:
        ddb.updateAccountRecord(cbid, 'account_status', 'SUBSCRIPTION_ERROR: add subscription to management group')
        raise
    print(f'add result: {add_sub_r.json()}')

    # Set Owner IAM rights
    guid = str(uuid.uuid4())
    try:
        owner_add_role_r = a.add_role(sub_id, owner_id, guid, a.owner_role)
    except:
        ddb.updateAccountRecord(cbid, 'account_status', 'ADD_ROLE_ERROR')
        raise

    print(f'\n\nSet owner role result: ')
    pprint.pprint(owner_add_role_r.json())

    # Set Contributor IAM rights
    if contributor: # contributor is optional
        guid = str(uuid.uuid4())
        try:
            add_role_r = a.add_role(sub_id, contrib_id, guid, a.contributor_role)
        except:
            ddb.updateAccountRecord(cbid, 'account_status', 'ADD_ROLE_ERROR')
            raise
        print(f'\n\nSet contributor role result: ')
        pprint.pprint(add_role_r.json())

    # Set Billing Reader IAM rights
    guid = str(uuid.uuid4())
    try:
        add_role_r = a.add_role(sub_id, billing_id, guid, a.billing_reader_role)
    except:
        ddb.updateAccountRecord(cbid, 'account_status', 'ADD_ROLE_ERROR')
        raise
    print(f'\n\nSet billing reader role result: ')
    pprint.pprint(add_role_r.json())

    # Second billing reader is optional, and may not be a mailid. Ignore errors
    if billing2_id:
        guid = str(uuid.uuid4())
        try:
            add_role_r2 = a.add_role(sub_id, billing2_id, guid, a.billing_reader_role)
            print(f'\n\nSet billing reader2 role result: ')
            pprint.pprint(add_role_r2.json())
        except Exception as e:
            print(f'Adding second Billing Reader failed: {e}')

    # Now verify that things are set properly
    # Check that subscription is in the right management group
    try:
        r = a.get_subscription(sub_id, group_id)
    except:
        ddb.updateAccountRecord(cbid, 'account_status', 'VERIFY_SUB_ERROR')
        raise
    if r.status_code != 200:
        ddb.updateAccountRecord(cbid, 'account_status', 'VERIFY_SUB_ERROR')
        raise Exception(f'Management group not set properly for subscription id {sub_id}')

    # Check role assignments -- ignoring 2nd billing reader
    role_dict = {}
    for id, name in id_list:
        try:
            r = a.get_role_assignment(sub_id, id) 
        except:
            ddb.updateAccountRecord(cbid, 'account_status', 'ROLE_ERROR')
            raise
        if r.status_code != 200:
            ddb.updateAccountRecord(cbid, 'account_status', 'ROLE_ERROR')
            raise Exception(f'Get of role for {name} (id {id}) failed')
        if not r.json()['value']:
            ddb.updateAccountRecord(cbid, 'account_status', 'ROLE_ERROR')
            raise Exception(f'Role for {name} (id {id}) not set')
        role_dict[name] = r.json()['value'][0]
        print(r)
    
    # Remove the creating account from an owner role in the newly created subscription
    # First we have to find the right role
    r = a.get_role_assignments_for_subscription(sub_id)
    print('role assignments by sub:\n\n\n\n')
    pprint.pprint(r.json())
    role_list = r.json()['value']
    for role in role_list:
        if role['properties']['principalId'] == a.creator_account:
            try:
                r = a.remove_role(role_id=role['id'])
            except:
                ddb.updateAccountRecord(cbid, 'account_status', 'REMOVE_ROLE_ERROR')
                raise

            print(f'remove role r: {r}')
            print(f'remove_role r json: {r.json()}')
            break
    
    ddb.updateAccountRecord(cbid, 'account_status', 'DEPLOYED')

    try:
        ad_group_result = populateADGroups(cbid, uc)
        pprint.pprint(f'AD Group Provisioning Result: {ad_group_result}')
        ddb.updateAccountRecord(cbid, 'account_status', 'COMPLETE')
        return sub_id
    except:
        ddb.updateAccountRecord(cbid, 'account_status', 'AD_GROUP_ERROR')
        raise
    
    


def populateADGroups(cbid, uc):
    group_list = [iam_policies.UCD_OWNER,
                  iam_policies.UCD_FULL_ADMIN,
                  iam_policies.UCD_BILLING_AZ,
                  iam_policies.UCD_READ_ONLY]
    account = ddb.getAccountRecord(cbid)
    for group in group_list:
        try:
            createGroup(group, account, uc, cbid)
            group_name = account['account_cloud'].upper() + '-' + \
                account['account_id'] + '-' + group
            pprint.pprint(f"Group {group_name} created successfully")
            sleep(10)
        except:
            ddb.updateAccountRecord(
                cbid, 'account_status', 'AD_GROUP_CREATE_ERROR')
            raise
        if iam_policies.UCD_OWNER == group:
            try:
                owner_mail = account['account_primary_admin']
                owner_group_r = populateGroup(owner_mail, group_name, uc, cbid)
                pprint.pprint(owner_group_r)
            except:
                ddb.updateAccountRecord(
                    cbid, 'account_status', 'AD_GROUP_CREATE_ERROR')
                raise
        elif iam_policies.UCD_BILLING_AZ == group:
            try:
                billing_email = account['ucd_budget_auth']
                billing_group_r = populateGroup(
                    billing_email, group_name, uc, cbid)
                pprint.pprint(billing_group_r)
                if account['account_billing_poc'] != "":
                    billing_poc_email = account['account_billing_poc']
                    billing_poc_group_r = populateGroup(
                        billing_poc_email, group_name, uc, cbid)
                    pprint.pprint(billing_poc_group_r)
                else:
                    pprint.pprint(
                        "Group provisioning process: no billing PoC")
            except:
                ddb.updateAccountRecord(
                    cbid, 'account_status', 'AD_GROUP_CREATE_ERROR')
                raise
        elif iam_policies.UCD_FULL_ADMIN == group:
            if account['account_technical_poc'] != "":
                try:
                    billing_email = account['account_technical_poc']
                    billing_group_r = populateGroup(
                        billing_email, group_name, uc, cbid)
                    pprint.pprint(billing_group_r)
                except:
                    ddb.updateAccountRecord(
                        cbid, 'account_status', 'AD_GROUP_CREATE_ERROR')
                    raise
            else:
                pprint.pprint("Group provisioning process: no technical PoC")       
    for group in group_list:
        group_name = account['account_cloud'].upper() + '-' + \
            account['account_id'] + '-' + group
        try:
            base = account['account_cloud'].upper() + '-' + account['account_id']
            description = f"Azure account access for role {group}"
            update_result = updateGroupInfo(
                group_name, account, group, description, base, uc, cbid)
            pprint.pprint(
                f"Group update result for {group_name}: {update_result}")
        except:
            ddb.updateAccountRecord(
                cbid, 'account_status', 'AD_GROUP_CREATE_ERROR')
            raise
        else:
            continue
    return
