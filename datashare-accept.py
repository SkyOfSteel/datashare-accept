import boto3
from datetime import datetime, timedelta, timezone

session = boto3.Session(profile_name="governance", region_name="us-east-1")
rs = session.client("redshift")

account_id = session.client("sts").get_caller_identity()["Account"]     # which key holds the account?
GLUE_CATALOG = f"arn:aws:glue:{session.region_name}:{account_id}:catalog"
EXCLUDE = ("_bi_", "_fulfillment")
RECENT_DAYS = 400

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

glue = session.client("glue")

# ARNs of datashares that already have a federated database (= already done)
created_arns = set()
for page in glue.get_paginator("get_databases").paginate():
    for db in page["DatabaseList"]:
        fed = db.get("FederatedDatabase")   # .get() → None if this db isn't federated
        if fed:
            # add fed["Identifier"] to created_arns
            created_arns.add(fed["Identifier"])

paginator = rs.get_paginator("describe_data_shares_for_consumer")

matches = []

for page in paginator.paginate():
    for share in page["DataShares"]:
        arn = share["DataShareArn"]
        associations = share["DataShareAssociations"]
        name = datashare_name(arn)

        # filter 0: skip datashares that already have a database
        if arn in created_arns:
            continue

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

        #compiling a dict of invitations that need processing
        matches.append(share)

if not matches:
    print("Nothing to accept!")
else:
    for share in matches:
        arn = share["DataShareArn"]
        name = datashare_name(arn)
        accepted = is_accepted(share["DataShareAssociations"])
        db_name = name.removeprefix("ds_")
        created_date = invitation_date(share["DataShareAssociations"])

        answer = input(f"Process {name}, created on {created_date:%Y-%m-%d %H:%M:%S}? (y/n) ")
        if answer.strip().lower() == "y":
            # DRY RUN — print the plan, don't call AWS yet
            # if NOT accepted, note "would accept (associate) ..."
            # always note "would create database <db_name>"
            if not accepted:
                print(f"Would accept {name} and create database {db_name}")
            if accepted:
                print(f"Would create database {db_name}")
        else:
            print(f"  skipped {name}")

input("Press Enter to exit...")