
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
    print("Batch contained", len(tried_l), "items.")
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


def print_infos(tried_l):

    infos = [item for item in tried_l if len(item["infos"]) > 0 ] 
    print(len(infos), "out of", len(tried_l), "items had info.")

    if len(infos) > 0:
        print()
        print("Items with info:")
        for item in infos:
            print(f" #{item['item_num']}:\t{item['asset_id']}\tInfo: {item['infos']}")


def print_timing(tried_l):

    if "time_began" not in tried_l[0]:
        # no timing info in runlog
        pass
    else:
        began = datetime.datetime.fromisoformat(tried_l[0]["time_began"])
        ended = datetime.datetime.fromisoformat(tried_l[-1]["time_ended"])

        days = (ended-began).days
        seconds = (ended-began).seconds

        print(f'First item began: {began.strftime("%Y-%m-%d %H:%M:%S")}')
        print(f'Final item ended: {ended.strftime("%Y-%m-%d %H:%M:%S")}  ({days} days, {seconds} seconds later)')


def main():
    
    parser = parser = argparse.ArgumentParser(
        prog='runlog_summarizer.py',
        description='Creates a user-friendly summary from clams-kitchen runlog',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument("-s", "--simple", action="store_true",
        help="Print just a simple summary, not the full summary")
    parser.add_argument("-i", "--infos", action="store_true",
        help="Print infos about any items that have it.")
    parser.add_argument("logfile", metavar="LOG",
        help="Path to a single runlog (in JSON format)")

    # parser.add_argument("-d", "--jobdir", metavar="DIR", nargs="?",
    #     help="Path to directory containing runlogs")

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


if __name__ == "__main__":
    main()
