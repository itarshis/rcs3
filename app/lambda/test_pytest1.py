#
# I've been running this with the commandline of:
# pytest -x -s test_pytest1.py
#
from body import body # Body of post request to create test account
from time import sleep
import requests
import pprint
import pytest
import yaml
import sys
import re
import os

URLBASE = 'https://cb.api-dev.cloud.ucdavis.edu/test/'
CONFIG_FILE = 'pytest_config.yml'
STATUS_GOOD = 'COMPLETE'
STATUS_TRIES = 20 # How many times to try for a 'COMPLETE' status
STATUS_WAIT_TIME = 30 # Time between attempts to check status of account
account_id = None # Account ID global for delete test
api_key = os.environ['TEST_API_KEY']

# Get yaml config file data -- currently just api key
with open(CONFIG_FILE, 'r') as f:
    conf = yaml.safe_load(f)
api_key = conf['api_key']

headers = {'x-api-key': api_key}


def get_account_status(cbid):
    url = f'{URLBASE}cb-status'
    params = {'cbid': cbid}
    resp = requests.get(url, params=params, headers=headers)
    return resp

def create_account():
    url = f'{URLBASE}cb-deploy'

    # POST data to endpoint to create the account
    resp = requests.post(url, headers=headers, json=body)
    return resp

def delete_account(account_id):
    url = f'{URLBASE}cb-deploy'
    params = {'id': account_id}

    return requests.delete(url, params=params, headers=headers)

def wait_for_account(cbid):
    '''Loop, waiting for account to be created'''

    account_status = ''
    print('Account status:')
    # Loop on the account status until it's either all set, or we've looped too many times
    for i in range(0, STATUS_TRIES):
        status = get_account_status(cbid)
        status_json = status.json()
        account_status = status_json['account_info']['account_status']
        print(f'   {account_status}')
        if account_status == STATUS_GOOD:
            break
        # Account not ready. Take a nap, then try again
        sleep(STATUS_WAIT_TIME)
    
    return account_status, status_json

def test_create_account():
    global headers

    resp = create_account()
    j = resp.json()
    pprint.pprint(j)
    err = j.get('errorMessage', '')
    if 'CBID:' in err:
        m = re.search('CBID:\s*(.+)', err)
        r = get_account_status(m.group(1))
        print('Exiting account information:')
        pprint.pprint(r.json())
    assert resp.status_code == 200, 'Account creation response not 200'

    # Make sure deploy says it's successful
    deploy_status = j.get('body', {}).get('deploy_status')
    assert deploy_status == 'SUCCESS', 'Account creation does not indicate success'

    # Make sure we got a UUID back
    cbid = j.get('body', {}).get('message', {}).get('uuid')
    assert cbid is not None, 'No UUID found in account creation response'

    print('Account info:')
    pprint.pprint(j)

    # Wait until account is complete or we time out waiting for it to be complete
    account_status, status_json = wait_for_account(cbid)

    assert account_status == STATUS_GOOD, f'Account status is not "{STATUS_GOOD}"'

    account_id = status_json['account_info']['account_id']
    print(f'account_id: {account_id}')

    # We have to then delete the account so that the delete_account can create
    # the account so that it can test the delete. Not sure how this makes sense,
    # but...
    delete_account(account_id)


# Test account rollback
def test_delete_account():

    # Create an account to test rollback on
    resp = create_account()
    j = resp.json()

    assert resp.status_code == 200, f'Account creation response not 200 ({resp.status_code})'

    # Make sure deploy says it's successful
    deploy_status = j.get('body', {}).get('deploy_status')
    assert deploy_status == 'SUCCESS', 'Delete account test: Account creation does not indicate success'

    # Make sure we got a UUID back
    cbid = j.get('body', {}).get('message', {}).get('uuid')
    assert cbid is not None, 'Delete account test: No UUID found in account creation response'

    print('Account info:')
    pprint.pprint(j)

    # Wait until account is complete or we time out waiting for it to be complete
    account_status, status_json = wait_for_account(cbid)

    assert account_status == STATUS_GOOD, f'Delete account test: Created account status is not "{STATUS_GOOD}"'

    account_id = status_json['account_info']['account_id']
    
    # Now we can try the actual deletion
    resp = delete_account(account_id)
    j = resp.json()
    print('Delete response:')
    pprint.pprint(j)
    status = j.get('statusCode')
    assert status == 200, f'Delete account status is {status}'
    assert resp.status_code == 200, f'Delete resp.status_code is {resp.status_code}'



# Created this just in case the account exists and needs to be rolled back
if __name__ == '__main__':
    account_id = sys.argv[1]
    r = delete_account(account_id)
    pprint.pprint(r.json())