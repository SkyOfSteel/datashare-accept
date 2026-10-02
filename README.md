# Datashare Invite Accept Tool (AWS)

A script to programmatically accept data share invites in Lake Formation and create Glue databases with SSO access.

## Overview

This command-line tool accepts Lake Formation-managed Amazon Redshift datashare invitations, registers each datashare with Lake Formation and creates the matching federated AWS Glue database, all in one run.

It lists the datashares shared with your account, then narrows them to recent invitations (created within the last `--days` days, 7 by default) whose names fit the convention. By default it skips anything containing `_bi_` or `_fulfillment` (see `--exclude`), as well as anything that already has a database.

It then shows the full list, including the database name each invitation will get, and asks once whether to process them [a]ll, go [o]ne by one, or [q]uit. The target account and region are read from the active AWS session, and the tool is safe to re-run — already-processed datashares are detected and skipped.

## Pre-requisites

1. AWS CLI v2, with an SSO profile for the account that has Lake Formation admin rights.
2. Python 3.9+.
3. boto3, installed by the Setup steps below.

## Setup

Copy `datashare-accept.py`, `requirements.txt` to a folder. Then, in PowerShell, in that folder:

```
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe datashare-accept.py --profile <profile-name> --days 0
```

Calling the venv's `python.exe` by its path works without activating the venv, which helps where `Activate.ps1` is blocked by the script-execution policy. The last line is a safe first run: it logs in if needed and reads the invitation list, which confirms that the profile has access. With `--days 0` nothing qualifies, so it changes nothing and ends at `Nothing to accept!`.

To launch the tool from a wrapper script, call `venv\Scripts\python.exe` by its full path the same way. The script pauses before it exits and returns an exit code, but an unexpected error still closes the window before it can be read, so have the wrapper pause at the end too (for example with `Read-Host`).

## Usage

Run it from a terminal. The examples use `python`; if the venv isn't activated, use `.\venv\Scripts\python.exe` instead:

```
python datashare-accept.py                                     # "default" profile, default filters
python datashare-accept.py --profile governance                # a named AWS profile
python datashare-accept.py --days 30                           # invitations from the last 30 days
python datashare-accept.py --exclude _bi_ _fulfillment _test_  # replaces the default exclusions
python datashare-accept.py --help                              # all options
```

If the profile's SSO login is missing or expired, the script opens your browser to log in, then carries on.

`--exclude` values are separated by spaces, not commas, and they replace the defaults. `--exclude` on its own turns off all exclusions. Each run prints the profile and filters in use before listing anything.

The script lists every invitation in scope with its creation date, status and target database name (the datashare name without its `ds_clstr_` or `ds_` prefix), then asks once: `a` processes them all, `o` asks `y/n` for each one, and anything else quits without changes. For each invitation it processes, it accepts it if needed, registers it with Lake Formation and creates the Glue database.

When there's nothing to do, it prints `Nothing to accept!` and exits. Otherwise it ends with a summary of what was done, failed and skipped. The exit code is `0` if nothing failed and `1` otherwise, so a wrapper script can check `$LASTEXITCODE`. Afterwards, confirm the new databases under **Lake Formation → Data Catalog → Data Sharing → Shared databases**, or re-run the tool — anything already done drops off the list.

## Known Issues

~~The script was skipping the register step after accepting the invite.~~

## To-Do

1. ~~Test in the live environment.~~
2. Try `[a]ll` on a live batch.
3. Exit cleanly on Ctrl+C instead of printing a traceback.