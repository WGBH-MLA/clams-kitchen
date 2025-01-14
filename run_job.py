"""
run_job.py

This script runs CLAMS applications against a batch of assets by looping through 
the items in the batch, taking several steps with each one.  

It uses several data structures that are global for this module.

`cf` - the job configuration dictionary. Most of the values are set by the 
job configuration file.  Some can be set from the command line.  Some
are calculated at the beginning of the job.  It has the following keys:
   - start_timestamp (str)
   - job_id (str) 
   - job_name (str) 
   - logs_dir (str)    
   - just_get_media (bool)
   - start_after_item (int)
   - end_after_item (int)
   - overwrite_mmif (bool)
   - cleanup_media_per_item (bool)
   - cleanup_beyond_item (int)
   - artifacts_dir (str)

`clams_run_cli` - bool indicating whether to run CLAMS apps as CLI or web service   

`clams_endpoints` - a list of URLS for web service endpoints for CLAMS apps

`clams_images` - a list of names for Docker images for CLAMS apps 

`clams_params` - a list of dictionaries of parameter values for CLAMS apps 

`post_proc` - a dictionary with the parameters for the post-processing routine

`batch_l` - a list of items in the batch.  Each item is a dictionary with keys set
by the columns of the batch definition list CSV file.  In addition, it includes the
following keys:
   - asset_id (str)
   - batch_item (int)
   - skip_reason (str)
   - media_filename (str)
   - media_path (str)
   - mmif_files (list of str)
   - mmif_paths (list of str)
   - elapsed_seconds (int)
"""

# %%
# Import modules

import os
import platform
import csv
import json
import datetime
import warnings
import subprocess
import argparse
import requests

import visaid_builder.post_proc_item

from drawer.media_availability import check_avail, make_avail, remove_media
from drawer.mmif_adjunct import make_blank_mmif, mmif_check

########################################################
# %%
# Define helper functions

def write_job_results_log(cf, batch_l, item_count):
    """Write out results to a CSV file and to a JSON file
    Only write out records that have been reached so far
    """

    # Results files get a new name every time this script is run
    job_results_log_file_base = ( cf["logs_dir"] + "/" + cf["job_id"] + 
                                    "_" + cf["start_timestamp"] + "_runlog" )
    job_results_log_csv_path  = job_results_log_file_base + ".csv"
    job_results_log_json_path  = job_results_log_file_base + ".json"

    with open(job_results_log_csv_path, 'w', newline='') as file:
        fieldnames = batch_l[0].keys()
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(batch_l[:(item_count-cf["start_after_item"])])
    
    with open(job_results_log_json_path, 'w') as file:
        json.dump(batch_l[:(item_count-cf["start_after_item"])], file, indent=2)


def cleanup_media(cf, item_count, item):
    """Cleanup media, i.e., remove media file for this item
    Do this only if the global settings allow it
    """
    
    print()
    print("# CLEANING UP MEDIA")

    if not cf["media_required"]:
        print("Job declared media was not required.  Will not attempt to clean up.")
    elif cf["cleanup_media_per_item"] and item_count > cf["cleanup_beyond_item"]:
        print("Attempting to remove media at", item["media_path"])
        removed = remove_media(item["media_path"])
        if removed:
            print("Media removed.")
    else:
        print("Leaving media for this item.")


########################################################
# %%

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

########################################################
# %%
print()

# Set job-specific configuration based on values in configuration file
with open(job_conf_path, "r") as jsonfile:
    conffile = json.load(jsonfile)

# Dictionaries to store configuation information for this job
# These will be based on the conffile dictionary, but checked and normalized
cf = {}
post_proc = {}

