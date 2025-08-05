"""
run_job.py

This script runs CLAMS applications against a batch of assets by looping through 
the items in the batch, taking several steps with each one.  

It uses several data structures that are passed around this module.

`cf` - the job configuration dictionary. Most of the values are set by the 
job configuration file.  Some can be set from the command line.  Some
are calculated at the beginning of the job.  The dictionary keys are as follows,
with the corresponding configuration file key in brackets.
   - start_timestamp (str)
   - job_id (str)                        ["id"]
   - job_name (str)                      ["name"]
   - logs_dir (str)    
   - just_get_media (bool)               ["just_get_media"]
   - media_required (bool)               ["media_required"]
   - start_after_item (int)              ["start_after_item"]
   - end_after_item (int)                ["end_after_item"]
   - include_only_items (list of ints)   ["include_only_items"]
   - overwrite_mmif (bool)               ["overwrite_mmif"]
   - cleanup_media_per_item (bool)       [cleanup_media_per_item"]
   - cleanup_beyond_item (int)           ["cleanup_beyond_item"]
   - parallel (int)                      ["parallel"]
   - stagger (int)                       ["stagger"]
   - artifacts_dir (str)
   - media_dir (str)
   - shell_media_dir (str)
   - shell_cache_dir (str)
   - mmif_dir (str)
   - shell_mmif_dir (str)

`clams` - CLAMS-specific configuration dictionary. The values are set by the 
job configuration file.  It has the following keys:
   - apps (list of dicts) each dict each with a key of "image" or "endpoint" 
         and the relevant Docker image or web service endpoint as the value.
         Each dict also has a key indicating whe the value of the "gpus" parameter
         passed to Docker.  Usually, to use GPU, it is set to "all".
   - param_sets (list of dicts) each with parameters for a CLAMS app
   - docker_gpus_all (bool) indicating whether to call Docker with GPU (cuda) enabled
   - show_cli_stderr (bool) indicating whether to print stderr to screen

`post_procs` - a list of dicts each with the parameters for a post-process

It is expected that each dictionary in `post_procs` will contain at, at least, keys
for "name" of the postprocess which has a string value (e.g., "visaid_builder") 
and "artifacts" of the postprocess, a list of strings indicatinng the artifacts
to be produced (e.g., "slate").  In addition, the dict declares the options and 
parameters specific to the relevant postprocess.

`batch_l` - a list of items in the batch (limited by values of `start_after_item`
and `end_after_item` if those were supplied.  Each item is a dictionary with keys set
by the columns of the batch definition list CSV file.  An additional index with key 
of `"item_num"` is added after the CSV file is read.

`tried_l` - a list of items attempted.  The data structure inherits keys defined
in `batch_l` and adds the following keys, which are set when each item is ru:
   - skip_reason (str)
   - errors (list of str)
   - problems (list of str)
   - media_filename (str)
   - media_path (str)
   - mmif_files (list of str)
   - mmif_paths (list of str)
   - elapsed_seconds (int)
"""

# Import standard modules
import os
import platform
import csv
import json
import datetime
import time
import warnings
import subprocess
import argparse
import multiprocessing as mp
import logging

logging.basicConfig(
    level=logging.WARNING,
    format="%(message)s"
)

# Import installed modules
import requests

# Import local modules
import runlog_sum
from drawer.media_availability import check_avail, make_avail, remove_media
from drawer.mmif_adjunct import make_blank_mmif, mmif_check

# Import post-processing modules, if available
try:
    import visaid_builder.post_proc_item
except ImportError as e:
    print("Import error:", e)
    print("Warning: `visaid_builder` module not found.  Will not use.")

try:
    import transcript_converter.post_proc_item
except ImportError as e:
    print("Import error:", e)
    print("Warning: `transcript_converter` module not found.  Will not use.")
   



############################################################################
# Define helper functions
############################################################################

def update_tried( item, cf, tried_l, l_lock):
    """Helper function to reduce code repetition.
    Handles locking, but only if a lock has been defined."""

    # shorthand item number string for screen output
    ins = f'[#{item["item_num"]}] '

    # record time that item finished
    item["time_ended"] = datetime.datetime.now().isoformat()

    print(ins+"Recording this item in the list of tried items.")

    if l_lock is not None:
        print(ins+f"Worker {os.getpid()} received lock: {l_lock}") # DIAG
        with l_lock: 
            print(ins+f"Worker {os.getpid()} acquired lock: {l_lock}") # DIAG
            tried_l.append(item)
            print(ins+"Item recorded in processing list.")
            write_tried_log(item, cf, tried_l)
        print(ins+f"Worker {os.getpid()} released lock: {l_lock}") # DIAG
    else:
        tried_l.append(item)
        print(ins+"Item recorded in processing list.")
        write_tried_log(item, cf, tried_l)


