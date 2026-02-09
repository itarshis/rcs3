# Import some necessary modules

import json
import boto3
import datetime
import os
import logging
import time

# Import custom modules modules for this app
import db

# Record runtime
now = datetime.datetime.now()
timestring = datetime.datetime.utcnow().strftime("%y%m%d%H%M%S")

# Configure logging
log_level = os.environ['log_level'] if 'log_level' in os.environ else "INFO"
logger = logging.getLogger()
logger.setLevel(log_level)

# Pull DB variables from environment variables in Lambda
DB_NAME = os.environ['db'] if 'db' in os.environ else 'cb_accounts'
DB_PORT = os.environ['db_port'] if 'db_port' in os.environ else '3306'
DB_USER = os.environ['db_user'] if 'db_user' in os.environ else 'lambda_user'
DB_HOST = os.environ['db_host'] if 'db_host' in os.environ else 'cbdb-dev.chtwvseqymaj.us-west-2.rds.amazonaws.com'
DB_SECRET = os.environ['db_secret'] if 'db_secret' in os.environ else 'cbdb-dev-sql_conn_pw'


def status_update(event, context):
    try:
        db_pass = get_secret(DB_SECRET)
        db_con = db.database_connect(DB_HOST, DB_USER, db_pass, DB_NAME, 'utf8')
        ad_status = event['ad_status']
        cbid = event["cbid"]
        try:
            update_cb_result = db.update_cb_record(cbid, 'account_status', ad_status, db_con )
        except:
            raise
        else:
            logger.info(update_cb_result)
            message = "SUCCESS: account_status successfully updated for %s" % cbid
            return response_handler('200', message)
    except:
        raise

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

def response_handler(status_code, message):
    response = {
        "isBase64Encoded": 'false',
        "statusCode": status_code,
        "body": json.dumps(message)
    }

    return response