t0 = datetime.datetime.now()
cf["start_timestamp"] = t0.strftime("%Y%m%d_%H%M%S")

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

    # Paths for local_base and mnt_base will usually be the same in a 
    # POSIX-like environment.
    # They differ in a Windows environment where the local_base may begin with
    # Windows drive letters, e.g., "C:/Users/..." and the mnt_base may be 
    # translated to a POSIX-compatible format, e.g., "/mnt/c/Users/...".
    if "local_base" in conffile:
        local_base = conffile["local_base"]
    else:
        local_base = ""

    if cli_batch_def_path is not None:
        batch_def_path = cli_batch_def_path
    else:
        #  "def_path" is required if not specified on the command line
        batch_def_path = local_base + conffile["def_path"]

    if "mnt_base" in conffile:
        mnt_base = conffile["mnt_base"]
    else:
        mnt_base = local_base

    # "results_dir" is required
    results_dir = local_base + conffile["results_dir"]
    mnt_results_dir = mnt_base + conffile["results_dir"]
    
    # "media_dir" is required
    media_dir = local_base + conffile["media_dir"]
    mnt_media_dir = mnt_base + conffile["media_dir"]

    if "mmif_dir" in conffile:
        mmif_dir = local_base + conffile["mmif_dir"]
        mnt_mmif_dir = mnt_base + conffile["mmif_dir"]
    else:
        mmif_dir_name = "mmif"
        mmif_dir = results_dir + "/" + mmif_dir_name 
        mnt_mmif_dir = mnt_results_dir + "/" + mmif_dir_name 

    if "logs_dir" in conffile:
        cf["logs_dir"] = local_base + conffile["logs_dir"]
    else:
        cf["logs_dir"] = results_dir

    # Checks to make sure directories and setup file exist
    for dirpath in [results_dir, cf["logs_dir"], media_dir, batch_def_path]:
        if not os.path.exists(dirpath):
            raise FileNotFoundError("Path does not exist: " + dirpath)


    # Additional configuration options
    if "media_required" in conffile:
        cf["media_required"] = conffile["media_required"]
    else:
        cf["media_required"] = True

    if cli_just_get_media:
        cf["just_get_media"] = True
    elif "just_get_media" in conffile:
        cf["just_get_media"] = conffile["just_get_media"]
    else:
        cf["just_get_media"] = False

    if "start_after_item" in conffile:
        cf["start_after_item"] = conffile["start_after_item"]
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


    # CLAMS config

    if "clams_run_cli" in conffile:
        clams_run_cli = conffile["clams_run_cli"]
    elif cf["just_get_media"]:
        clams_run_cli = False
    else:
        clams_run_cli = True

    if cf["just_get_media"]:
        num_clams_stages = 0
        clams_endpoints = clams_images = []
    elif not clams_run_cli:
        # need to know the URLs of the webservices if (but only if) not running
        # in CLI mode 
        clams_endpoints = conffile["clams_endpoints"]
        clams_images = []
        num_clams_stages = len(clams_endpoints)
    else:
        # need to know the docker image if (but only if) running in CLI mode
        clams_images = conffile["clams_images"]
        clams_endpoints = []
        num_clams_stages = len(clams_images)

    if "clams_params" in conffile:
        clams_params = conffile["clams_params"]
    else:
        clams_params = []

    if len(clams_params) != num_clams_stages:
        raise RuntimeError("Number of CLAMS stages not equal to number of sets of CLAMS params.") 


    # Post-processing configuration options

    if "post_proc" in conffile:
        post_proc = conffile["post_proc"]

        if "name" not in post_proc:
            post_proc["name"] = ""
    else:
        post_proc = {}

    if "artifacts" in post_proc:
        # directory for all artifacts (not including MMIF files)
        cf["artifacts_dir"] = results_dir + "/" + "artifacts"
    else:
        post_proc["name"] = ""
        post_proc["artifacts"] = []
        cf["artifacts_dir"] = ""

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


#########################################################
# Check and/or create directories for job output

# Create list of dirs to create/validate
dirs = [mmif_dir]

if len(post_proc["artifacts"]) > 0:

    dirs.append(cf["artifacts_dir"])
    
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


########################################################
# %%
# Process batch in a loop

# Make sure at least an empty list exists to define the batch
# (This value should get overwritten when we open a batch def file in the next 
# step. However, if there is no such file, having an empty list this enables 
# us to exit the empty loop gracefully.)
batch_l = []

# open batch as a list of dictionaries
with open(batch_def_path, encoding='utf-8', newline='') as csvfile:
    batch_l = list(csv.DictReader(csvfile))

# restrict to the appropriate subset
batch_l = batch_l[cf["start_after_item"]:cf["end_after_item"]]

item_count = cf["start_after_item"]

