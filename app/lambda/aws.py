import json
import boto3
import os
import base64
import logging

log_level = os.environ['log_level'] if 'log_level' in os.environ else "INFO"
logger = logging.getLogger()
logger.setLevel(log_level)
AWS_REGION = os.environ['AWS_REGION'] if 'AWS_REGION' in os.environ else 'us-west-2'

def get_secret(secret_name):
    """Get a secret from the AWS secret server.
        Args:
            secret_name (str): The name of the secret to obtain.
        Returns:
            val[secret_name] (str): The secret.
    """

    region_name = AWS_REGION

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
            secret = base64.standard_b64decode(get_secret_value_response['SecretBinary'])

    val = json.loads(secret)
    if val.get(secret_name):
        return val[secret_name]
    else:
        return val


def invoke_lambda(lambda_name, payload):
    """Invoke a Lambda
        Args:
            lambda_name (str): the name of the lambda to invoke
            payload (json): the event payload to send the lambda function
        Returns:
            lambda client invokation response
    """
    client = boto3.client('lambda')
    message = "Invoking lambda: %s" % lambda_name
    logger.info(message)
    try:
        response = client.invoke(
            FunctionName = lambda_name,
            InvocationType = 'Event',
            LogType = 'None',
            Payload = payload
        )
    except FunctionError:
        logger.error(FunctionError)
        return FunctionError
    else:
        logger.info(response)
        return response
