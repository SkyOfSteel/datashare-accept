# Datashare Invite Accept Tool (AWS)

A script to programmatically accept data share invites in Lake Formation and create Glue databases with SSO access.

## Overview

This command-line tool accepts Lake Formation-managed Amazon Redshift datashare invitations and creates the matching federated AWS Glue databases in one step. 

It lists the datashares shared with your account, then narrows them to recent invitations (created within the last `RECENT_DAYS` days) whose names fit the convention — it skips anything containing `_bi_` or `_fulfillment` and anything that already has a database. 

For each remaining invitation it asks for confirmation. The target account and region are read from the active AWS session, and the tool is safe to re-run — already-processed datashares are detected and skipped.

## Pre-requisites

1. AWS CLI with SSO configured.
2. Python 3.9+.
3. boto3

## Usage

Authenticate your profile — the tool relies on an existing SSO session and can't log in on its own:

```
aws sso login --profile governance
```

Then run it from a terminal:

```
python datashare-accept.py                      # uses the default "governance" profile
python datashare-accept.py --profile devsecops  # or point it at another profile
```

The script prints each in-scope invitation with its creation date and asks `y/n`. Answer `y` to accept the datashare and create its Glue database (retrying briefly to absorb accept-to-create propagation lag), or `n` to skip it. 

When there's nothing to do, it prints `Nothing to accept!` and exits. Afterwards, confirm the new databases under **Lake Formation → Data Catalog → Data Sharing → Shared databases** or re-run the tool — anything already done drops off the list.

## Known Issues

N/A

## To-Do

1. Test in the live environment.