def write_tried_log(item, cf, tried_l):
    """
    Write a "runlog" of tried items.
    Write out both CSV and JSON versions.
    Note: `item` is used only for exception messages; it can be `None`.  
    """

    # shorthand item number string for screen output
    if item is not None:
        ins = f'[#{item["item_num"]}] '
    else:
        ins = ""

    # Conversion may be necessary if object passed in was a ListProxy instead of
    # plain list.
    # This step has been known to cause problems with multiprocessing, especially
    # with items rapidly or many items being updated concurrently.  If we can't 
    # convert to a list, no problem.  
    log_l = None
    try:
        log_l = list(tried_l)
    except Exception as e:
        print(ins + "High volume IPC prevented immediate logging of this item.")
        print(ins + "(This item will still be included in log eventually.)")

    # If we got a log list, write it out
    if log_l is not None:
        # Results files get a new name every time this script is run
        job_results_log_file_base = ( cf["logs_dir"] + "/" + cf["job_id"] + 
                                        "_" + cf["start_timestamp"] + "_runlog" )
        job_results_log_csv_path  = job_results_log_file_base + ".csv"
        job_results_log_json_path  = job_results_log_file_base + ".json"

        with open(job_results_log_csv_path, 'w', newline='') as file:
            fieldnames = log_l[0].keys()
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(log_l)
        
        with open(job_results_log_json_path, 'w') as file:
            json.dump(log_l, file, indent=2)

        print(ins+"Processing list written to log file.")


def cleanup_media(cf, item):
    """Cleanup media, i.e., remove media file for this item.
    (Do the cleanup only if it is permitted by the configuration settings!)
    """
    
    # shorthand item number string for screen output
    ins = f'[#{item["item_num"]}] '

    print(ins)
    print(ins + '# CLEANING UP MEDIA')

    if not cf["media_required"]:
        print(ins + "Job declared media was not required.  Will not attempt to clean up.")
    elif cf["cleanup_media_per_item"] and item["item_num"] > cf["cleanup_beyond_item"]:
        print(ins + "Attempting to remove media at", item["media_path"])
        removed = remove_media(item["media_path"])
        if removed:
            print(ins + "Media removed.")
    else:
        print(ins + "Leaving media for this item.")


