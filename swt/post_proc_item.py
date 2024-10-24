"""
post_proc_item.py

Defines functions for doing post processing of MMIF created by SWT
"""

# %%
# Run import statements

import csv
import json

from mmif import Mmif

import drawer.lilhelp
import swt.process_swt

MODULE_VERSION = "0.1"

# The latest valid start time for the program (if not set by config)
#   (We won't look for the main program slate after this point.)
#   (And we won't assign a proxy start time after this point.)
DEFAULT_PROG_START_MAX = 150000


def run_post(item, cf, post_proc, mmif_path):
    """
    Calls particular methods to run post processing for the item according to the 
    configuration specified in the `cf` and `post_proc` dictionaries.
    """

    artifacts_dir = cf["artifacts_dir"]

    if "name" in post_proc:
        if post_proc["name"].lower() != "swt":
            print("Post-processing error: Tried to run", post_proc["name"],
                  "process with SWT post-processing function.")
            return False
    else:
        print("Post-processing error: No post-process or name specified.")
        return False

    # Set up for the particular kinds of artifacts requested 
    if "artifacts" in post_proc:
        artifacts = post_proc["artifacts"]
    else:
        artifacts = []

    artifacts_dir = cf["artifacts_dir"]

    if "data" in artifacts:
        data_dir = artifacts_dir + "/data"
        infer_data = True
    else:
        infer_data = False

    if "slates" in artifacts:
        slates_dir = artifacts_dir + "/slates"
        get_slate = True
    else:
        get_slate = False

    if "visaids" in artifacts:
        visaids_dir = artifacts_dir + "/visaids"
        make_visaid = True
    else:
        make_visaid = False
    
    if "reps" in artifacts:
        reps_dir = artifacts_dir + "/reps"
        get_reps = True
    else:
        get_reps = False

    if "ksl" in artifacts:
        ksl_dir = artifacts_dir + "/ksl"
        make_ksl_index = True
    else:
        make_ksl_index = False

    if "prog_start_max" in post_proc:
        prog_start_max = post_proc["prog_start_max"]
    else:
        prog_start_max = DEFAULT_PROG_START_MAX

    if "subsampling" in post_proc:
        subsampling = post_proc["subsampling"]
    else:
        subsampling = None

    if "max_gap" in post_proc:
        max_gap = post_proc["max_gap"]
    else:
        max_gap = None


    # Open MMIF and start processing
    with open(mmif_path, "r") as file:
        mmif_str = file.read()

    # call SWT MMIF processors to get a table of time frames
    tfs = swt.process_swt.list_tfs(mmif_str, max_gap=max_gap, subsampling=subsampling)

    # get metadata_str
    metadata_str = swt.process_swt.get_mmif_metadata_str(mmif_str)


    #
    # Infer metadata
    #
    if infer_data:
        print("Attempting to infer data...")

        # Calculate some significant datapoints based on table of time frames
        #
        # Note:  For reasons I don't understand, we have to cast some integer
        # values originally created by Pandas to int from int64

        # The end of the bars is the end of the last bars timeframe
        # If there is no bars timeframe, then the value is 0
        bars_end = 0
        bars_tfs = [ tf for tf in tfs 
                        if (tf[1] in ['bars'] and tf[3] <= prog_start_max) ]
        if len(bars_tfs) > 0:
            bars_end = int(bars_tfs[-1][3])

        # Proxy starts at the end of the bars or the beginning of the slate,
        # whichever is greater
        slate_begin = None
        slate_tfs = [ tf for tf in tfs 
                        if (tf[1] in ['slate'] and tf[3] <= prog_start_max)]
        if len(slate_tfs) > 0:
            slate_begin = int(slate_tfs[0][2])
            proxy_start_ms = max(bars_end, slate_begin)
        else:
            proxy_start_ms = bars_end

        # print("bars end:", bars_end, "slate begin:", slate_begin, "proxy start:", proxy_start_ms) # DIAG

        item["proxy_start"] = proxy_start_ms / 1000

        print("Proxy start:", item["proxy_start"])


    #
    # Extract the slate
    #
    if get_slate:
        print("Attempting to save a slate...")

        # The slate rep is the rep timepoint from from the first slate timeframe
        # If there is not slate timeframe, then the value is None
        slate_rep = None
        slate_tfs = [ tf for tf in tfs if tf[1] in ['slate'] ]
        if len(slate_tfs) > 0:
            slate_rep = int(slate_tfs[0][4])

        if slate_rep is not None:
            try:
                count = drawer.lilhelp.extract_stills( 
                           item["media_path"], 
                           [ slate_rep ], 
                           item["asset_id"],
                           slates_dir,
                           verbose=False )
                if count == 1:
                    print("Slate saved.")
                else:
                    print("Warning: Saved", count, "slates.")

            except Exception as e:
                print("Extraction of slate frame at", slate_rep ,"failed.")
                print("Error:", e)
            
        else:
            print("No slate found.")


    #
    # Extract representative stills from timeframes
    #
    if get_reps:
        print("Attempting to save representative stills...")

        if len(tfs) > 0:
            tps = [ tf[4] for tf in tfs ] 
            tps = list(set(tps))
            tps.sort()

            try:
               rep_images = drawer.lilhelp.extract_stills( 
                            item["media_path"], 
                            tps, 
                            item["asset_id"],
                            reps_dir,
                            verbose=False )

            except Exception as e:
               print("Extraction of frame at", slate_rep ,"failed.")
               print("Error:", e)  

            print("Saved", len(rep_images), "representative stills from", len(tfs), "scenes.")

        else:
            print("No scenes from which to extract stills.")


    # 
    # Create KSL-style index of still images extracted
    #
    if make_ksl_index:
        print("Attempting to make a KSL-style index...")

        if not get_reps:
            print("Cannot make index because representative stills were not extracted.")
        else:

            # build KSL data for this item
            ksl_arr = []
            for fname in rep_images:
                
                # extract the requersted frame time from the filename
                tp = int(fname.split("_")[2])

                # lookup label in tfs array
                label = [ tf[5] for tf in tfs if tf[4] == tp ][0]

                if label.find(":") != -1:
                    label, sublabel = label.split(":")
                else:
                    sublabel = ""

                row = [ fname, label, sublabel, "Job ID: "+cf["job_id"] ]
                ksl_arr.append(row) 

            # set name of index 
            ksl_index_path = ksl_dir + "/img_label_predictions.csv"

            # append to CSV file
            with open(ksl_index_path, 'a') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerows(ksl_arr)
            
            print("Appended", len(ksl_arr), "rows to image index CSV.")

            # Now, to rewrite the JS file
            # load full array based on updated CSV file
            full_ksl_arr = []
            with open(ksl_index_path, 'r') as csvfile:
                reader = csv.reader(csvfile)
                for row in reader:
                    full_ksl_arr.append(row)
            
            # check for duplicates and remove them
            full_ksl_tups = set(tuple(r) for r in full_ksl_arr)
            if len(full_ksl_arr) != len( full_ksl_tups ):
                print("Warning: Duplicate items in accumulated KSL array.")
                full_ksl_arr = [ list(tup) for tup in full_ksl_tups ] 

            full_ksl_arr.sort(key=lambda f:f[0])

            # build JS array file
            proto_js_arr = [ [r[0], False, r[1], r[2], False, "", ""] for r in full_ksl_arr ]

            # convert array to a JSON string 
            image_array_j = json.dumps(proto_js_arr)

            # prettify with line breaks
            image_array_j = image_array_j.replace("[[", "[\n[")
            image_array_j = image_array_j.replace("], [", "], \n[")
            image_array_j = image_array_j.replace("]]", "]\n]")

            # add bits around the JSON text to make it valid Javascript
            image_array_j = "imgArray=\n" + image_array_j
            image_array_j = image_array_j + "\n;"

            # write Javascript file 
            array_pathname = ksl_dir + "/img_arr_init.js"
            with open(array_pathname, "w") as array_file:
                array_file.write(image_array_j)
            
            print("Updated image index JS, now with", len(proto_js_arr), "entries.")


    #
    # Save a visaid
    #
    if make_visaid:
        print("Attempting to make a visaid...")

        visaid_filename = visaid_path = None

        if "scene_types" in post_proc:
            scene_types = post_proc["scene_types"]
        else:
            scene_types = []

        try:
            visaid_filename, visaid_path = swt.process_swt.create_aid( 
                video_path=item["media_path"], 
                tfs=tfs, 
                stdout=False, 
                output_dirname=visaids_dir,
                job_id=cf["job_id"],
                job_name=cf["job_name"], 
                guid=item["asset_id"],
                types=scene_types,
                metadata_str=metadata_str,
                max_gap=max_gap,
                subsampling=subsampling
                )

            if visaid_path:
                print("Visual index created at")
                print(visaid_path)
            else:
                print("Creation of visaid failed.")

        except Exception as e:
            print("Creation of visaid failed.")
            print("Error:", e)
