# CLAMS Kitchen
Python scripts for running CLAMS apps and using the output

## Overview

The `run_job.py` script runs CLAMS applications against a batch of assets by looping through the items in the batch, taking several steps with each one.  For each item, the script performs the following steps:
  - Checking for media files
  - Downloading media files from Sony Ci (optional)
  - Creating a "blank" MMIF file for the asset
  - Running a CLAMS app (or a pipeline of CLAMS apps) to create annotation-laden MMIF
  - Performing post-processing on the data-laden MMIF to create useful output
  - Logging of each item processed
  - Cleaning up (removing) downloaded media

Currently, the main post-processing routines that have been defined are associated with the creation of visual indexes ("visaids") for video files, as performed by the [visaid_builder](https://github.com/WGBH-MLA/visaid_builder) module, using the output the [CLAMS SWT detection app](https://github.com/clamsproject/app-swt-detection).  

Additional post-processing for transcripts and transcript metadata is performed by the [transcript_converter](https://github.com/WGBH-MLA/transcript_converter) module, using the output of the [CLAMS Whisper Wrapper app](https://apps.clams.ai/whisper-wrapper/) or the [CLAMS Parakeet Wrapper app](https://apps.clams.ai/parakeet-wrapper/).


## Installation

Clone this repository.  Change to the repository directory and do a `pip install -r requirements.txt`.

If you wish to use the included `media_availability` module (which downloads media files from Sony Ci), then the `jq` executable must be available in the local environment.

To use the visaid_builder routines in the CLAMS kitchen, clone the [visaid_builder](https://github.com/WGBH-MLA/visaid_builder) project inside the `clams-kitchen` root folder.  Then install additional requirements by doing `pip install -r visaid_builder/requirements.txt`.

To use the transcript_converter routines, clone the [transcript_converter](https://github.com/WGBH-MLA/transcript_converter) project inside the `clams-kitchen` root folder.  Then install additional requirements by doing `pip install -r transcript_converter/requirements.txt`.

## Usage

The main script is `run_job.py`.  Run `python run_job.py -h` for help.

You will need a configuration file, which is a JSON file.  See the "Configuration" section betlow for details.  Several example files are included in the `sample_config` directory.

You will also need a batch definition file, which is a CSV file.  The first column must be `asset_id`.  In addition, at least one other column is required.  It must be either `media_filename` (for media that is already locally available in the media directory) or `sonyci_id` (for media that needs to be acquired from Sony Ci).

## Configuration

The following fields can be set in the job configuration JSON file.  Alternatively, several of these fields can be set or overridden with command-line arguments to `run_job.py`.

### Mandatory fields

These fields are required for execution of `run_job.py`.

#### `id`

This is an identifier for the batch.  It should have no spaces or other special characters that don't belong in a filename.

#### `def_path` 

Path and filename for the CSV file defining the list of items to be processed.  The first two columns must be "asset_id" and "sonyci_id". (See example file in this directory.)

#### `media_dir` 

This is the path to the directory where media files to be processed will be stored.  (If local_base` and `mnt_base`are specified, they will be automatically prefixed to this path at runtime.)

#### `results_dir`

This is the path to the directory where data output from the batch run will be stored.  (If local_base` and `mnt_base`are specified, they will be prefixed to this path.)


### Essential fields

These fields are essential in that you need them in order to do useful CLAMS processing.

#### `local_base` and `mnt_base`

The `local_base` and `mnt_base` keys specify prefixes for the `_dir` and `_path` parameters.  

These prefixes exist to support running on a Windows machine where file paths may be interpreted according to either Windows conventions or POSIX conventions at different steps of the process.  So, on a Windows machine, the local base might be "C:" with the mount base "/mnt/c".  

On a Linux or Mac system, the `local_base` and `mnt_base` should be the same, or they can be omitted entirely.  If only a `local_base` is specified, this value will be used for `mnt_base` as well.

#### `clams_run_cli`

Determines whether CLAMS apps are to be run via Dockerized commandline apps or via web service endpoints.  Default is `true`.

#### `clams_images` or `clams_endpoints`

A list of strings specifying either Docker images for CLAMS apps to be run or endpoints to be queried.


#### `clams_params`

A dictionary of parameters and values to be passed to the CLAMS apps

#### `post_proc`

A dictionary specifying a pre-defined procedure to be run after the CLAMS apps -- for instance creating artifacts like slates or visual aids from the output of SWT.


### Optional fields

#### `name`

This is a human-readable identifier for the batch.  If it is not specified, the value of `id` will be used instead.

#### `start_after_item` and `end_after_item`

These can be used to run part of a batch defined in the batch definition list.  (Useful for resuming batches that were interupted.)

#### `overwrite_mmif`

When this is false, MMIF files matching the asset ID and batch ID will left in place, and not recreated.  If this true, the MMIF processing will be redone, and the MMIF files will be overwritten.  The default is `false`.

#### `cleanup_media_per_item`

Controls whether media files are deleted after a run is complete.  The default is `false`.

#### `cleanup_beyond_item`

Specifies the item in the batch beyond which media files are to be deleted (assuming `cleanup_media_per_item` is true).  The default is 0.




## Media 

Media files should be placed in a directory specified in the job configuration.

If media files are to be downloaded from Sony Ci using the included `media_availability` module, then there must be a YAML file at `./secrets/ci.yml` with the following keys:
  - `cred_string`
  - `client_id`
  - `client_secret`
  - `workspace_id`


## Current limitations

This script works with CLAMS apps running in CLI mode or as web services.  However, complex parameters (like the 'map' parameter of the SWT detection app) does not work for web-service mode.  Also, note that web services must be initialized and be running before clams-kitchen can use them.
