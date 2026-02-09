from ruamel.yaml import YAML
from hashlib import sha1
from time import sleep
import functools
import requests
import pprint
import base64
import time
import hmac
import sys
import os
import re

file_path = os.path.dirname(os.path.realpath(__file__))

class DummyResponse:
    def __init__(self, status_code, json=None):
        self.status_code = status_code
        self.json = json

class uConnectAPI:
    def __init__(self, **kwargs): #config=None, test=False, pubkey=None, privkey=None, url=None):
        ''' If running in AWS, we'll likely set the keys via env vars, so we should
            allow passing them in here.
            Possible args: config (complete path to config file, or filename if in same dir)
                           test (True/False)
                           pubkey
                           privkey
                           url (url to API with trailing slash)
        '''
        print(f'uConnectAPI args: {kwargs}')
        self.pubkey = kwargs.get('pubkey')
        self.privkey = kwargs.get('privkey')
        self.url = kwargs.get('url')

        self.session = requests.Session()

    def cdec(func):
        """This is a decorator for all the API calls. It wraps the functions that call REST endpoints
            and transforms the result slightly. Because the requests.models.Response object is
            immutable, it makes the function call, gets the json from the request's result,
            transforms it slightly, and then returns the requests.models.Response and also the json.

            *** This is the reason all the below functions return (res, _json). ***

            Args:
                func: A function reference.
            Returns:
                res (requests.models.Response): Result of api request.
                _json (dict): slightly modified res.json()
        """

        @functools.wraps(func)
        def wrap(self, *args, **kwargs):
            # Check function name for type of call so we can auth properly
            # (auth depends on method type)
            if re.match('get_', func.__name__):
                method = 'GET'
            elif re.match('update_', func.__name__):
                method = 'PUT'
            elif re.match('patch_', func.__name__):
                method = 'PATCH'
            else:
                method = 'POST'

            self.do_auth(method=method)
            try:
                res = func(self, *args, **kwargs)
            except Exception as e:
                json = {'success': False,
                        'result': {},
                        'error': {'message': f'Exception caught trying to call API: {str(e)}'}
                       }
                res = DummyResponse(status_code=500, json=json)
                return (res, json)

            # Matt says 401s are handled by a different library so he can't return a body for those
            if res.status_code == 401:
                json = {'success': False,
                        'responseObject': {},
                        'error': {'message': 'Unauthorized'}
                       }
            elif res.status_code == 405:
                json = {'success': False,
                        'responseObject': {},
                        'error': {'message': 'Method not allowed'}
                       }
            else: # Anything other than 401 should have a body
                json = res.json()
            print(f"Response info: {json}")
            json['result'] = json.pop('responseObject')
            return (res, json)

        return wrap

    def do_auth(self, method='GET'):
        """Set up the auth headers needed for each request using the UTC timestamp,
           public key, and private key
            Args:
                method (str): The HTTP method, GET or POST.
            Returns:
                Nothing
        """
        unixtime = str(int(time.time()))
        self.session.headers.update({'X-UTIMESTAMP': unixtime})
        sig = f'{method}:{unixtime}:{self.pubkey}'
        digester = hmac.new(self.privkey.encode(), msg=sig.encode(), digestmod=sha1)
        signature = base64.b64encode(digester.digest())

        self.session.auth = (self.pubkey, signature)

        # Changing the content type should happen automatically if you
        # POST with the 'json=' method argument

    def status_check(self):
        """Do a health check. This URL bypasses auth. This method also doesn't use the 'cdec'
           decorator, so it just returns the requests call result.
            Args:
                None
            Returns:
                res (requests.models.Response): Result of api request.
        """
        return self.session.get(f'{self.url}LogicMonitorHealth')

    @cdec
    def get_user_by_samaccount(self, acct):
        """Get AD user info by samaccount (e.g. 'lizardo').
            Args:
                acct (str): samaccount name.
            Returns:
                res (requests.models.Response): Result of api request.
                _json (dict): slightly modified res.json()
        """
        return self.session.get(f'{self.url}AdUsers/sam/{acct}')

    @cdec
    def get_user_by_upn(self, upn):
        """Get AD user by UPN (userPrincipalName, e.g. brcamp@mail.t3.ucdavis.edu).
            Args:
                upn (str): User UPN.
            Returns:
                res (requests.models.Response): Result of api request.
                _json (dict): slightly modified res.json()
        """
        return self.session.get(f'{self.url}AdUsers/upn/{upn}')

    @cdec
    def get_user_by_guid(self, guid):
        """Get AD user using the AD user's guid.
            Args:
                guid (str): AD guid, e.g. 88110f5a-5e52-47fc-892f-008908e6eb3f
            Returns:
                res (requests.models.Response): Result of api request.
                _json (dict): slightly modified res.json()
        """
        return self.session.get(f'{self.url}AdUsers/guid/{guid}')

    @cdec
    def get_user_by_mail(self, mailid):
        """Get AD user using the users's mailid (with @ucdavis.edu)
            Args:
                mailid (str): UCD mailid with @ucdavis.edu
            Returns:
                res (requests.models.Response): Result of api request.
                _json (dict): slightly modified res.json()
        """
        return self.session.get(f'{self.url}AdUsers/mail/{mailid}')

    @cdec
    def get_user_by_email(self, mailid):
        """Get AD user using the users's mailid (with @ucdavis.edu)
            Args:
                mailid (str): UCD mailid with @ucdavis.edu
            Returns:
                res (requests.models.Response): Result of api request.
                _json (dict): slightly modified res.json()
        """
        return self.session.get(f'{self.url}AdUsers/email/{mailid}')

    @cdec
    def get_group_by_guid(self, guid):
        """Get AD group information with the group's guid.
            Args:
                guid (str): The group guid to look up.
            Returns:
                res (requests.models.Response): Result of api request.
                _json (dict): slightly modified res.json()
        """
        return self.session.get(f'{self.url}ManagedGroups/guid/{guid}')

    @cdec
    def get_group_by_dn(self, dn):
        """Get AD group information using the group's AD DN.
            Args:
                dn (str): The group's full DN
            Returns:
                res (requests.models.Response): Result of api request.
                _json (dict): slightly modified res.json()
        """
        return self.session.get(f'{self.url}ManagedGroups/dn/{dn}')

    @cdec
    def get_group_by_samaccount(self, acct):
        """Get AD group information using the group's samaccount as the lookup key.
            Args:
                acct (str): The group's samaccount.
            Returns:
                res (requests.models.Response): Result of api request.
                _json (dict): slightly modified res.json()
        """
        return self.session.get(f'{self.url}ManagedGroups/sam/{acct}')

    @cdec
    def get_group_members_by_guid(self, guid):
        """Get a list of a group's members using the group's AD guid as the lookup key.
            Args:
                guid (str): The group's guid.
            Returns:
                res (requests.models.Response): Result of api request.
                _json (dict): slightly modified res.json()
        """
        return self.session.get(f'{self.url}ManagedGroups/{guid}/members')

    @cdec
    def search_group(self, value=None, match_type='LIKE', property='ExtensionAttribute6'):
        """Search groups for a value in the given property.
            Args:
                value (str): The value to search for
                match_type (str): 'EQUALS' or 'LIKE'
                property (str): The group property to search in - currently only ExtensionAttribute6
            Returns:
                res (requests.models.Response): Result of api request.
                _json (dict): slightly modified res.json()
        """
        params = {  'property': property,
                    'value': value,
                    'matchType': match_type
        }
        return self.session.post(f'{self.url}ManagedGroups/search', json=params)


    @cdec
    def get_requests_by_guid(self, guid):
        """Check on a requestGuid to see if the request has been completed. Used
           when doing something other than a GET against AD and something needs to be
           updated/added/deleted.
            Args:
                guid (str): The request guid to check for completion.
            Returns:
                res (requests.models.Response): Result of api request.
                _json (dict): slightly modified res.json()
        """
        return self.session.get(f'{self.url}Requests/{guid}')

    @cdec
    def get_requests_log(self, guid):
        """Grab the log for a particular Requests GUID.
            Args:
                guid (str): The request guid
            Returns:
                res (requests.models.Response): Result of api request.
                _json (dict): slightly modified res.json()
        """
        return self.session.get(f'{self.url}Requests/{guid}/logs')

    @cdec
    def create_group(self, groupname, displayname=None, description=None, max_members=None,
                     extension=None):
        """Create an AD group.
            Args:
                groupname (str): The desired group name.
                displayname (str): Display name for the group (optional).
                max_members (int): Maximum members allowed (None or 0 for unlimited).
                extension (str): String to put into the group's extension attribute.
            Returns:
                res (requests.models.Response): Result of api request.
                _json (dict): slightly modified res.json()
        """
        if type(max_members) is str:
            max_members = int(max_members)
        data = {'groupName': groupname, 'displayName': displayname,
                'description': description, 'maxMembers': max_members,
                'extensionAttribute6': extension}

        return self.session.post(f'{self.url}ManagedGroups', json=data)

    @cdec
    def update_group_by_guid(self, guid, displayname=None, description=None, max_members=None,
                             extension=None):
        """Update an AD group. This will overwrite all of a group's data, not selectively update
           certain fields. Therefore you need to include all keyword args if you don't want them
           to be None in the group created.
            Args:
                guid (str): The group's AD GUID.
                groupname (str): The desired group name.
                displayname (str): Display name for the group (optional).
                max_members (int): Maximum members allowed (None or 0 for unlimited).
                extension (str): String to put into the group's extension attribute.
            Returns:
                res (requests.models.Response): Result of api request.
                _json (dict): slightly modified res.json()
        """
        if type(max_members) is str:
            max_members = int(max_members)
        data = {'displayName': displayname, 'description': description,
                'maxMembers': max_members, 'extensionAttribute6': extension}

        return self.session.put(f'{self.url}ManagedGroups/{guid}', json=data)

    @cdec
    def add_group_membership_by_guid(self, user_guid, group_guid):
        """Add an AD user to a group.
            Args:
                user_guid (str): An AD user's guid.
                group_guid (str): An AD group's guid
            Returns:
                res (requests.models.Response): Result of api request.
                _json (dict): slightly modified res.json()
        """
        data = {'userGuid': user_guid,
                'action': 'ADD'}
        return self.session.post(f'{self.url}ManagedGroups/{group_guid}/members',
                json=data)

    @cdec
    def remove_group_membership_by_guid(self, user_guid, group_guid):
        """Remove an AD user from a group.
            Args:
                user_guid (str): An AD user's guid.
                group_guid (str): An AD group's guid
            Returns:
                res (requests.models.Response): Result of api request.
                _json (dict): slightly modified res.json()
        """
        data = {'userGuid': user_guid,
                'action': 'REMOVE'}
        return self.session.post(f'{self.url}ManagedGroups/{group_guid}/members',
                json=data)

    def wait_for_request(self, request, tries=10, pause=.5):
        """Loop to wait for a request to finish.
           'request' can be a request guid found in the json of a request object,
           or a request.models.Response object itself.

           Return if we've tried 'tries' times
           already, if there's an error returned, if the status code is something
           other than 200, or if the call indicates the request is finished.

           If we've tried 'tries' times with no success, return the result of the
           last attempt to get the request status.

           Sleep 'pause' seconds after each attempt.

           Args:
                request (str or requests.models.Response): Something that contains the requestGuid.
                tries (int): How many times we should check for a successful request before giving up.
                pause (float): How long to pause between attempts.
           Returns:
                res (requests.models.Response): Result of api request.
                _json (dict): slightly modified res.json()
        """
        if type(request) is requests.models.Response:
            #print('request is Response type')
            try:
                json = request.json()
                guid = json['responseObject']['requestGuid']
            except:
                pass
            if request.status_code != 200 or json['success'] == False or not guid:
                return (request, None)

        elif type(request) is str:
            guid = request
        else:
            raise Exception('wait_for_request: unknown request type')

        while tries > 0:
            res, _json = self.get_requests_by_guid(guid)
            if res.status_code != 200:
                return (res, _json)
            err = _json.get('error')

            if err or _json['success'] == True:
                # Return on success or error
                return (res, _json)

            sleep(pause)
            tries -= 1

        return (res, _json)


if __name__ == '__main__':
    # API keys in the config file
    uc = uConnectAPI(config='uConnect_api.yml')
    print(uc)
    res = uc.status_check()
    print(res.content)
    print(res.status_code)
    sys.exit(0)
    projects_dn = 'OU=CB-DEV,OU=EPS,OU=DSM Recharge Projects,OU=IET,OU=DEPARTMENTS,DC=ou,DC=ad3,DC=ucdavis,DC=edu'
    res, json = uc.get_group_by_dn(projects_dn)
    print(f'group res: {res.content}')
