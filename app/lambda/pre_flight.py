# Import 3rd party modules we need
import json
import logging
import os
import errors

# Logger configuration

log_level = os.environ['log_level'] if 'log_level' in os.environ else "INFO"
logger = logging.getLogger()
logger.setLevel(log_level)

# All functions related to pre-flight processing of the JSON payload

def input_validation(input, template):
    valid_keys= json.load(open(template, "r")).keys()
    input_keys = input.keys()
    for i in input_keys:
        if i in valid_keys:
            continue
        else:
            error = 'Unexpected JSON field: ' + i
            raise errors.BadRequest(error)
    logger.info("API input validation passed")

def input_grooming(input, template):
    result_dict = {}
    input_keys = input.keys()
    db_keys = json.load(open(template, "r")).keys()
    db_names = json.load(open(template, "r")).values()
    template_json = json.load(open(template, "r"))
    for i in input_keys:
        if i in db_keys:
            dict_key = template_json[i]
            result_dict[dict_key] = input[i]
    return result_dict
