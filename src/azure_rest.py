#!/home/lizardo/git/cb-deploy-api/lambda/venv/bin/python3

from datetime import datetime
from ruamel.yaml import YAML
from pathlib import Path
from time import sleep
import requests
import argparse
import pprint
import sys
import re

file_path = Path('.').resolve()
sys.path.append(file_path)

class AzureBlob:
    def __init__(self, config='Azure-config.yml', section='subscriptions',
                 client_id=None, password=None, creator_account=None, billing_account=None):

        self.config = dict()
        self.owner_role = '8e3af657-a8ff-443c-a75c-2fe8c4bcb635'
        self.contributor_role = 'b24988ac-6180-42a0-ab88-20f7382dd24c'
        self.billing_reader_role = 'fa23ad8b-c56e-40d8-ac0c-ce449e1d2c64'
        self.billing_account = billing_account

        if client_id is not None and password is not None:
            self.config['client_id'] = client_id
            self.config['password'] = password
            self.creator_account = creator_account
        else:
            file = file_path / config
            with open(file, 'r') as ymlfile:
                yaml = YAML()
                self.config = yaml.load(ymlfile)[section]

        self.token = None
        self.auth_r = dict()
        self.session = requests.Session()
        self.session.headers.update({'ContentType': 'application/x-www-form-urlencoded'})
        print(self.session.params)
        self.uri = f'https://{self.billing_account}.blob.core.windows.net/'
        self.session.headers.update({'x-ms-version': '2019-12-12'})

    def get_containers(self, container=None):
        """Sadly, returns an XML document"""
        self.session.headers.update({'x-ms-date': datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')})
        container = re.sub(r'^/|/$', '', container)
        uri = f'{self.uri}{container}?restype=container&comp=list'
        r = self.session.get(uri)
        #print(f'r status_code: {r.status_code}')
        #print(f'r content: {r.content}')
        return r

    def get_blob_list(self, container='', prefix=None, delimiter=None):
        """Sadly, returns an XML document"""
        self.session.headers.update({'x-ms-date': datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')})
        container = re.sub(r'^/|/$', '', container)
        uri = f'{self.uri}{container}?restype=container&comp=list'
        if prefix:
            uri += f'&prefix={prefix}'
        if delimiter:
            uri += f'&delimiter={delimiter}'
        print(f'get_blob_list uri: {uri}')
        r = self.session.get(uri)
        return r

    def get_file(self, container='', file=None):
        self.session.headers.update({'x-ms-date': datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')})
        file = re.sub(r'^/', '', file)
        container = re.sub(r'^/|/$', '', container)
        uri = f'{self.uri}{container}/{file}'
        r = self.session.get(uri)
        return r

    def set_api_version(self, version):
        self.session.params.update({'api-version': version})

    def get_token(self):
        if self.token:
            # Ultimately should note time of token creation and TTL to see if we need to get a new one
            self.session.headers.update({'Authorization': f'{self.auth_r["token_type"]} {self.token}'})
            print('Using existing auth_token')
            return
        
        uri = 'https://login.microsoftonline.com/ucdavis365.onmicrosoft.com/oauth2/token'
        body = {
            'client_id': self.config['client_id'],
            'client_secret': self.config['password'],
            'grant_type': 'client_credentials',
            'resource': 'https://storage.azure.com/'
            }
        r = self.session.post(uri, data=body)
        if r.status_code != 200:
            raise Exception(f'get_token failed, status: {r.status_code}: {r.text}')

        self.auth_r = r.json()
        self.token = self.auth_r['access_token']
        self.token_type = self.auth_r['token_type']
        self.session.headers.update({'Authorization': f'{self.auth_r["token_type"]} {self.token}'})



class Azure:
    def __init__(self, config='Azure-config.yml', section='subscriptions',
                 client_id=None, password=None, tenant_id=None, creator_account=None, tenant_name=None, billing_account='299147', enrollment_id='83612694'):

        self.config = dict()
        #self.creator_account = '90a322d6-18a6-4f7d-877b-c6d54496a389'
        self.owner_role = '8e3af657-a8ff-443c-a75c-2fe8c4bcb635'
        self.contributor_role = 'b24988ac-6180-42a0-ab88-20f7382dd24c'
        self.billing_reader_role = 'fa23ad8b-c56e-40d8-ac0c-ce449e1d2c64'
        self.billing_account = billing_account
        self.enrollment_id = enrollment_id

        if client_id is not None and password is not None:
            self.config['client_id'] = client_id
            self.config['password'] = password
            self.creator_account = creator_account
            self.tenant_id = tenant_id
            self.tenant_name = tenant_name
        else:
            file = file_path / config
            with open(file, 'r') as ymlfile:
                yaml = YAML()
                self.config = yaml.load(ymlfile)[section]

        self.graph_token = None
        self.graph_auth_r = dict()
        self.management_token = None
        self.management_auth_r = dict()
        self.session = requests.Session()
        self.session.headers.update({'ContentType': 'application/x-www-form-urlencoded'})
        print(self.session.params)

    def graph_get_token(self):
        if self.graph_token:
            # Ultimately should note time of token creation and TTL to see if we need to get a new one
            self.session.headers.update({'Authorization': f'{self.graph_auth_r["token_type"]} {self.graph_token}'})
            print('Using existing graph_auth_token')
            return
        
        url = f'https://login.microsoftonline.com/{self.tenant_name}/oauth2/v2.0/token'
        body = {
            'client_id': self.config['client_id'],
            'client_secret': self.config['password'],
            'grant_type': 'client_credentials',
            'scope': 'https://graph.microsoft.com/.default',
            'api-version': '2020-09-01'
            }
        r = self.session.post(url, data=body)
        if r.status_code != 200:
            raise Exception(f'graph_get_token failed, status: {r.status_code}: {r.text}')
        else:
            print('Got graph_auth_token')

        self.graph_auth_r = r.json()
        print(self.graph_auth_r)
        self.graph_token = self.graph_auth_r['access_token']
        self.graph_token_type = self.graph_auth_r['token_type']
        self.session.headers.update({'Authorization': f'{self.graph_auth_r["token_type"]} {self.graph_token}'})

    def management_get_token(self):
        if self.management_token:
            # Ultimately should note time of token creation and TTL to see if we need to get a new one
            self.session.headers.update({'Authorization': f'{self.management_auth_r["token_type"]} {self.management_token}'})
            print('Using existing management_auth_token')
            return
        
        uri = f'https://login.microsoftonline.com/{self.tenant_id}/oauth2/token'
        body = {
            'client_id': self.config['client_id'],
            'client_secret': self.config['password'],
            'grant_type': 'client_credentials',
            'resource': 'https://management.core.windows.net/'
            }
        print(f'Auth info: {body}')
        r = self.session.post(uri, data=body)
        if r.status_code != 200:
            raise Exception(f'management_get_token failed, status: {r.status_code}: {r.text}')
        else:
            print('Got management_auth_token')

        self.management_auth_r = r.json()
        self.management_token = self.management_auth_r['access_token']
        self.management_token_type = self.management_auth_r['token_type']
        self.session.headers.update({'Authorization': f'{self.management_auth_r["token_type"]} {self.management_token}'})

    def get_subscription(self, subscription_id, group_id):
        self.set_api_version('2020-05-01')
        url = f'https://management.azure.com/providers/Microsoft.Management/managementGroups/{group_id}/subscriptions/{subscription_id}'
        print(f'url: {url}')
        r = self.session.get(url)
        print(r)
        if r.status_code != 200:
            #raise Exception(f'get_subscription failed, status: {r.status_code}: {r.text}')
            print(f'get_subscription failed, status: {r.status_code}: {r.text}')
        return r

    # Set api_version and Authorization before calling
    def create_subscription(self, displayname, alias, environment='Production'):
        # Allowed values for Workload are Production and DevTest
        self.set_api_version('2020-09-01')
        url = f'https://management.azure.com/providers/Microsoft.Subscription/aliases/{alias}'
        body = {
                 "properties": {
                    "billingScope": f"/providers/Microsoft.Billing/BillingAccounts/{self.enrollment_id}/enrollmentAccounts/{self.billing_account}",
                    "DisplayName": f"{displayname}",
                    "Workload": f"{environment}"
                  }
               }
        r = self.session.put(url, json=body)
        #r = self.session.put(url, data={'key':'value'})
        if r.status_code not in (200, 201):
            raise Exception(f'create_subscription for "{displayname}" failed, status: {r.status_code}: {r.text}')
        else:
            print(f'Created subscription {displayname}')
        
        print(f'subscription data: {r.json()}')
        return r

    def get_role_assignments_for_subscription(self, sub_id):
        scope = f'subscriptions/{sub_id}'
        self.set_api_version('2015-07-01')
        filter = 'atScope()'
        url = f'https://management.azure.com/{scope}/providers/Microsoft.Authorization/roleAssignments?$filter={filter}'

        r = self.session.get(url)
        if r.status_code != 200:
            raise Exception(f'get_fole_assignments_for_subscription failed, status: {r.status_code}: {r.text}')
        return r

    # Set api_version and Authorization before calling
    def add_sub_to_management_group(self, subscription_id, group_id):
        self.set_api_version('2020-05-01')
        url = f'https://management.azure.com/providers/Microsoft.Management/managementGroups/{group_id}/subscriptions/{subscription_id}'
        r = self.session.put(url)
        #if r.status_code != requests.codes.ok:
        if r.status_code not in (200, 201):
            raise Exception(f'Add subscription {subscription_id} to management group {group_id} failed, status: {r.status_code}: {r.text}')
        else:
            print(f'Added subscription {subscription_id} to {group_id}')
        
        return r

    def add_role(self, subscription_id, user_id, role_id_guid, role):
        self.set_api_version('2015-07-01')
        url = f'https://management.azure.com/subscriptions/{subscription_id}/providers/Microsoft.Authorization/roleAssignments/{role_id_guid}'
   
        body = {
            "properties": {
                "roleDefinitionId": f"/subscriptions/{subscription_id}/providers/Microsoft.Authorization/roleDefinitions/{role}",
                "principalId": user_id
            }
        }
        r = self.session.put(url, json=body)
        #if r.status_code != requests.codes.ok:
        if r.status_code not in (200, 201):
            if r.status_code != 409: # The role assignment already exists
                print('=' * 80)
                print(f'body: {r.request.body}')
                print(f'url: {r.request.url}')
                raise Exception(f'Set role (id {role_id_guid} failed for {subscription_id}, status: {r.status_code}: {r.text}')
        else:
            print(f'Set role {role_id_guid} for {subscription_id}')
        
        return r

    def remove_role(self, subscription_id=None, role_definition_id=None, scope=None, role_id=None):
        self.set_api_version('2015-07-01')
        scope = f'subscriptions/{subscription_id}'
        if scope and role_definition_id:
            url = f'https://management.azure.com/{scope}/providers/Microsoft.Authorization/roleAssignments/{role_definition_id}'
        elif role_id is not None:
            url = f'https://management.azure.com{role_id}'
        else:
            raise Exception(f'Remove role failed, not enough information provided')

        r = self.session.delete(url)
        print(f'remove role r: {r}')
        print(f'remove role text: {r.text}')
        pprint.pprint(f'remove_role json: {r.json()}')
        if r.status_code != 200:
            raise Exception(f'Remove role failed, status: {r.status_code}: {r.text}')
        else:
            print(f'Remove role {url} succeeded')
        
        return r


    def set_api_version(self, version):
        self.session.params.update({'api-version': version})


    def graph_get_user(self, UPN):
        url = f"https://graph.microsoft.com/v1.0/users/{UPN}"
        print(f'get_graph_user UPN: {UPN}')
        r = self.session.get(url)
        print(
            f"ClientId: {self.config['client_id']}. TenantId: {self.tenant_id}. ")
        if r.status_code != 200:
            raise Exception(f'graph_get_user failed, status: {r.status_code}: {r.text}')
        return r


    def get_role_assignment(self, subscription_id, object_id):
        self.set_api_version('2015-07-01')
        scope = f'subscriptions/{subscription_id}'
        filter = f"atScope()+and+assignedTo('{object_id}')"
        url = f'https://management.azure.com/{scope}/providers/Microsoft.Authorization/roleAssignments?$filter={filter}'
        r = self.session.get(url)
        if r.status_code != 200:
            raise Exception(f'get_role_assignment failed, status: {r.status_code}: {r.text}')
        return r


if __name__ == '__main__':
    from create_azure_sub import create_account
    a = Azure()
    a.management_get_token()
    #sys.exit(0)
    parser = argparse.ArgumentParser(description='Azure subscription adding tester')
    parser.add_argument('-a', '--alias', required=True)
    parser.add_argument('-d', '--displayname', required=True)
    parser.add_argument('-o', '--owner', required=True)
    parser.add_argument('-c', '--contributor', required=False, default=None)
    parser.add_argument('-b', '--billing_reader', required=True)
    parser.add_argument('--cbid', required=True)
    parser.add_argument('--group', required=False, default='AggieCloud')
    parser.add_argument('-t', '--check1', required=False, action='store_true')
    args = parser.parse_args()

    args.billing_reader = args.billing_reader.split(',')
    print(args.billing_reader)
    print(type(args.billing_reader))

    if args.check1:
        r = a.get_role_assignments_for_subscription('9c5d5055-7619-4f17-9c5a-450f0038da82')
        print(r.json())
        pprint.pprint(r.json(), indent=4)
        print(f'Count of role assignments: {len(r.json()["value"])}')
    else:
        create_account(args.owner, args.billing_reader, args.displayname, args.alias, args.group, args.cbid, args.contributor)