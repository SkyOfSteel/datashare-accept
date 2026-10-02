r"""
DatashareAccept: Accept Lake Formation-managed Amazon Redshift datashare invitations
and build their Glue databases.

The script lists pending datashare invitations shared with the account's Glue Data Catalog,
shows them for review, then processes all of them or one by one: it accepts each invitation,
registers the datashare with Lake Formation and creates the matching federated AWS Glue
database. By default it targets invitations from the past 7 days whose names do not contain
"_bi_" or "_fulfillment" (these belong to other teams).

Features:
1. Lists datashares shared with the account (redshift describe-data-shares-for-consumer).
2. Skips any that already have a federated Glue database, so it is safe to re-run.
3. Excludes datashares by name (--exclude, default: _bi_ _fulfillment).
4. Keeps only invitations created within the last N days (--days, default: 7).
5. Shows the full list with each target database name, then asks once:
   [a]ll, [o]ne by one (y/n per invitation), or [q]uit. Any other answer quits.
6. Accepts (associates) not-yet-accepted datashares with the Glue Data Catalog.
7. Registers each datashare with Lake Formation (required before creating the database).
8. Creates the federated Glue database, named after the datashare minus its "ds_clstr_"
   or "ds_" prefix. Retries short delays; gives up at once on errors a retry can't fix.
9. Opens the browser for an SSO login when the profile's login is missing or expired.
10. Explains setup problems (unknown profile, missing AWS CLI, unfinished login) in plain words.
11. Ends with a summary and an exit code: 0 if nothing failed, 1 otherwise.

Feature Update:
2026-10-02
    1. Lake Formation register step between accepting and creating the database.
    2. Command-line options: --profile (default "default"), --exclude, --days.
    3. Review list with [a]ll / [o]ne by one / [q]uit.
    4. SSO login on demand, friendly setup errors, summary and exit code.
    5. Database names also drop the "ds_clstr_" prefix.

Prerequisites: Python 3.9+, AWS CLI v2 (used for the SSO login), and an AWS SSO profile
for the account with Lake Formation admin rights. boto3 is installed during setup.

Setup (PowerShell, in the folder with this script and requirements.txt):

  python -m venv venv
  .\venv\Scripts\python.exe -m pip install -r requirements.txt
  .\venv\Scripts\python.exe datashare-accept.py --profile <profile-name> --days 0

The last line is a safe first run: it logs in if needed, reads the invitation list and changes
nothing. Calling the venv's python.exe by its path needs no venv activation. A wrapper script
should launch the tool the same way and pause at the end (e.g. Read-Host), because an
unexpected error closes the window before it can be read.

Usage examples (with the venv activated; otherwise use .\venv\Scripts\python.exe):
  python datashare-accept.py                                     # "default" profile, default filters
  python datashare-accept.py --profile governance                # a named AWS profile
  python datashare-accept.py --days 30                           # invitations from the last 30 days
  python datashare-accept.py --exclude _bi_ _fulfillment _test_  # replaces the defaults
  python datashare-accept.py --help                              # all options

Author: Ivan Zots
Released on: 2026-08-27
"""

import boto3, argparse, time, subprocess, sys
from datetime import datetime, timedelta, timezone
from botocore.exceptions import SSOError, TokenRetrievalError, ProfileNotFound

def create_session(profile, region):
    """Return a boto3 session for the profile, running 'aws sso login' first if the login is missing or expired."""
    session = boto3.Session(profile_name=profile, region_name=region)
    try:
        session.client("sts").get_caller_identity()          # check that the login works
    except (SSOError, TokenRetrievalError):
        print(f"No valid SSO login for profile '{profile}'. Opening the browser to log in...")
        subprocess.run(["aws", "sso", "login", "--profile", profile], check=True)
        session = boto3.Session(profile_name=profile, region_name=region)
    return session

def fail(message):
    """Print an error, keep the window open until Enter is pressed, then exit with code 1."""
    print(f"ERROR: {message}")
    input("Press Enter to exit...")
    sys.exit(1)

parser = argparse.ArgumentParser(description="Accept LF-managed Redshift datashare invitations "
                                "and create their Glue databases.", 
                                 add_help=False)
parser.add_argument("-h", "--help", action="help", help="Show this help message and exit.")
parser.add_argument("--profile", default="default", 
                    help="Name of the AWS SSO profile to use ('default' if nothing specified).")
parser.add_argument("--exclude", nargs="*", default=["_bi_", "_fulfillment"], 
                    help="Skip datashares whose name contains any of these (default: _bi_ _fulfillment). "
                    "Values must be separated by spaces. "
                    "Using this option replaces the default values. "
                    "Typing --exclude without parameters shows all pending invites.")
