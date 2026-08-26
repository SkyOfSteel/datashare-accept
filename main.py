import boto3
from datetime import datetime, timedelta, timezone

session = boto3.Session(profile_name="governance", region_name="us-east-1")
rs = session.client("redshift")

GLUE_CATALOG = "arn:aws:glue:us-east-1:614518280298:catalog"
EXCLUDE = ("_bi_", "_fulfillment")
RECENT_DAYS = 7

def datashare_name(arn):
    # TODO: the name is the piece after the last "/" in the ARN
    ...

def is_accepted(associations):
    # TODO: True if any association is GLUE_CATALOG with Status == "ACTIVE"
    ...

def invitation_date(associations):
    # TODO: the CreatedDate of the "DataCatalog/..." association
    ...

paginator = rs.get_paginator("describe_data_shares_for_consumer")
for page in paginator.paginate():
    for share in page["DataShares"]:
        arn = share["DataShareArn"]
        name = datashare_name(arn)
        # TODO filter 1: skip if name contains anything in EXCLUDE
        # TODO filter 2: skip if invitation_date is older than RECENT_DAYS
        # then print: name, arn, and "accepted" vs "NOT accepted"