# Main loop
for item in batch_l:
    ti = datetime.datetime.now()

    tis = ti.strftime("%Y-%m-%d %H:%M:%S")

    item_count += 1
    print()
    print()
    print(" * ")
    print("*** ITEM #", item_count, ":", item["asset_id"], "[", cf["job_name"], "]", tis)
    print(" * ")

    ########################################################

    # set default value for `media_type` if this is not supplied
    if "media_type" not in item:
        item["media_type"] = "Moving Image"
        print("Warning:  Media type not specified. Assuming it is 'Moving Image'.")

    # initialize new dictionary elements for this item
    item["batch_item"] = item_count
    item["skip_reason"] = ""
    item["media_filename"] = ""
    item["media_path"] = ""
    item["mmif_files"] = []
    item["mmif_paths"] = []
    item["elapsed_seconds"] = None

    # set the index of the MMIF files so far for this item
    mmifi = -1

    ########################################################
    # Add media to the availability place, if it is not already there,
    # and update the dictionary

    print()
    print("# MEDIA AVAILABILITY")

    if not cf["media_required"]:
        print("Media declared not required.")
        print("Will continue.") 
    else:
        media_path = ""
        media_filename = check_avail(item["asset_id"], media_dir)

        if media_filename is not None:
            media_path = media_dir + "/" + media_filename
            print("Media already available:  ", media_path) 
        else:
            print("Media not yet available; will try to make available.") 
            if item["sonyci_id"] :
                media_filename = make_avail(item["asset_id"], item["sonyci_id"], media_dir)
                if media_filename is not None:
                    media_path = media_dir + "/" + media_filename
            else:
                print("No Ci ID for " + item["asset_id"])

        if media_filename is not None and os.path.isfile(media_path):
            item["media_filename"] = media_filename
            item["media_path"] = media_path
        else:
            # step failed
            # print error messages, updated results, continue to next loop iteration
            print("Media file for " + item["asset_id"] + " could not be made available.")
            print("SKIPPING", item["asset_id"])
            item["skip_reason"] = "media"
            write_job_results_log(cf, batch_l, item_count)
            continue

        if cf["just_get_media"]:
            print()
            print("Media acquisition successful.")
            # Update results (so we have a record of any failures)
            write_job_results_log(cf, batch_l, item_count)

            # continue to next iteration without additional steps
            continue


    ########################################################
    # Create blank MMIF file, if it's not already there
    # (create MMIF 0)

    print()
    print("# MAKING BLANK MMIF")
    mmifi += 1

    if not cf["media_required"]:
        print("Media declared not required, implying that blank MMIF is not required.") 
        print("Will continue.")

        # add empty strings for filename and path to this MMIF file
        item["mmif_files"].append("")
        item["mmif_paths"].append("")
    else:

        # define MMIF for this stage of this iteration
        mmif_filename = item["asset_id"] + "_" + str(mmifi) + ".mmif"
        mmif_path = mmif_dir + "/" + mmif_filename

        # Check to see if it exists; if not create it
        if ( os.path.isfile(mmif_path) and not cf["overwrite_mmif"]):
            print("Will use existing MMIF:    " + mmif_path)
        else:
            print("Will create MMIF file:     " + mmif_path)

            # Check for prereqs
            if cf["media_required"] and item["media_filename"] == "":
                # prereqs not satisfied
                # print error messages, updated results, continue to next loop iteration
                print("Prerequisite failed:  Media required and no media filename recorded.")
                print("SKIPPING", item["asset_id"])
                item["skip_reason"] = "mmif-0-prereq"
                write_job_results_log(cf, batch_l, item_count)
                continue
            else:
                print("Prerequisites passed.")

            if item["media_type"] == "Moving Image":
                mime = "video"
            elif item["media_type"] == "Sound":
                mime = "audio"
            else:
                print( "Warning: media type of " + item["asset_id"] + 
                    " is `" + item["media_type"] + "`." )
                print( "Using 'video' as the MIME type." )
                mime = "video"
            mmif_str = make_blank_mmif(item["media_filename"], mime)

            with open(mmif_path, "w") as file:
                num_chars = file.write(mmif_str)
            if num_chars < len(mmif_str):
                raise Exception("Tried to write MMIF, but failed.")
        
        mmif_status = mmif_check(mmif_path)
        if 'blank' in mmif_status:
            print("Blank MMIF file successfully created.")
            item["mmif_files"].append(mmif_filename)
            item["mmif_paths"].append(mmif_path)
        else:
            # step failed
            # print error messages, updated results, continue to next loop iteration
            mmif_check(mmif_path, complain=True)
            print("SKIPPING", item["asset_id"])
            item["skip_reason"] = "mmif-0"
            cleanup_media(cf, item_count, item)
            write_job_results_log(cf, batch_l, item_count)
            continue


    #############################################################
    # Construct CLAMS calls and call CLAMS apps, save output MMIF
    # (create MMIF 1 thru n)

    print()
    print("# CREATING ANNOTATION-LADEN MMIF WITH CLAMS")

    print("Will run", num_clams_stages, "round(s) of CLAMS processing.")
    clams_failed = False

    for i in range(num_clams_stages):

        # Don't run if previous step failed
        if clams_failed:
            continue

        mmifi += 1
        clamsi = mmifi - 1
        print()
        print("## Making MMIF #", mmifi)

        # Define MMIF for this step of the job
        mmif_filename = item["asset_id"] + "_" + cf["job_id"] + "_" + str(mmifi) + ".mmif"
        mmif_path = mmif_dir + "/" + mmif_filename

        # Decide whether to use existing MMIF file or create a new one
        make_new_mmif = True
        if ( os.path.isfile(mmif_path) and not cf["overwrite_mmif"]):
            # Check to make sure file isn't implausibly small.
            # (Sometimes aborted processes leave around 0 byte mmif files.)
            if ( os.path.getsize(mmif_path) > 100 ):
                # check to make sure MMIF file is valid
                if 'valid' in mmif_check(mmif_path):
                    print("Will use existing MMIF:    " + mmif_path)
                    make_new_mmif = False
                else:
                    print("Existing MMIF file is not valid.  Will overwrite.")
            else:
                print("Existing MMIF file is only", 
                    os.path.getsize(mmif_path), 
                    "bytes.  Will overwrite.")
        
        if make_new_mmif:
            # Need to make new MMIF file.  Going to run a CLAMS app
            print("Will try making MMIF file: " + mmif_path)

            # Check for prereqs
            mmif_status = mmif_check(item["mmif_paths"][mmifi-1])
            if 'valid' not in mmif_status:
                # prereqs not satisfied
                # print error messages, updated results, continue to next loop iteration
                mmif_check(mmif_path, complain=True)
                print("Prerequisite failed:  Input MMIF is not valid.")
                print("SKIPPING", item["asset_id"])
                item["skip_reason"] = "mmif-1-prereq"
                write_job_results_log(cf, batch_l, item_count)
                continue
            else:
                print("Prerequisites passed.")

            if not clams_run_cli :
                ################################################################
                # Run CLAMS app, assuming the app is already running as a local web service
                print("Sending request to CLAMS web service...")

                if len(clams_params[clamsi]) > 0:
                    # build querystring with parameters in job configuration
                    qsp = "?"
                    for p in clams_params[clamsi]:
                        qsp += p
                        qsp += "="
                        qsp += str(clams_params[clamsi][p])
                        qsp += "&"
                    qsp = qsp[:-1] # remove trailing "&"
                service = clams_endpoints[clamsi]
                endpoint = service + qsp

                headers = {'Accept': 'application/json'}

                with open(item["mmif_paths"][mmifi-1], "r") as file:
                    mmif_str = file.read()

                try:
                    # actually run the CLAMS app
                    response = requests.post(endpoint, headers=headers, data=mmif_str)
                except Exception as e:
                    print("Encountered exception:", e)
                    print("Failed to get a response from the CLAMS web service.")
                    print("Check CLAMS web service and resume before batch item:", item_count)
                    raise SystemExit("Exiting script.") from e

                print("CLAMS app web serivce response code:", response.status_code)
                
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
                    print("MMIF file created.")

            else:
                ################################################################
                # Run CLAMS app by calling the Docker image
                print("Attempting to call Dockerized CLAMS app CLI...")

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
                        "-v",
                        mnt_media_dir + '/:/data',
                        "-v",
                        mnt_mmif_dir + '/:/mmif',
                        "-i",
                        "--rm",
                        clams_images[clamsi],
                        "python",
                        "cli.py"
                    ]

                coml = coml_prefix + coml

                # If there are parameters, add them to the command list
                if len(clams_params[clamsi]) > 0:
                    app_params = []
                    for p in clams_params[clamsi]:
                        if type(clams_params[clamsi][p]) != dict:
                            # parameter is not nested; just add it
                            app_params.append( "--" + p )
                            app_params.append( str(clams_params[clamsi][p]) )
                        else:
                            # parameter is a dictionary; break it into separately
                            # specified parameters
                            for mkey in clams_params[clamsi][p]:
                                app_params.append( "--" + p )
                                mvalue = clams_params[clamsi][p][mkey]
                                app_params.append( mkey + ":" +  mvalue )

                    # Work-around to delimit values passed with --map flag:
                    # Add a dummy flag
                    app_params.append("--")
                
                    coml += app_params

                coml.append("/mmif/" + input_mmif_filename)
                coml.append("/mmif/" + output_mmif_filename)

                # print(coml) # DIAG
                # print( " ".join(coml) ) # DIAG

                # actually run the CLAMS app
                result = subprocess.run(coml, capture_output=True, text=True)

                if result.stderr:
                    print("Warning: CLI returned with error.  Contents of stderr:")
                    print(result.stderr)
                else:
                    print("CLAMS app finished without errors.")


        # Validate CLAMS app run
        mmif_status = mmif_check(mmif_path)
        if ('laden' in mmif_status and 'error-views' not in mmif_status):
            item["mmif_files"].append(mmif_filename)
            item["mmif_paths"].append(mmif_path)
        else:
            # step failed
            # print error messages, updated results, continue to next loop iteration
            mmif_check(mmif_path, complain=True)
            clams_failed = True
            

    if clams_failed:
        print("SKIPPING", item["asset_id"])
        item["skip_reason"] = "mmif-" + str(mmifi)
        cleanup_media(cf, item_count, item)
        write_job_results_log(cf, batch_l, item_count)
        continue


    ########################################################
    # Process MMIF and get useful output
    # 
    
    print()
    print("# POSTPROCESSING ANNOTATION-LADEN MMIF")

    if post_proc["name"] == "" :
        print("No postprocessing procedure named.  Will not postprocess.")

    else:
        print("Will attempt to run postprocessing procedure:", post_proc["name"])
        # Check for prereqs
        mmif_status = mmif_check(item["mmif_paths"][mmifi])
        if ('laden' not in mmif_status or 'error-views' in mmif_status):
            # prereqs not satisfied
            # print error messages, updated results, continue to next loop iteration
            mmif_check(mmif_path, complain=True)
            print("Step prerequisite failed: MMIF contains error views or lacks annotations.")
            print("SKIPPING", item["asset_id"])
            item["skip_reason"] = "usemmif-prereq"
            write_job_results_log(cf, batch_l, item_count)
            continue
        else:
            print("Step prerequisites passed.")


        # Call separate procedure for appropraite post-processing
        if post_proc["name"].lower() == "swt" :
            visaid_builder.post_proc_item.run_post(item=item, 
               cf=cf,
               post_proc=post_proc, 
               mmif_path=item["mmif_paths"][mmifi])
        else:
            print("Invalid postprocessing procedure:", post_proc)


    ########################################################
    # Done with this item.  
    # 

    # Record running time
    tn = datetime.datetime.now()
    item["elapsed_seconds"] = (tn-ti).seconds

    # Clean up
    cleanup_media(cf, item_count, item)

    # Update results to reflect this iteration of the loop
    write_job_results_log(cf, batch_l, item_count)

    # print diag info
    print()
    print("Elapsed time for this item:", item["elapsed_seconds"], "seconds")



# end of main processing loop
########################################################

tn = datetime.datetime.now()

num_skips = len( [item for item in batch_l if item["skip_reason"] != ""] )

print()
print("****************************")
print()
print("Job finished at", tn.strftime("%Y-%m-%d %H:%M:%S"))
print("Total elapsed time:", (tn-t0).days, "days,", (tn-t0).seconds, "seconds")
print("Skipped", num_skips, "items, out of", len(batch_l), "total items.")
print("Results logged in", cf["logs_dir"])
print()

