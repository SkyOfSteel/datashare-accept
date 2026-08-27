import boto3
from datetime import datetime, timedelta, timezone

session = boto3.Session(profile_name="governance", region_name="us-east-1")
rs = session.client("redshift")

GLUE_CATALOG = "arn:aws:glue:us-east-1:614518280298:catalog"
EXCLUDE = ("_bi_", "_fulfillment")
RECENT_DAYS = 7

def datashare_name(arn):
    # the name is the piece after the last "/" in the ARN
    return arn.split("/")[-1]

def is_accepted(associations):
    # True if any association is GLUE_CATALOG with Status == "ACTIVE"
    for assoc in associations:
        if assoc["Status"] == "ACTIVE" and assoc["ConsumerIdentifier"] == GLUE_CATALOG:
            return True
    return False

def invitation_date(associations):
    # the CreatedDate of the "DataCatalog/..." association
    try:
        for assoc in associations:
            if assoc["ConsumerIdentifier"].startswith("DataCatalog"):
                return assoc["CreatedDate"]
    except TypeError:
        print("TypeError: incorrect date type")

paginator = rs.get_paginator("describe_data_shares_for_consumer")
for page in paginator.paginate():
    for share in page["DataShares"]:
        arn = share["DataShareArn"]
        name = datashare_name(arn)
        # TODO filter 1: skip if name contains anything in EXCLUDE
        # TODO filter 2: skip if invitation_date is older than RECENT_DAYS
        # then print: name, arn, and "accepted" vs "NOT accepted"