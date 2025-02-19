# CLAMS Kitchen
Python scripts for running CLAMS apps and using the output

## Overview

The `run_job.py` script runs CLAMS applications against a batch of assets by looping through the items in the batch, taking several steps with each one.  For each item, the script performs the following steps:
  - checking for media files and downloading missing ones from Sony Ci
  - creating a "blank" MMIF file for the asset
  - running a CLAMS app (or a pipeline of CLAMS apps) to create annotation-laden MMIF
  - performing post-processing on the data-laden MMIF to create useful output
  - cleaning up (removing) downloaded media

Currently, the only post-processing routines that have been defined are associated with the creation of visual indexes ("visaids") for video files, as performed by the [visaid_builder](https://github.com/WGBH-MLA/visaid_builder).  


## Installation

Clone this repository.  Change to the repository directory and do a `pip install -r requirements.txt`.

If you wish to use the included `media_availability` module (which downloads media files from Sony Ci), then the `jq` executable must be available in the local environment.

To use the SWT detection app and visaid-builder routines in the CLAMS kitchen, clone the [visaid_builder](https://github.com/WGBH-MLA/visaid_builder) project inside the `clams-kitchen` root folder.  Then install additional requirements by doing `pip install -r visaid_builder/requirements.txt`.


## Usage

The main script is `run_job.py`.  Run `python run_job.py -h` for help.

You will need a configuration file, which is a JSON file.  See the `CONFIGURATION.md` file for details.  Several example files are included in the `sample_config` directory.


## Media 

Media files should be placed in a directory specified in the job configuration.

If media files are to be downloaded from Sony Ci using the included `media_availability` module, then there must be a YAML file at `./secrets/ci.yml` with the following keys:
  - `cred_string`
  - `client_id`
  - `client_secret`
  - `workspace_id`


## Current limitations

This script works with CLAMS apps running in CLI mode or as web services.  However, support for web services is more difficult and may be dropped.  One problem with using apps running as web services is that if the app fails, the script does not currently have a way to restart the web service.  Also, complex parameters (like the 'map' parameter of the SWT detection app) does not work for web-service mode.
