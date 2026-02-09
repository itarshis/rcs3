import os
import json
import boto3
import errors
import logging
from boto3.dynamodb.conditions import Attr, Key

log_level = os.environ['log_level'] if 'log_level' in os.environ else "INFO"
logger = logging.getLogger()
logger.setLevel(log_level)
AWS_REGION = os.environ['AWS_REGION'] if 'AWS_REGION' in os.environ else 'us-west-2'

DDB_NAME = os.environ['ddb_name'] if 'ddb_name' in os.environ else 'test-aggiecloud-accounts'

def insertNewAccountRecord(data):
    """
    Create new account records in the dynamoDB database
    """
    ddb = boto3.resource('dynamodb')
    ddbTable = ddb.Table(DDB_NAME)
    try:
        createResult = ddbTable.put_item(Item=data)
        logger.info(f'Account record creation result: {createResult}')
    except:
        raise


def updateAccountRecord(cbid, fieldName, fieldValue, new="false"):
    """
    Update some attribute of the ddb record
    """
    ddb = boto3.resource('dynamodb', region_name=AWS_REGION)
    ddbTable = ddb.Table(DDB_NAME)
    if (new == "false"):
        updateExp = f'SET {fieldName} = :fv'
    elif (new == "true"):
        updateExp = f'ADD {fieldName} = :fv'
    else:
        logger.error(f'Failed to update {fieldName} because type of update unspecified')
    try:
        logger.info(f'Updating attribute {fieldName} to {fieldValue}')
        updateResult = ddbTable.update_item(
            Key={"cbid": cbid}, UpdateExpression=updateExp, ExpressionAttributeValues={":fv":fieldValue})
        logger.info(f'Update result: {updateResult}')
    except:
        raise

def getAccountRecord(cbid):
    """
    Search the database for duplicate account_ids
    """
    ddb = boto3.resource('dynamodb')
    ddbTable = ddb.Table(DDB_NAME)
    try:
        queryResult = ddbTable.query(
            KeyConditionExpression=Key('cbid').eq(cbid)
        )
        logger.info(f"Query result: {queryResult}")
        resultLen = len(queryResult['Items'])
        logger.info(f'Query result length: {resultLen}')
        resultItems = queryResult['Items']
        for r in resultItems:
            r.pop('ordid', None)
            r.pop('account_est_spend', None)
            r.pop('cb_new_account', None)
            r.pop('is_test', None)
        if resultLen == 1:
            return resultItems[0]
        elif resultLen == 0:
            raise errors.ServerError(
                f"Error record not found by CBID {cbid}")
        elif resultLen > 1:
            raise errors.ServerError(
                "Error in database: multiple entries for same account.")
    except:
        raise

def checkForDupes(account_id, account_cloud):
    """
    Search the database for duplicate account_ids
    """
    ddb = boto3.resource('dynamodb')
    ddbTable = ddb.Table(DDB_NAME)
    try:
        queryResult = ddbTable.scan(
            FilterExpression=
                Attr('account_id').eq(account_id) & Attr('account_cloud').eq(account_cloud)
            )
        logger.info(f"Query result: {queryResult}")
        resultLen = len(queryResult['Items'])
        logger.info(f'Query result length: {resultLen}')
        if resultLen == 1:
            return queryResult['Items'][0]['cbid']
        elif resultLen == 0:
            return "CHECK_PASSED"
        elif resultLen > 1:
            raise errors.ServerError(
                "Error in database: multiple entries for same account.")
    except:
        raise

def getAccountsByStatus(status):
    """
    Search the database for duplicate account_ids
    """
    ddb = boto3.resource('dynamodb')
    ddbTable = ddb.Table(DDB_NAME)
    try:
        queryResult = ddbTable.scan(
            FilterExpression=
                Attr('account_status').eq(status)
            )
        logger.info(f"Query result: {queryResult}")
        resultLen = len(queryResult['Items'])
        logger.info(f'Query result length: {resultLen}')
        resultItems = queryResult['Items']
        for r in resultItems:
            r.pop('ordid', None)
            r.pop('account_est_spend', None)
            r.pop('cb_new_account', None)
            r.pop('is_test', None)
        return resultItems

    except:
        raise

def deleteAccountRecord(cbid):
    """
    Delete an account record by CBID
    """
    ddb = boto3.resource('dynamodb')
    ddbTable = ddb.Table(DDB_NAME)
    try:
        deleteResult = ddbTable.delete_item(
            Key={
                'cbid': cbid
            })
        logger.info(f"Query result: {deleteResult}")
        return deleteResult
    except:
        raise
