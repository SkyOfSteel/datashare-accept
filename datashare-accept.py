"""
DatashareAccept: Accept Lake Formation-managed Amazon Redshift datashare invitations 
and build their Glue databases.

The script finds pending datashares in the account's Glue Data Catalog, accepts it and creates
the matching federated AWS Glue database upon approval. It targets invitations from the past 7 days 
whose name does not contain "_bi_" or "_fulfillment".

Features:
1. Lists datashares shared with the account via redshift describe-data-shares-for-consumer.
2. Skips any that already have a federated Glue database.
3. Excludes datashares whose name contains "_bi_" or "_fulfillment" - these belong to other teams.
4. Keeps only invitations created within the last RECENT_DAYS days (7 by default).
5. Prompts (y/n) per invitation before making any change.
6. Associates not-yet-accepted datashares to the Glue Data Catalog.
7. Creates the federated Glue database, with 3 retry attempts if there is a lag between accepting an invite
and creating a database.
8. Derives account and region from the active session.

Usage examples:
  aws sso login --profile governance              # log into your AWS SSO account
  python datashare-accept.py                      # default "governance" profile
  python datashare-accept.py --profile devsecops  # a "devsecops" AWS profile

Prerequisites: an authenticated SSO session for the chosen profile (`aws sso login --profile <name>`)
and boto3 installed.

Author: Ivan Zots
Released on: 2026-08-27
"""

import boto3, argparse, time
from datetime import datetime, timedelta, timezone

parser = argparse.ArgumentParser(description="Accept LF-managed Redshift datashare invitations.")
parser.add_argument("--profile", default="governance", help="AWS profile to use (default: governance)")
args = parser.parse_args()

session = boto3.Session(profile_name=args.profile, region_name="us-east-1")
rs = session.client("redshift")
glue = session.client("glue")

account_id = session.client("sts").get_caller_identity()["Account"]     # get the account number
GLUE_CATALOG = f"arn:aws:glue:{session.region_name}:{account_id}:catalog"
EXCLUDE = ("_bi_", "_fulfillment")
RECENT_DAYS = 7

def datashare_name(arn):
    """Return the datashare name: the segment after the last '/' in its ARN."""
    return arn.split("/")[-1]

def is_accepted(associations):
    """Return True if the datashare is already accepted (has an ACTIVE association to the Glue catalog)."""
    for assoc in associations:
        if assoc["Status"] == "ACTIVE" and assoc["ConsumerIdentifier"] == GLUE_CATALOG:
            return True
    return False

def invitation_date(associations):
    """Return the invitation's CreatedDate (from its DataCatalog association) or None if absent."""
    for assoc in associations:
        if assoc["ConsumerIdentifier"].startswith("DataCatalog"):
            return assoc["CreatedDate"]
    return None

def create_db_with_retry(db_name, arn, attempts=3, wait=5):
    """Create the datashare's federated Glue database, retrying to account for a delay after accepting."""
    for attempt in range(1, attempts + 1):
        try:
            glue.create_database(DatabaseInput={
                "Name": db_name,
                "FederatedDatabase": {"Identifier": arn, "ConnectionName": "aws:redshift"},
            })
            return True                                   # success → done
        except Exception as e:
            print(f"  create attempt {attempt}/{attempts} failed: {e}")
            if attempt < attempts:
                time.sleep(wait)                          # wait, then loop
    return False                                          # exhausted all tries

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

        # filter 1: skip if name contains anything in EXCLUDE ("_bi_", "_fulfillment")
        if any(filtered_value in name for filtered_value in EXCLUDE):
            continue

        # filter 2: skip if invitation_date is older than RECENT_DAYS
        created_date = invitation_date(associations)
        if created_date is None:
            continue
        cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
        if created_date < cutoff:
            continue

        #compiling a list of invitations that need processing
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
            # if NOT accepted, note "would accept (associate) ..."
            # always note "would create database <db_name>"
            if not accepted:
                try:
                    rs.associate_data_share_consumer(
                        DataShareArn=arn,
                        ConsumerArn=GLUE_CATALOG,
                    )
                    print(f"Success! Accepted {name}.")
                except Exception as e:
                    print(f"Error: {e}. Skipping.")
                    continue

            if create_db_with_retry(db_name, arn):
                print(f"Success! Created database {db_name}")
            else:
                print(f"Max. retries reached for {db_name}. Skipping.")
                continue

        else:
            print(f"  skipped {name}")

input("Press Enter to exit...")