
import argparse
import os
import sys
import json


def print_simple_summary(tried_l):
    
    num_tries = len( tried_l )
    num_skips = len( [item for item in tried_l if item["skip_reason"] not in [""]] )
    num_errors = len( [item for item in tried_l if len(item["errors"]) > 0 ] )
    num_problems = len( [item for item in tried_l if len(item["problems"]) > 0 ] )

    print(num_skips, "out of", num_tries, "items were skipped.")
    print(num_errors, "out of", num_tries, "items had errors.")
    print(num_problems, "out of", num_tries, "items had problems.")
    

def print_summary(tried_l):

    num_tries = len( tried_l )

    skips = [item for item in tried_l if item["skip_reason"] not in [""]]

    


def main():
    
    parser = parser = argparse.ArgumentParser(
        prog='runlog_summarizer.py',
        description='Creates a user-friendly summary from clams-kitchen runlog',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument("-f", "--logfile", metavar="LOG", nargs="?",
        help="Path to a single runlog")

    # parser.add_argument("-d", "--jobdir", metavar="DIR", nargs="?",
    #     help="Path to directory containing runlogs")

    args = parser.parse_args()

    if args.logfile is not None:
        logfile = args.logfile
    



if __name__ == "__main__":
    main()