parser.add_argument("--days", type=int, default=7,
                    help="Only invitations created in the last N days (default: 7).")
args = parser.parse_args()

try:
    session = create_session(args.profile, "us-east-1")
except ProfileNotFound:
    fail(f"AWS profile '{args.profile}' not found. Check the name with: aws configure list-profiles")
except FileNotFoundError:
    fail("The AWS CLI ('aws') was not found. Install AWS CLI v2, then try again.")
except subprocess.CalledProcessError:
    fail("The SSO login did not complete. Run the script again to retry.")

rs = session.client("redshift")
glue = session.client("glue")
lf = session.client("lakeformation")

account_id = session.client("sts").get_caller_identity()["Account"]     # get the account number
GLUE_CATALOG = f"arn:aws:glue:{session.region_name}:{account_id}:catalog"
EXCLUDE = args.exclude
RECENT_DAYS = args.days

print(f"Profile: {args.profile} | Exclude names containing: {EXCLUDE} | Over the last {RECENT_DAYS} days")

def datashare_name(arn):
    """Return the datashare name: the segment after the last '/' in its ARN."""
    return arn.split("/")[-1]

def db_name_for(share_name):
    """Return the Glue database name: the datashare name without its "ds_clstr_" or "ds_" prefix."""
    db_name = share_name.removeprefix("ds_clstr_")
    return db_name.removeprefix("ds_")

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
    """Create the datashare's federated Glue database, 
    retrying short delays but giving up at once on errors a retry can't fix."""
    for attempt in range(1, attempts + 1):
        try:
            glue.create_database(DatabaseInput={
                "Name": db_name,
                "FederatedDatabase": {"Identifier": arn, "ConnectionName": "aws:redshift"},
            })
            return True                                   # success → done
        except (glue.exceptions.AlreadyExistsException,
                glue.exceptions.FederatedResourceAlreadyExistsException,
                glue.exceptions.InvalidInputException) as e:
            print(f"  create failed, retrying won't help: {e}")
            return False                                  # give up at once
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

done = 0
skipped = 0
failed = []          # names of the datashares that failed, for the summary

if not matches: 
    print("Nothing to accept!")
else:
    print(f"\nFound {len(matches)} invitation(s):")
    for number, share in enumerate(matches, start=1):
        name = datashare_name(share["DataShareArn"])
        created_date = invitation_date(share["DataShareAssociations"])
        status = "accepted" if is_accepted(share["DataShareAssociations"]) else "NOT accepted"
        print(f"  {number}. {name}  {created_date:%Y-%m-%d %H:%M}  [{status}]  -> {db_name_for(name)}")
    print()

    choice = input("Process [a]ll, go [o]ne by one, or [q]uit? ").strip().lower()
    if choice not in ("a", "o"):
        print("Quitting - nothing was changed.")
    else:
        for share in matches:
            arn = share["DataShareArn"]
            name = datashare_name(arn)
            accepted = is_accepted(share["DataShareAssociations"])
            db_name = db_name_for(name)
            created_date = invitation_date(share["DataShareAssociations"])

            if choice == "a":
                print(f"Processing {name}...")
                answer = "y"
            else:
                answer = input(f"Process {name}, created on {created_date:%Y-%m-%d %H:%M:%S}? (y/n) ")

            if answer.strip().lower() == "y":
                if not accepted:
                    try:
                        rs.associate_data_share_consumer(
                            DataShareArn=arn,
                            ConsumerArn=GLUE_CATALOG,
                        )
                        print(f"Success! Accepted {name}.")
                    except Exception as e:
                        print(f"Error: {e}. Skipping.")
                        failed.append(name)
                        continue

                try:
                    lf.register_resource(ResourceArn=arn)
                    print(f"Registered {name} with Lake Formation.")
                except lf.exceptions.AlreadyExistsException:
                    print(f"{name} was already registered.")
                except Exception as e:
                    print(f"Error registering {name}: {e}. Skipping.")
                    failed.append(name)
                    continue

                if create_db_with_retry(db_name, arn):
                    print(f"Success! Created database {db_name}.")
                    done += 1
                else:
                    print(f"Could not create database {db_name}. Skipping.")
                    failed.append(name)
                    continue

            else:
                print(f"  skipped {name}")
                skipped += 1
        
        print(f"\nSummary: {done} done, {len(failed)} failed, {skipped} skipped")
        if failed:
            print("Failed: " + ", ".join(failed))

input("Press Enter to exit...")
sys.exit(1 if failed else 0)