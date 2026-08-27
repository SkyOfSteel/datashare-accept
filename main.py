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
    for assoc in associations:
        if assoc["ConsumerIdentifier"].startswith("DataCatalog"):
            return assoc["CreatedDate"]
    return None

paginator = rs.get_paginator("describe_data_shares_for_consumer")

for page in paginator.paginate():
    for share in page["DataShares"]:
        arn = share["DataShareArn"]
        associations = share["DataShareAssociations"]
        name = datashare_name(arn)

        # filter 1: skip if name contains anything in EXCLUDE
        if any(filtered_value in name for filtered_value in EXCLUDE):
            continue

        # filter 2: skip if invitation_date is older than RECENT_DAYS
        created_date = invitation_date(associations)
        if created_date is None:
            continue
        cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
        if created_date < cutoff:
            continue

        # name, arn, and "accepted" vs "NOT accepted"
        status = "accepted" if is_accepted(associations) else "NOT accepted"
        print(f"{name} [{status}] {arn} Created on: {created_date}")