############################################################################
# main function
############################################################################
def main():
    """Reads commandline arguments and input files, sets up job, manages batch running."""

    # get the time when the job began
    t0 = datetime.datetime.now()

    ############################################################################
    # Handle command line arguments

    app_desc="""
    Performs CLAMS processing and post-processing in a loop as specified in a job configuration file.

    Note: Any values passed on the command line override values in the configuration file.
    """
    parser = parser = argparse.ArgumentParser(
            prog='python run_job.py',
            description=app_desc,
            formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("job_conf_path", metavar="CONFIG",
        help="Path for the JSON job configuration file")
    parser.add_argument("batch_def_path", metavar="DEFLIST", nargs="?",
        help="Path for the CSV file defining the batch of items to be processed.")
    parser.add_argument("job_id", metavar="JOBID", nargs="?",
        help="An identifer string for the job; no spaces allowed")
    parser.add_argument("job_name", metavar="JOBNAME", nargs="?",
        help="A human-readable name for the job; may include spaces; not valid without a JOBID")
    parser.add_argument("--just-get-media", action="store_true",
        help="Just acquire the media listed in the batch definition file.")

    args = parser.parse_args()

    job_conf_path = args.job_conf_path

    if args.batch_def_path is not None:
        cli_batch_def_path = args.batch_def_path
    else:
        cli_batch_def_path = None

    if args.job_id is not None:
        cli_job_id = args.job_id
        
        if args.job_name is not None:
            cli_job_name = args.job_name
        else:
            cli_job_name = cli_job_id
    else:
        cli_job_id = None
        cli_job_name = None

    cli_just_get_media = args.just_get_media


    ############################################################################
    # Process info in the job config file to set up this job.

    print()
    print("Setting up job...")
    print()

    # Set job-specific configuration based on values in configuration file
    with open(job_conf_path, "r") as jsonfile:
        try: 
            conffile = json.load(jsonfile)
        except json.JSONDecodeError as e:
            print(f"JSON parsing error: {str(e)}")
            print()
            raise SystemExit from e
        

    # Dictionaries to store configuation information for this job
    # (Values will be based on the conffile dictionary, but checked and normalized.)
    cf = {}
    clams = {}
    
    cf["start_timestamp"] = t0.strftime("%Y%m%d_%H%M%S")

    # Wrap everything in a big `try` block.  We'll catch some more likely errors, and try
    # to exit gracefully.  (However, the error checking here is not intended to be 
    # especially robust.)
    try: 

        if cli_job_id is not None:
            cf["job_id"] = cli_job_id
        else:
            # This is required to be in the config file if it is not on the command line
            if "id" in conffile:
                cf["job_id"] = conffile["id"] 
            else:
                raise RuntimeError("No job ID specified on commandline or in config file.") 

        if cli_job_name is not None:
            cf["job_name"] = cli_job_name
        elif "name" in conffile:
            cf["job_name"] = conffile["name"]
        else:
            cf["job_name"] = cf["job_id"]


        # Paths and directories 

        # Explanation of `local_base` vs `shell_base`
        # 
        # These are the bases of file paths used by clams-kitchen.
        #
        # Paths for local_base and shell_base will usually be the same in a 
        # POSIX-like environment.
        # They differ in a Windows environment where the local_base may begin with
        # Windows drive letters, e.g., "C:/Users/..." and the shell_base may be 
        # translated to a POSIX-compatible format, e.g., "/mnt/c/Users/...".
        # 
        # Paths beginning with the shell_base are used for running the Docker (and
        # perhaps anything else that involves `subprocess.run`).

        # Begin by establishing the local_base
        # In a POSIX-like environment, this is the main thing we need.
        if "local_base" in conffile:
            local_base = conffile["local_base"]
        else:
            local_base = ""

        # Set the shell_base 
        # (May either match or diverge from local_base)
        if "shell_base" in conffile:
            shell_base = conffile["shell_base"]
        elif "mnt_base" in conffile:  
            # deprecated way to specify shell_base
            shell_base = conffile["mnt_base"]
        else:
            shell_base = local_base

        # Path to batch definition file
        if cli_batch_def_path is not None:
            batch_def_path = cli_batch_def_path
        else:
            #  `def_path` is required if not specified on the command line
            batch_def_path = local_base + conffile["def_path"]

        # `media_dir` is required unless media is not required        
        if "media_required" in conffile:
            cf["media_required"] = conffile["media_required"]
        else:
            cf["media_required"] = True
        if cf["media_required"] or "media_dir" in conffile:
            cf["media_dir"] = local_base + conffile["media_dir"]
            cf["shell_media_dir"] = shell_base + conffile["media_dir"]
        
        # `cache_dir` is optional and is always relative to the `shell_base`
        if "cache_dir" in conffile:
            cf["shell_cache_dir"] = shell_base + conffile["cache_dir"]
        else:
            cf["shell_cache_dir"] = None

        # `results_dir` is required
        results_dir = local_base + conffile["results_dir"]
        shell_results_dir = shell_base + conffile["results_dir"]

        # If `mmif_dir` is not specified, create it and put it in the `results_dir`
        if "mmif_dir" in conffile:
            cf["mmif_dir"] = local_base + conffile["mmif_dir"]
            cf["shell_mmif_dir"] = shell_base + conffile["mmif_dir"]
        else:
            cf["mmif_dir"] = results_dir + "/mmif"
            cf["shell_mmif_dir"] = shell_results_dir + "/mmif"

        # If `logs_dir` is not specified, just use `results_dir`
        if "logs_dir" in conffile:
            cf["logs_dir"] = local_base + conffile["logs_dir"]
        else:
            cf["logs_dir"] = results_dir

        # Checks to make sure directories and setup file exist
        for dirpath in [results_dir, cf["logs_dir"], batch_def_path]:
            if not os.path.exists(dirpath):
                raise FileNotFoundError("Path does not exist: " + dirpath)
        if cf["media_required"] and not os.path.exists(cf["media_dir"]):
            raise FileNotFoundError("Path does not exist: " + cf["media_dir"])


        # Additional configuration options
        if cli_just_get_media:
            cf["just_get_media"] = True
        elif "just_get_media" in conffile:
            cf["just_get_media"] = conffile["just_get_media"]
        else:
            cf["just_get_media"] = False

        if "start_after_item" in conffile:
            if isinstance(conffile["start_after_item"], int) and conffile["start_after_item"] >  0:
                cf["start_after_item"] = conffile["start_after_item"]
            else:
                cf["start_after_item"] = 0
        else:
            cf["start_after_item"] = 0
           
        if "end_after_item" in conffile:
            if conffile["end_after_item"] == "":
                cf["end_after_item"] = None
            elif conffile["end_after_item"] is None:
                cf["end_after_item"] = None
            else:
                cf["end_after_item"] = conffile["end_after_item"]
        else:
            cf["end_after_item"] = None

        if "include_only_items" in conffile:
            if conffile["include_only_items"] is None:
                cf["include_only_items"] = None
            else:
                beg = cf["start_after_item"] if cf["start_after_item"] else 0
                end = cf["end_after_item"] if cf["end_after_item"] else 999999
                cf["include_only_items"] = [i for i in conffile["include_only_items"] if i>beg and i<=end ]
        else:
            cf["include_only_items"] = None

        if "overwrite_mmif" in conffile:
            cf["overwrite_mmif"] = conffile["overwrite_mmif"]
        else:
            cf["overwrite_mmif"] = False

        if "cleanup_media_per_item" in conffile:
            cf["cleanup_media_per_item"] = conffile["cleanup_media_per_item"]
        else:
            cf["cleanup_media_per_item"] = False
        
        if "cleanup_beyond_item" in conffile:
            cf["cleanup_beyond_item"] = conffile["cleanup_beyond_item"]
        else:
            cf["cleanup_beyond_item"] = 0

        if "filter_warnings" in conffile:
            warnings.filterwarnings(conffile["filter_warnings"])
        else:
            warnings.filterwarnings("ignore")

        if "parallel" in conffile:
            cf["parallel"] = conffile["parallel"]
        else:
            cf["parallel"] = 0

        if "stagger" in conffile:
            cf["stagger"] = conffile["stagger"]
        else:
            cf["stagger"] = 20


        # CLAMS config

        # First, set the apps list
        clams["apps"] = clams["param_sets"] = []
        if "clams_apps" in conffile:
            # Check for valid values
            for app in conffile["clams_apps"]:
                if not isinstance(app, dict) and len(app)!= 1:
                    raise RuntimeError("CLAMS apps must be specified as single-item dictionaries.") 
                elif not any(key in app for key in ["image", "endpoint"]):
                    raise RuntimeError("CLAMS apps must have a key of 'image' or 'endpoint'.") 

            clams["apps"] = conffile["clams_apps"]

        elif any(key in conffile for key in ["clams_run_cli", "clams_images", "clams_endpoints"]):
            # Handle deprecated configuration keys
            cli_only = False
            if "clams_run_cli" in conffile:
                if conffile["clams_run_cli"]:
                    cli_only = True

            if "clams_images" in conffile or cli_only:
                if "clams_images" in conffile:
                    clams["apps"] = [ {"image": i} for i in conffile["clams_images"] ]
            else:
                if "clams_endpoints" in conffile:
                    clams["apps"] = [ {"endpoint": e} for e in conffile["clams_endpoints"] ]

        # Count the number of stages
        clams["num_stages"] = len(clams["apps"])

        # Set the parameter sets list
        if "clams_params" in conffile:
            clams["param_sets"] = conffile["clams_params"]
        else:
            # if parameters aren't specified, just use empty dictionaries for each app
            clams["param_sets"] = [ {} for _ in clams["apps"] ] 

        # Make sure we have the right number of parameter sets
        if len(clams["param_sets"]) != clams["num_stages"]:
            raise RuntimeError("Number of CLAMS apps not equal to number of sets of CLAMS params.") 
         

        # Each app specified as a Docker image can be run with the "--gpus" flag set to a 
        # particular value.
        # If this is not already specified in the config file, a default value can be given, to
        # allow defaulting to "all" GPUS for apps for which the "gpus" is not already specified.
        default_docker_gpus_all = False
        if "docker_gpus_all" in conffile:
            if conffile["docker_gpus_all"]:
                default_docker_gpus_all = True
        elif "clams_run_cli_gpu" in conffile:
            # deprecated conffile key
            if conffile["clams_run_cli_gpu"]:
                default_docker_gpus_all = True

        # Set the gpus setting if not already set, on a per app basis
        if default_docker_gpus_all:
            for app in clams["apps"]:
                if "image" in app and "gpus" not in app:
                    app["gpus"] = "all"

        if "clams_show_cli_stderr" in conffile:
            if conffile["clams_show_cli_stderr"]:
                clams["show_cli_stderr"] = True
            else:
                clams["show_cli_stderr"] = False
        else:
            clams["show_cli_stderr"] = False

        # Post-processing configuration options

        if "post_proc" in conffile:
            # just one post process defined in conffile
            if not isinstance( conffile["post_proc"], dict):
                raise RuntimeError("Value for `post_proc` must be a dict.")
            else:
                post_procs = [ conffile["post_proc"] ]
        elif "post_procs" in conffile:
            # list of post processes defined in conffile
            if not isinstance( conffile["post_procs"], list):
                raise RuntimeError("Value for `post_procs` must be a list.")
            else:
                post_procs = conffile["post_procs"] 
        else:
            post_procs = []

        if len(post_procs) > 0:
            # directory for all artifacts (not including MMIF files)
            cf["artifacts_dir"] = results_dir + "/" + "artifacts"
        else:
            cf["artifacts_dir"] = None


    # Handle exceptions encountered during configuration

    except KeyError as e:
        print("Invalid configuration file at", job_conf_path)
        print("Error for expected key:", e)
        raise SystemExit from e

    except FileNotFoundError as e:
        print("Required directory or file not found")
        print("File not found error:", e)
        raise SystemExit from e

    except RuntimeError as e:
        print("Failed to configure job")
        print("Runtime Error:", e)
        raise SystemExit from e


    ############################################################################
    # Check and/or create directories for job output

    # Create list of dirs to create/validate
    dirs = [ cf["mmif_dir"] ]

    if cf["artifacts_dir"]:
        dirs.append(cf["artifacts_dir"])

        for post_proc in post_procs:
            if "artifacts" in post_proc and len(post_proc["artifacts"]) > 0:
                # subdirectories for types of artifacts
                for arttype in post_proc["artifacts"]:
                    artdir = cf["artifacts_dir"] + "/" + arttype
                    dirs.append(artdir)

    # Checks to make sure these directories exist
    # If directories do not exist, then create them
    for dirpath in dirs:
        if os.path.exists(dirpath):
            print("Found existing directory: " + dirpath)
        else:
            print("Creating directory: " + dirpath)
            os.mkdir(dirpath)


    ############################################################################
    # Configure batch

    # Open the batch spreadsheet as a list of dictionaries
    # (But we'll restrict this list based on the configuration.)
    with open(batch_def_path, encoding='utf-8', newline='') as csvfile:
        batch_l = list(csv.DictReader(csvfile))

    # Add a human-readable item index to the batch list
    # (This will be used for filtering and logging.)
    for index, item in enumerate(batch_l, start=1):
        item["item_num"] = index

    # Re-set last item according to the length of the batch list
    if cf["end_after_item"] is None:
        cf["end_after_item"] = len(batch_l)
    elif cf["end_after_item"] < cf["start_after_item"]:
        cf["end_after_item"] = cf["start_after_item"]
    elif cf["end_after_item"] > len(batch_l):
        cf["end_after_item"] = len(batch_l)

    # restrict the batch to the appropriate range
    batch_l = batch_l[cf["start_after_item"]:cf["end_after_item"]]

    # Filter the batch just to specified items (if specified)
    if cf["include_only_items"] is not None:
        batch_l = [ item for item in batch_l if item["item_num"] in cf["include_only_items"] ]

    print()
    print(f'Starting with item # {cf["start_after_item"]+1} and ending after item # {cf["end_after_item"]}.')
    if cf["include_only_items"] is not None:
        print(f'Will omit all items except those specified: {cf["include_only_items"]}.')
    print("Total items:", len(batch_l))


    ############################################################################
    # Main loop or processing pool

    print("Will start processing.")
    print()

    # The `tried_l` variable is the main data structure for recording results of the run.  
    # It is a list of dicts.
    # In MP mode, it is a `Manager.list`.  In serial mode, it is a plain list.
    tried_l = []

    if cf["parallel"] == 0:
        print(f'Will process items serially...')
        print()
        for batch_item in batch_l:
            run_item( batch_item, cf, clams, post_procs, tried_l, None) 

    else:
        print(f'Will process {cf["parallel"]} items in parallel.')
        if cf["stagger"] > 0:
            print(f'Will stagger start of initial {cf["parallel"]} items by {cf["stagger"]}s...')
        print()

        with mp.Manager() as manager:
            # The `tried_l` variable will be an object shared by processes, so each process 
            # can append records to it.
            tried_l = manager.list()
            l_lock = manager.Lock()

            # Collection of items returned from each run.  Should have the same items as 
            # tried_l, after the end of the run.
            # (Not currently used.)
            end_l = []
            
            # Distribute the job to the specified number of worker processes
            # (`chunksize=1` ensures processing in order, to the extent possible.)
            with mp.Pool(cf["parallel"]) as pool:
                end_l = pool.starmap( run_item, 
                                      [ (batch_item, cf, clams, post_procs, tried_l, l_lock) 
                                        for batch_item in batch_l ], 
                                      chunksize=1 )
            # convert `tried_l` to a normal list
            tried_l = list(tried_l)

        # Make sure all items got logged 
        print()
        write_tried_log(None, cf, tried_l)

    # End of main loop or processing pool
    ############################################################################


    ############################################################################
    # Print status and summary after all items have been processed
    print()
    print()
    print("***************************************************************************")
    print()

    if len(tried_l) == len(batch_l):
        print(f"Done with {len(tried_l)} items.")
    else:
        print(f"Warning: Aimed to process {len(batch_l)} total items, but logged {len(tried_l)} attempted items.")

    print()
    runlog_sum.print_simple_summary(tried_l)
    print()
    print()

    tn = datetime.datetime.now()
    days = (tn-t0).days
    seconds = (tn-t0).seconds
    print("Job finished at", tn.strftime("%Y-%m-%d %H:%M:%S"))
    print("Total elapsed time:", days, "days,", seconds, "seconds")
    print(f'Results logged in {cf["logs_dir"]}/')
    print()
    print()


############################################################################
# primary item-level function (for running each item)
############################################################################
def run_item( batch_item, cf, clams, post_procs, tried_l, l_lock) :
    """Run a single item"""

    # stagger start for the initial tranche of parallel items
    if (batch_item["item_num"] - cf["start_after_item"]) <= cf["parallel"]:
        delay = cf["stagger"] * ((batch_item["item_num"] - cf["start_after_item"]) - 1)
        time.sleep(delay)

    # record item start time
    ti = datetime.datetime.now()
    tis = ti.strftime("%Y-%m-%d %H:%M:%S")

    # create new object so we don't change or add to the item passed in.  
    item = batch_item.copy()

    # shorthand item number string for screen output
    ins = f'[#{item["item_num"]}] '

    item_header =  f'{ins}\n'
    item_header += f'{ins}  *  \n'
    item_header += f'{ins}* * *  ITEM # {item["item_num"]} of {cf["end_after_item"]}  * {item["asset_id"]} [ {cf["job_name"]} ] {tis}\n'
    item_header += f'{ins}  *  '
    print(item_header)

    # initialize new dictionary elements for this item
    item["skip_reason"] = ""
    item["errors"] = []
    item["problems"] = []
    item["infos"] = []
    item["media_filename"] = ""
    item["media_path"] = ""
    item["mmif_files"] = []
    item["mmif_paths"] = []
    item["time_began"] = ti.isoformat()
    item["time_ended"] = ""
    item["elapsed_seconds"] = None

    # set default value for `media_type` if this is not supplied
    if "media_type" not in item:
        item["media_type"] = "Moving Image"
        print(ins + "Warning:  Media type not specified. Assuming it is 'Moving Image'.")

    # set the index of the MMIF files so far for this item
    mmifi = -1

    ########################################################
    # Add media to the availability place, if it is not already there,
    # and update the dictionary

    print(ins)
    print(ins + '# MEDIA AVAILABILITY')

    if not cf["media_required"]:
        print(ins + "Media declared not required.")
        print(ins + "Will continue.") 
    else:
        media_path = ""
        media_filename = check_avail(item["asset_id"], cf["media_dir"], ins)

        if media_filename is not None:
            media_path = cf["media_dir"] + "/" + media_filename
            print(ins + "Media already available:  ", media_path) 
        else:
            print(ins + "Media not yet available; will try to make available.") 
            if item["sonyci_id"] :
                media_filename = make_avail(item["asset_id"], item["sonyci_id"], cf["media_dir"], ins)
                if media_filename is not None:
                    media_path = cf["media_dir"] + "/" + media_filename
            else:
                print(ins + "No Ci ID for " + item["asset_id"])

        if media_filename is not None and os.path.isfile(media_path):
            item["media_filename"] = media_filename
            item["media_path"] = media_path
        else:
            # step failed
            # print error messages, updated results, continue to next loop iteration
            print(ins + "Media file for " + item["asset_id"] + " could not be made available.")
            print(ins + "SKIPPING", item["asset_id"])
            item["skip_reason"] = "media"
            update_tried( item, cf, tried_l, l_lock)
            return item

        if cf["just_get_media"]:
            # just update log and continue to next iteration without additional steps
            print(ins + "Media acquisition successful.")
            # Update results (so we have a record of any failures)
            update_tried( item, cf, tried_l, l_lock)
            return item


    ########################################################
    # Create blank MMIF file, if it's not already there
    # (create MMIF 0)

    print(ins)
    print(ins + '# MAKING BLANK MMIF')
    mmifi += 1

    if not cf["media_required"]:
        print(ins + "Media declared not required, implying that blank MMIF is not required.") 
        print(ins + "Will continue.")

        # add empty strings for filename and path to this MMIF file
        item["mmif_files"].append("")
        item["mmif_paths"].append("")
    else:

        # define MMIF for this stage of this iteration
        mmif_filename = item["asset_id"] + "_" + str(mmifi) + ".mmif"
        mmif_path = cf["mmif_dir"] + "/" + mmif_filename

        # Check to see if it exists; if not create it
        if ( os.path.isfile(mmif_path) and not cf["overwrite_mmif"]):
            print(ins + "Will use existing MMIF:    " + mmif_path)
        else:
            print(ins + "Will create MMIF file:     " + mmif_path)

            # Check for prereqs
            if cf["media_required"] and item["media_filename"] == "":
                # prereqs not satisfied
                # print error messages, update results, continue to next loop iteration
                print(ins + "Prerequisite failed:  Media required and no media filename recorded.")
                print(ins + "SKIPPING", item["asset_id"])
                item["skip_reason"] = f"mmif-{mmifi}-prereq"
                update_tried( item, cf, tried_l, l_lock)
                return item
            else:
                print(ins + "Prerequisites passed.")

            if item["media_type"] == "Moving Image":
                mime = "video"
            elif item["media_type"] == "Sound":
                mime = "audio"
            else:
                print(ins + "Warning: media type of " + item["asset_id"] + 
                    " is `" + item["media_type"] + "`." )
                print(ins + "Using 'video' as the MIME type." )
                mime = "video"
            mmif_str = make_blank_mmif(item["media_filename"], mime)

            with open(mmif_path, "w") as file:
                num_chars = file.write(mmif_str)
            if num_chars < len(mmif_str):
                raise Exception("Tried to write MMIF, but failed.")
        
        mmif_status = mmif_check(mmif_path)
        if 'blank' in mmif_status:
            print(ins + "Blank MMIF file successfully created.")
            item["mmif_files"].append(mmif_filename)
            item["mmif_paths"].append(mmif_path)
        else:
            # step failed
            # print error messages, update results, continue to next loop iteration
            mmif_check(mmif_path, complain=True)
            print(ins + "SKIPPING", item["asset_id"])
            item["skip_reason"] = f"mmif-{mmifi}"
            cleanup_media(cf, item)
            update_tried( item, cf, tried_l, l_lock)
            return item


    #############################################################
    # Construct CLAMS calls and call CLAMS apps, save output MMIF
    # (create MMIF 1 thru n)

    print(ins)
    print(ins + '# CREATING ANNOTATION-LADEN MMIF WITH CLAMS')

    print(ins + "Will run", clams["num_stages"], "round(s) of CLAMS processing.")
    clams_failed = False

    for i in range(clams["num_stages"]):

        # Don't run another stage of CLAMS processing if previous stage failed
        if clams_failed:
            # Go to next step of clams stages loop
            # (does not break out of the item)
            continue

        mmifi += 1
        clamsi = mmifi - 1
        print(ins)
        print(ins + f'## Making MMIF _{mmifi}')

        # Define MMIF for this step of the job
        mmif_filename = item["asset_id"] + "_" + cf["job_id"] + "_" + str(mmifi) + ".mmif"
        mmif_path = cf["mmif_dir"] + "/" + mmif_filename

        # Decide whether to use existing MMIF file or create a new one
        make_new_mmif = True
        if ( os.path.isfile(mmif_path) and not cf["overwrite_mmif"]):
            # Check to make sure file isn't implausibly small.
            # (Sometimes aborted processes leave around 0 byte mmif files.)
            if ( os.path.getsize(mmif_path) > 100 ):
                # check to make sure MMIF file is valid
                if 'valid' in mmif_check(mmif_path):
                    print(ins + "Will use existing MMIF:    " + mmif_path)
                    make_new_mmif = False
                else:
                    print(ins + "Existing MMIF file is not valid.  Will overwrite.")
            else:
                print(ins + "Existing MMIF file is only", 
                    os.path.getsize(mmif_path), 
                    "bytes.  Will overwrite.")
        
        if make_new_mmif:
            # Need to make new MMIF file.  Going to run a CLAMS app
            print(ins + "Will try making MMIF file: " + mmif_path)

            # Check for prereqs
            mmif_status = mmif_check(item["mmif_paths"][mmifi-1])
            if 'valid' not in mmif_status:
                # prereqs not satisfied
                mmif_check(mmif_path, complain=True)
                print(ins + "Prerequisite failed:  Input MMIF is not valid.")
                print(ins + "SKIPPING", item["asset_id"])
                item["skip_reason"] = f"mmif-{mmifi}-prereq"
                clams_failed = True
                # Go to next step of clams stages loop
                # (does not break out of the item)
                continue
            else:
                print(ins + "Prerequisites passed.")

            # Check to see how we're running the CLAMS app and proceed accordingly
            if "endpoint" in clams["apps"][clamsi]:
                ################################################################
                # Run CLAMS app, assuming the app is already running as a local web service
                endpoint = clams["apps"][clamsi]["endpoint"]

                print(ins + "Sending request to a CLAMS web service at " + endpoint)

                if len(clams["param_sets"][clamsi]) > 0:
                    # build querystring with parameters in job configuration
                    qsp = "?"
                    for p in clams["param_sets"][clamsi]:
                        qsp += p
                        qsp += "="
                        qsp += str(clams["param_sets"][clamsi][p])
                        qsp += "&"
                    qsp = qsp[:-1] # remove trailing "&"
                else:
                    qsp = ""

                uri = endpoint + qsp

                headers = {'Accept': 'application/json'}

                with open(item["mmif_paths"][mmifi-1], "r") as file:
                    mmif_str = file.read()

                try:
                    # send request to the the CLAMS endpoint
                    response = requests.post(uri, headers=headers, data=mmif_str)
                except Exception as e:
                    print(ins + "Encountered exception:", e)
                    print(ins + "Failed to get a response from the CLAMS web service.")
                    print(ins + "Check CLAMS web service and resume before batch item:", item["item_num"])
                    raise SystemExit("Exiting script.") from e

                print(ins + "CLAMS app web serivce response code:", response.status_code)
                
                # use the HTTP response as appropriate
                if response.status_code :
                    mmif_str = response.text
                    if response.status_code == 500:
                        mmif_path += "500"

                # Write out MMIF file
                if mmif_str != "":
                    with open(mmif_path, "w") as file:
                        num_chars = file.write(mmif_str)
                    if num_chars < len(mmif_str):
                        raise Exception("Tried to write MMIF, but failed.")
                    print(ins + "MMIF file created.")

            elif "image" in clams["apps"][clamsi]:
                ################################################################
                # Run CLAMS app by running the Docker image
                image = clams["apps"][clamsi]["image"]

                print(ins + "Attempting to run a CLAMS Docker image: " + image)

                input_mmif_filename = item["mmif_files"][mmifi-1]
                output_mmif_filename = mmif_filename

                # Set the environment-specific path to Docker and Windows-specific additions
                current_os = platform.system()
                if current_os == "Windows":
                    docker_bin_path = "/mnt/c/Program Files/Docker/Docker/resources/bin/docker"
                    coml_prefix = ["bash"]
                elif current_os == "Linux":
                    docker_bin_path = "/usr/bin/docker"
                    coml_prefix = []
                else:
                    raise OSError(f"Unsupported operating system: {current_os}")

                # build shell command as list for `subprocess.run()`
                coml = [
                        docker_bin_path, 
                        "run",
                        "-i",
                        "--rm",
                        "-v",
                        cf["shell_mmif_dir"] + '/:/mmif'
                    ]
                if cf["media_required"]:
                    coml += [ "-v", cf["shell_media_dir"] + '/:/data' ]
                if cf["shell_cache_dir"]:
                    coml += [ "-v", cf["shell_cache_dir"] + '/:/cache' ]
                if "gpus" in clams["apps"][clamsi]:
                    coml += [ "--gpus", clams["apps"][clamsi]["gpus"] ]
                coml += [
                        image,
                        "python",
                        "cli.py"
                    ]
                coml = coml_prefix + coml
    
                # If there are parameters, add them to the command list
                if len(clams["param_sets"][clamsi]) > 0:
                    app_params = []
                    for p in clams["param_sets"][clamsi]:
                        if type(clams["param_sets"][clamsi][p]) != dict:
                            # parameter is not nested; just add it
                            app_params.append( "--" + p )
                            app_params.append( str(clams["param_sets"][clamsi][p]) )
                        else:
                            # parameter is a dictionary; break it into separately
                            # specified parameters
                            for mkey in clams["param_sets"][clamsi][p]:
                                app_params.append( "--" + p )
                                mvalue = clams["param_sets"][clamsi][p][mkey]
                                app_params.append( mkey + ":" +  mvalue )

                    # Work-around to delimit values passed with --map flag:
                    # Add a dummy flag
                    app_params.append("--")
                
                    coml += app_params

                coml.append("/mmif/" + input_mmif_filename)
                coml.append("/mmif/" + output_mmif_filename)

                #print(coml) # DIAG
                #print( " ".join(coml) ) # DIAG

                # actually run the CLAMS app
                result = subprocess.run(coml, capture_output=True, text=True)

                if result.stderr:
                    print(ins + "Warning: CLI returned with content in stderr.")
                    if clams["show_cli_stderr"]:
                        print(ins + "Content of stderr:")
                        print(result.stderr)
                    item["problems"] += [ "clams-" + str(clamsi) + ":stderr" ]
                else:
                    print(ins + "CLAMS app finished without errors.")


        # Validate CLAMS app run
        mmif_status = mmif_check(mmif_path)
        if ('laden' in mmif_status and 'error-views' not in mmif_status):
            item["mmif_files"].append(mmif_filename)
            item["mmif_paths"].append(mmif_path)
        else:
            # step failed
            # print error messages, update results, mark the CLAMS processing has failed
            mmif_check(mmif_path, complain=True)
            clams_failed = True
            

    if clams_failed:
        # step failed
        # print error messages, update results, continue to next loop iteration
        print(ins + "SKIPPING", item["asset_id"])
        item["skip_reason"] = f"mmif-{mmifi}"
        cleanup_media(cf, item)
        update_tried( item, cf, tried_l, l_lock)
        return item


    ########################################################
    # Process MMIF and get useful output
    # 
    
    print(ins)
    print(ins + '# POSTPROCESSING ANNOTATION-LADEN MMIF')

    if len(post_procs) == 0:
        print(ins + "No postprocessing procedures requested.  Will not postprocess.")

    else:
        # Check for prereqs
        mmif_status = mmif_check(item["mmif_paths"][mmifi])
        if ('laden' not in mmif_status or 'error-views' in mmif_status):
            # prereqs not satisfied
            # print error messages, update results, continue to next loop iteration
            mmif_check(item["mmif_paths"][mmifi], complain=True)
            print(ins + "Step prerequisite failed: MMIF contains error views or lacks annotations.")
            print(ins + "SKIPPING", item["asset_id"])
            item["skip_reason"] = "usemmif-prereq"
            update_tried( item, cf, tried_l, l_lock)
            return item
        else:
            print(ins + "Step prerequisites passed.")

        # Loop throug and run each post processing procedure that has been listed.
        for post_proc in post_procs:
        
            if "name" not in post_proc:
                print(ins + "Postprocessing procedure not named.  Will not attempt.")
            else:
                print(ins + "Will attempt to run postprocessing procedure:", post_proc["name"])

                # Call separate procedure for appropraite post-processing
                if post_proc["name"].lower() in ["swt", "visaid_builder", "visaid-builder", "visaid"] :

                    pp_errors, pp_problems, pp_infos = visaid_builder.post_proc_item.run_post(
                        item=item, 
                        cf=cf,
                        params=post_proc )

                    if pp_errors not in [ None, [] ]:
                        print(ins + "Warning:", post_proc["name"], "returned errors:", pp_errors)
                        item["errors"] += [ post_proc["name"]+":"+e for e in pp_errors ]
                        print(ins + "PROCEEDING.")

                    if pp_problems not in [ None, [] ]:
                        print(ins + "Warning:", post_proc["name"], "encountered problems:", pp_problems)
                        item["problems"] += [ post_proc["name"]+":"+p for p in pp_problems ]
                        print(ins + "PROCEEDING.")

                    if pp_infos not in [ None, [] ]:
                        item["infos"] += [ post_proc["name"]+":"+m for m in pp_infos ]

                elif post_proc["name"].lower() in ["transcript_converter"] :

                    pp_errors, pp_problems, pp_infos = transcript_converter.post_proc_item.run_post(
                        item=item, 
                        cf=cf,
                        params=post_proc )

                    if pp_errors not in [ None, [] ]:
                        print(ins + "Warning:", post_proc["name"], "returned errors:", pp_errors)
                        item["errors"] += [ post_proc["name"]+":"+e for e in pp_errors ]
                        print(ins + "PROCEEDING.")

                    if pp_problems not in [ None, [] ]:
                        print(ins + "Warning:", post_proc["name"], "encountered problems:", pp_problems)
                        item["problems"] += [ post_proc["name"]+":"+p for p in pp_problems ]
                        print(ins + "PROCEEDING.")

                    if pp_infos not in [ None, [] ]:
                        item["infos"] += [ post_proc["name"]+":"+m for m in pp_infos ]

                else:
                    print(ins + "Invalid postprocessing procedure:", post_proc)


    ########################################################
    # Done with this item.  
    # 

    # Record running time
    tn = datetime.datetime.now()
    item["elapsed_seconds"] = (tn-ti).seconds

    # Clean up
    cleanup_media(cf, item)

    # Update results to reflect this iteration of the loop
    update_tried( item, cf, tried_l, l_lock)

    # print summary item info
    print(ins + f'Elapsed time for item #{item["item_num"]}:  {item["elapsed_seconds"]}s')


# end of function for running items
########################################################


if __name__ == "__main__":
    main()
