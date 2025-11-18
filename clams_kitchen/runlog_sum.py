
"""
runlog_sum.py

Functions to creates a user-friendly summaries from clams-kitchen runlogs
"""

import argparse
import os
import sys
import json
import datetime


def print_simple_summary(tried_l):
    
    skips = [item for item in tried_l if item["skip_reason"] not in [""]]
    errors = [item for item in tried_l if len(item["errors"]) > 0 ] 
    problems = [item for item in tried_l if len(item["problems"]) > 0 ] 
    infos = [item for item in tried_l if len(item["infos"]) > 0 ] 

    print_timing(tried_l)
    print()

    print(len(skips), "out of", len(tried_l), "items were skipped.")
    print(len(errors), "out of", len(tried_l), "items had errors.")
    print(len(problems), "out of", len(tried_l), "items had problems.")
    print(len(infos), "out of", len(tried_l), "items had info.")


def print_summary(tried_l):

    print()
    print("Logged attempts for", len(tried_l), "items.")
    print()

    print_timing(tried_l)
    print()

    skips = [item for item in tried_l if item["skip_reason"] not in [""]]
    errors = [item for item in tried_l if len(item["errors"]) > 0 ] 
    problems = [item for item in tried_l if len(item["problems"]) > 0 ] 
    infos = [item for item in tried_l if len(item["infos"]) > 0 ] 

    print(len(skips), "out of", len(tried_l), "items were skipped.")
    print(len(errors), "out of", len(tried_l), "items had errors.")
    print(len(problems), "out of", len(tried_l), "items had problems.")
    print(len(infos), "out of", len(tried_l), "items had info.")

    if len(skips) > 0:
        print()
        print("Items skipped:")
        for item in skips:
            print(f" #{item['item_num']}:\t{item['asset_id']}\tReason: {item['skip_reason']}")

    if len(errors) > 0:
        print()
        print("Items with errors:")
        for item in errors:
            print(f" #{item['item_num']}:\t{item['asset_id']}\tErrors: {item['errors']}")

    if len(problems) > 0:
        print()
        print("Items with problems:")
        for item in problems:
            print(f" #{item['item_num']}:\t{item['asset_id']}\tProblems: {item['problems']}")


def print_skipped_list(tried_l):
    skips = [item for item in tried_l if item["skip_reason"] not in [""]]

    print()
    print("Job item numbers of items skipped:")
    print( [item['item_num'] for item in skips] )


def print_consec(tried_l):
    items_done = [ item['item_num'] for item in tried_l ]
    items_done.sort()

    first = items_done[0]
    last_consec = first
    idx_check = 1

    while idx_check < len(items_done):
        if items_done[idx_check] == 1 + last_consec:
            last_consec = items_done[idx_check]
        else:
            break
        idx_check += 1

    print()
    print(f"Consecutive items attempted: #{first} to #{last_consec} (inclusive)")
    

def print_infos(tried_l):

    infos = [item for item in tried_l if len(item["infos"]) > 0 ] 

    if len(infos) > 0:
        print()
        print("Items with info:")
        for item in infos:
            print(f" #{item['item_num']}:\t{item['asset_id']}\tInfo: {item['infos']}")


def print_timing(tried_l):

    if not len(tried_l):
        # no list of cooked items
        pass
    elif "time_began" not in tried_l[0]:
        # no timing info in runlog
        pass
    else:
        # First item begun is the item with the lowest item number, 
        # not necessarily the first item in the list.
        began = datetime.datetime.fromisoformat(sorted(tried_l, key=lambda x: x["item_num"])[0]["time_began"])
        # Last item finished is last item in list.
        ended = datetime.datetime.fromisoformat(tried_l[-1]["time_ended"])

        days = (ended-began).days
        seconds = (ended-began).seconds

        print(f'Initial  item  began: {began.strftime("%Y-%m-%d %H:%M:%S")}')
        print(f'Latest item finished: {ended.strftime("%Y-%m-%d %H:%M:%S")}  ({days} days, {seconds} seconds later)')


def main():
    
    parser = parser = argparse.ArgumentParser(
        prog='cookreview',
        description='Creates a user-friendly summary from clams-kitchen cooklog',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument("-s", "--simple", action="store_true",
        help="Print just a simple summary, not the full summary")
    parser.add_argument("-i", "--infos", action="store_true",
        help="Print infos about any items that have it.")
    parser.add_argument("--list-skipped", action="store_true",
        help="Print a list of job item numbers for items skipped during the job.")
    parser.add_argument("--consec", action="store_true",
        help="Print the range of item item numbers consecutively attempted (useful for restarting aborted jobs)")
    parser.add_argument("logfile", metavar="COOKLOG",
        help="Path to a single cooklog, in JSON format, from clams-kitchen")

    args = parser.parse_args()

    logfile_path = args.logfile
    if logfile_path is None:
        print("No logfile specified.")
        print("Run with '-h' for help.")
        raise SystemExit
    
    with open(logfile_path, "r") as logfile:
        try:
            tried_l = json.load(logfile)
        except json.JSONDecodeError as e:
            print(f"JSON parsing error: {str(e)}")
            print()
            raise SystemExit from e

    if args.simple:
        print_simple_summary(tried_l)
    else:
        print_summary(tried_l)
    
    if args.infos:
        print_infos(tried_l)

    if args.list_skipped:
        print_skipped_list(tried_l)

    if args.consec:
        print_consec(tried_l)

if __name__ == "__main__":
    main()
