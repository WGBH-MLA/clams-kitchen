# Configuration for `run_batch.py`

## Overview

The main `run_batch.py` script is configured through a combination of command line parameters and a configuration file.

Run `python run_batch.py -h` for help.

The only required parameter is a configuration file, the semantics of which are detailed below.


## Sample files

Sample configuration files can be found in the `sample_config` directory.


## The configuation file

The config file is a JSON file with the following keys.

### `id` (required, if not provided at the CLI)

This is an identifier for the batch.  It should have no spaces or other special characters that don't belong in a filename.

### `name`

This is a human-readable identifier for the batch.  If it is not specified, the value of `id` will be used instead.


### `local_base` and `mnt_base`

The `local_base` and `mnt_base` keys specify prefixes for the `_dir` and `_path` parameters.  

These prefixes exist to support running on a Windows machine where file paths may be interpreted according to either Windows conventions or POSIX conventions at different steps of the process.  So, on a Windows machine, the local base might be "C:" with the mount base "/mnt/c".  

On a Linux or Mac system, the `local_base` and `mnt_base` should be the same, or they can be omitted entirely.  If only a `local_base` is specified, this value will be used for `mnt_base` as well.

### `results_dir` (required)

This is the path to the directory where data output from the batch run will be stored.  (If local_base` and `mnt_base`are specified, they will be prefixed to this path.)

### `def_path` (required, if not provided at the CLI)

Path and filename for the CSV file defining the list of items to be processed.  The first two columns must be "asset_id" and "sonyci_id". (See example file in this directory.)

### `media_dir` (required)

This is the path to the directory where media files to be processed will be stored.  (If local_base` and `mnt_base`are specified, they will be prefixed to this path.)

### `start_after_item` and `end_after_item`

These can be used to run part of a batch defined in the batch definition list.  (Useful for resuming batches that were interupted.)

### `overwrite_mmif`

When this is false, MMIF files matching the asset ID and batch ID will left in place, and not recreated.  If this true, the MMIF processing will be redone, and the MMIF files will be overwritten.  The default is `false`.

### `cleanup_media_per_item`

Controls whether media files are deleted after a run is complete.  The default is `false`.

### `cleanup_beyond_item`

Specifies the item in the batch beyond which media files are to be deleted (assuming `cleanup_media_per_item` is true).  The default is 0.

### `filter_warnings`

A value of 'ignore' supresses some uninformative error messages.  Default is 'ignore'.

### `clams_run_cli`

Determines whether CLAMS apps are to be run via Dockerized commandline apps or via web service endpoints.  Default is `true`.

### `clams_images` or `clams_endpoints`

A list of strings specifying either Docker images for CLAMS apps to be run or endpoints to be queried.

### `clams_params`

A dictionary of parameters and values to be passed to the CLAMS apps

### `post_proc`

A dictionary specifying a pre-defined procedure to be run after the CLAMS apps -- for instance creating artifacts like slates or visual aids from the output of SWT.



