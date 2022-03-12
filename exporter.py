#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from argparse import RawDescriptionHelpFormatter
from typing import List

import requests
import json
from datetime import datetime
import argparse
from dotenv import load_dotenv

from requests import Response

from logger import Logger
from request_series_printer import RequestSeriesPrinter
from adaptive_request_manager import AdaptiveRequestManager
from io_common import fmt_sizeof

env_file = os.path.join(os.path.dirname(__file__), ".env")
if os.path.isfile(env_file):
    load_dotenv(env_file)

# use this to say anything
# will print to stdout if no response_url is given
# or post_response to given url if provided
logger = None
def handle_print(text, response_url=None):
    if response_url is None:
        print(text)
        if logger:
            logger.log_line(text)
    else:
        send_post_request(response_url, text)


# slack api (OAuth 2.0) now requires auth tokens in HTTP Authorization header
# instead of passing it as a query parameter
try:
    HEADERS = {"Authorization": "Bearer %s" % os.environ["SLACK_USER_TOKEN"]}
except KeyError:
    handle_print("Missing SLACK_USER_TOKEN in environment variables")
    sys.exit(1)


def send_get_request(url, params):
    return requests.get(url, headers=HEADERS, params=params, timeout=(10, 30), )


def send_post_request(url, text):
    requests.post(url, json={"text": text})


def perform_request_with_retries(url, params) -> Response:
    """Naively deals with rate-limiting"""

    success = False
    attempt_num = 0

    while not success:
        attempt_num += 1
        request_series_printer.before_request_attempt(attempt_num)
        try:
            r: Response = send_get_request(url, params)
        except Exception as e:
            adaptive_request_manager.on_transport_error(attempt_num, str(e))
            handle_print("ERROR: Attempt {:d} failed. {:s}".format(attempt_num, str(e)))
            continue

        adaptive_request_manager.on_request_completion(r)
        if not r.ok:
            if r.status_code == 429:
                retry_after_sec = float(r.headers["Retry-After"])
                adaptive_request_manager.on_rate_limited_request_fail(retry_after_sec)
                continue

            if attempt_num >= AdaptiveRequestManager.RETRY_MAX_NUM:
                handle_print("ERROR: Max retry amount exceeded")
                sys.exit(1)
            continue

        return r


def fetch_at_cursor(url, params, cursor=None, response_url=None):
    if cursor is not None:
        params["cursor"] = cursor

    r = perform_request_with_retries(url, params)
    d = r.json()

    try:
        if d["ok"] is False:
            handle_print("API error encountered: %s" % d, response_url)
            sys.exit(1)

        next_cursor = None
        if "response_metadata" in d and "next_cursor" in d["response_metadata"]:
            next_cursor = d["response_metadata"]["next_cursor"]
            if str(next_cursor).strip() == "":
                next_cursor = None

        return next_cursor, d

    except KeyError as e:
        handle_print("Something went wrong: %s." % e, response_url)
        return None, []


def fetch_paginated(url, params, combine_key=None, response_url=None):
    next_cursor = None
    result = []
    while True:
        request_series_printer.before_request(params)
        next_cursor, data = fetch_at_cursor(
            url, params, cursor=next_cursor, response_url=response_url
        )

        try:
            result.extend(data) if combine_key is None else result.extend(
                data[combine_key]
            )
        except KeyError as e:
            handle_print("Something went wrong: %s." % e, response_url)
            sys.exit(1)

        if next_cursor is None:
            break
    return result


# GET requests


def fetch_channel_list(team_id=None, response_url=None):
    channels_path = a.o + "/channels.json"
    if os.path.exists(channels_path) is True:  # @FIXME load_from_cache() ?
        with open(channels_path, mode="r") as f:
            cached = json.load(f)
            handle_print(f'Channel list loaded from cache: {len(cached):d} channels')
            return cached

    handle_print('Channel list fetch starts')
    api_url = "https://slack.com/api/conversations.list",
    params = {
        # "token": os.environ["SLACK_USER_TOKEN"],
        "team_id": team_id,
        "types": ','.join([
            'public_channel',
            'private_channel',
            'im'  # direct messages. make optional?
        ]),
        "limit": 1000,
        "exclude_archived": True
    }

    adaptive_request_manager.reinit()
    request_series_printer.reinit()
    request_series_printer.before_paginated_batch(api_url)
    channels_list = fetch_paginated(
        api_url,
        params,
        combine_key="channels",
        response_url=response_url
    )
    request_series_printer.after_paginated_batch()
    handle_print(f'Channel list fetch successful: {len(channels_list):d} channels')
    save(channels_list, "channels")

    return channels_list


def fetch_channel_history(channel_id, response_url=None, oldest=None, latest=None):
    handle_print(f'Channel history fetch starts ({channel_id})')
    params = {
        # "token": os.environ["SLACK_USER_TOKEN"],
        "channel": channel_id,
        "limit": 1000,
    }
    api_url = "https://slack.com/api/conversations.history"

    if oldest is not None:
        params["oldest"] = oldest
    if latest is not None:
        params["latest"] = latest

    adaptive_request_manager.reinit()
    request_series_printer.reinit()
    request_series_printer.before_paginated_batch(api_url)
    result_list = fetch_paginated(
        api_url,
        params,
        combine_key="messages",
        response_url=response_url,
    )
    request_series_printer.after_paginated_batch()
    handle_print(f'Channel history fetch successful ({channel_id}): {len(result_list):d} results')
    return result_list


# @TODO reads from users.json, writes to users.json and user_list.json. bug? wut
def fetch_user_list(team_id=None, response_url=None):
    users_path = a.o + "/users.json"
    if os.path.exists(users_path) is True:  # @FIXME load_from_cache() ?
        with open(users_path, mode="r") as f:
            cached = json.load(f)
            handle_print(f'User list loaded from cache: {len(cached):d} users')
            return cached

    handle_print('User list fetch begins')
    api_url = "https://slack.com/api/users.list",
    params = {
        # "token": os.environ["SLACK_USER_TOKEN"],
        "limit": 1000,
        "team_id": team_id,
    }
    request_series_printer.reinit()
    adaptive_request_manager.reinit()
    request_series_printer.before_paginated_batch(api_url)
    users = fetch_paginated(
        api_url,
        params,
        combine_key="members",
        response_url=response_url,
    )
    request_series_printer.after_paginated_batch()

    handle_print(f'User list fetch successful: {len(users):d} users')
    save(users, "users")

    return users


def fetch_channel_replies(timestamps, channel_id, response_url=None):
    requests_estimated = len(timestamps)
    if requests_estimated == 0:
        handle_print(f'No timestamps - no replies. Skipping ({channel_id})')
        return []

    handle_print(f'Channel replies fetch starts ({channel_id})')
    handle_print(f'Request amount (estimated): {requests_estimated:d}')
    request_series_printer.reinit(requests_estimated)
    adaptive_request_manager.reinit()

    replies = []
    api_url = "https://slack.com/api/conversations.replies"

    request_series_printer.before_paginated_batch(api_url)
    for timestamp in timestamps:
        params = {
            # "token": os.environ["SLACK_USER_TOKEN"],
            "channel": channel_id,
            "ts": timestamp,
            "limit": 1000,
        }
        result = fetch_paginated(
            api_url,
            params,
            combine_key="messages",
            response_url=response_url,
        )
        replies.append(result)

    request_series_printer.after_paginated_batch()
    handle_print(f'Channel replies fetch successful ({channel_id}): {len(replies):d} results')
    return replies


# parsing


def parse_channel_list(channels, users):
    result = ""
    for channel in channels:
        ch_id = channel["id"]
        ch_name = channel["name"] if "name" in channel else ""
        ch_private = (
            "private " if "is_private" in channel and channel["is_private"] else ""
        )
        if "is_im" in channel and channel["is_im"]:
            ch_type = "direct_message"
        elif "is_mpim" in channel and channel["is_mpim"]:
            ch_type = "multiparty-direct_message"
        elif "group" in channel and channel["is_group"]:
            ch_type = "group"
        else:
            ch_type = "channel"
        if "creator" in channel:
            ch_ownership = "created by %s" % name_from_uid(channel["creator"], users)
        elif "user" in channel:
            ch_ownership = "with %s" % name_from_uid(channel["user"], users)
        else:
            ch_ownership = ""
        ch_name = " %s:" % ch_name if ch_name.strip() != "" else ch_name
        result += "[%s]%s %s%s %s\n" % (
            ch_id,
            ch_name,
            ch_private,
            ch_type,
            ch_ownership,
        )

    return result


def name_from_uid(user_id, users, real=False):
    for user in users:
        if user["id"] != user_id:
            continue

        if real:
            try:
                return user["profile"]["real_name"]
            except KeyError:
                try:
                    return user["profile"]["display_name"]
                except KeyError:
                    return "[no full name]"
        else:
            return user["name"]

    return "[null user]"


def name_from_ch_id(channel_id, channels):
    for channel in channels:
        if channel["id"] == channel_id:
            return (
                (channel["user"], "Direct Message")
                if "user" in channel
                else (channel["name"], "Channel")
            )
    return "[null channel]"


def parse_user_list(users):
    result = ""
    for u in users:
        entry = "[%s]" % u["id"]

        try:
            entry += " %s" % u["name"]
        except KeyError:
            pass

        try:
            entry += " (%s)" % u["profile"]["real_name"]
        except KeyError:
            pass

        try:
            entry += ", %s" % u["tz"]
        except KeyError:
            pass

        u_type = ""
        if "is_admin" in u and u["is_admin"]:
            u_type += "admin|"
        if "is_owner" in u and u["is_owner"]:
            u_type += "owner|"
        if "is_primary_owner" in u and u["is_primary_owner"]:
            u_type += "primary_owner|"
        if "is_restricted" in u and u["is_restricted"]:
            u_type += "restricted|"
        if "is_ultra_restricted" in u and u["is_ultra_restricted"]:
            u_type += "ultra_restricted|"
        if "is_bot" in u and u["is_bot"]:
            u_type += "bot|"
        if "is_app_user" in u and u["is_app_user"]:
            u_type += "app_user|"

        if u_type.endswith("|"):
            u_type = u_type[:-1]

        entry += ", " if u_type.strip() != "" else ""
        entry += "%s\n" % u_type
        result += entry

    return result


def parse_channel_history(msgs, users, check_thread=False):
    if "messages" in msgs:
        msgs = msgs["messages"]

    messages = [x for x in msgs if x["type"] == "message"]  # files are also messages
    body = ""
    for msg in messages:
        if "user" in msg:
            usr = {
                "name": name_from_uid(msg["user"], users),
                "real_name": name_from_uid(msg["user"], users, real=True),
            }
        else:
            usr = {"name": "", "real_name": "none"}

        timestamp = datetime.fromtimestamp(round(float(msg["ts"]))).strftime(
            "%m-%d-%y %H:%M:%S"
        )
        text = msg["text"] if msg["text"].strip() != "" else "[no message content]"
        for u in [x["id"] for x in users]:  # it takes BILLIONS to iterate user list with 50k users. refactoring required
            text = str(text).replace(
                "<@%s>" % u, "<@%s> (%s)" % (u, name_from_uid(u, users))
            )

        entry = "Message at %s\nUser: %s (%s)\n%s" % (
            timestamp,
            usr["name"],
            usr["real_name"],
            text,
        )
        if "reactions" in msg:
            rxns = msg["reactions"]
            entry += "\nReactions: " + ", ".join(
                "%s (%s)"
                % (x["name"], ", ".join(name_from_uid(u, users) for u in x["users"]))
                for x in rxns
            )
        if "files" in msg:
            files = msg["files"]
            deleted = [
                f for f in files if "name" not in f or "url_private_download" not in f
            ]
            ok_files = [f for f in files if f not in deleted]
            entry += "\nFiles:\n"
            entry += "\n".join(
                " - [%s] %s, %s" % (f["id"], f["name"], f["url_private_download"])
                for f in ok_files
            )
            entry += "\n".join(
                " - [%s] [deleted, oversize, or unavailable file]" % f["id"]
                for f in deleted
            )

        entry += "\n\n%s\n\n" % ("*" * 24)

        if check_thread and "parent_user_id" in msg:
            entry = "\n".join("\t%s" % x for x in entry.split("\n"))

        body += entry.rstrip(
            "\t"
        )  # get rid of any extra tabs between trailing newlines

    return body


def parse_replies(threads, users):
    body = ""
    for thread in threads:
        body += parse_channel_history(thread, users, check_thread=True)
        body += "\n"

    return body


def ch_name_from_id(ch_id, ch_list):
    # return ch_map_id.get(ch_id)['name']
    for channel in ch_list:
        if channel['id'] == ch_id:
            return channel['name']


def id_from_ch_name(channel_name, channel_list):
    for channel in channel_list:
        if channel.get('name', None) == channel_name:
            return channel['id']


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        formatter_class=RawDescriptionHelpFormatter,
        epilog='\n'.join([
            "RATE LIMIT COMPENSAION",
            'This program considers rate limiting and by default dynamically adjusts post-request delay to minimize limit errors and work with reasonable speed at the same time. When <MAX_RPM> is not set, delay will slowly decrease after some amount of succeessful requests in a row and increase after failed requests. When <MAX_RPS> is set, adjuster works almost the same, except that it will try to keep request ratio not bigger than option.\n\nOption -A disables dynamic compensation completely - program just waits a few seconds and then retry. Delay duration is read from "Retry-After" header (if it is provided by web-server) - this algorithm is independent from dynamic compensation and works always).'
        ])
    )
    parser.add_argument(
        "-o",
        help="Directory in which to save output files (if set empty, prints to stdout)",
        default=".slack-backup",
        action="store", type=str
    )
    parser.add_argument(
        "--lc", action="store_true", help="List all conversations in your workspace"
    )
    parser.add_argument(
        "--lu", action="store_true", help="List all users in your workspace"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Give the requested output in raw JSON format (no parsing)",
        default=True
    )
    parser.add_argument(
        "-c", action="store_true", help="Get history for all accessible conversations (filters available, see below)"
    )
    parser.add_argument(
        "--ch",
        metavar='<NAME>|<FILE>.json',
        help="With -c, restrict export to given channel name (e.g. \"general\", not abbrev). Also can be a filename which stores json-encoded array of channel names."
    )
    parser.add_argument(
        "--fr",
        help="With -c, Unix timestamp (seconds since Jan. 1, 1970) for earliest message",
        type=str,
    )
    parser.add_argument(
        "--to",
        help="With -c, Unix timestamp (seconds since Jan. 1, 1970) for latest message",
        type=str,
    )
    parser.add_argument(
        "-r",
        action="store_true",
        help="Get reply threads for all accessible conversations. Implies -c, but conversation history data is not writed to files at the end. Using them together (-cr) will save a lot of time if you want both history and replies",
    )
    arm_group = parser.add_mutually_exclusive_group()
    arm_group.add_argument(
        "-x",
        metavar='<MAX_RPM>',
        action="store",
        type=float,
        help="Set max requests per minute; request delays will be dynamically adjusted to keep real RPM as close as possible to it (default = 0, auto) (see below)."
    )
    arm_group.add_argument(
        "-A",
        action="store_true",
        help="Disable adaptive rate limit compensation mechanism (see below)."
    )

    a = parser.parse_args()
    ts = str(datetime.strftime(datetime.now(), "%m-%d-%Y_%H%M%S"))
    sep_str = "*" * 24

    logger = Logger.get_instance()
    request_series_printer = RequestSeriesPrinter.get_instance()
    adaptive_request_manager = AdaptiveRequestManager.get_instance()
    adaptive_request_manager.apply_app_args(a)

    def get_output_dir_path():
        return os.path.abspath(
            os.path.expanduser(os.path.expandvars(a.o))
        )


    def save(data, filename):
        if a.o is None:
            json.dump(print(data), sys.stdout, indent=4)
        else:
            out_dir = get_output_dir_path()
            filename = filename + ".json" if a.json else filename + ".txt"
            full_filepath = os.path.join(out_dir, filename)
            os.makedirs(os.path.dirname(full_filepath), exist_ok=True)
            print("Writing output to %s... " % full_filepath, end='', flush=True)
            # @TODO it takes a lot of time to encode 50-mb json and app is
            # unrepsonsive all that time. asynchronus I/O can solve the problem
            # and also it can provide real-time work progress
            if a.json:
                data = json.dumps(data, indent=4, ensure_ascii=False)
            with open(full_filepath, mode="w", encoding="utf-8") as f:
                f.write(data)
            print(f"Done ({fmt_sizeof(len(data)).strip()})")

    def load_from_cache(filename) -> List|None:
        # if file is found: read it and return list
        # if file is not found: return None
        full_filepath = os.path.join(get_output_dir_path(), filename + ".json")
        if os.path.exists(full_filepath):
            with open(full_filepath, mode="r", encoding="utf-8") as f:
                return json.load(f)
        else:
            print(f"Cache miss: {filename}")
            return None

    def get_channel_replies_save_path(ch_id, ch_list):
        return "%s--replies" % get_channel_save_path(ch_id, ch_list)

    def save_channel_replies(channel_hist, channel_id, channel_list, users):
        replies_save_path = get_channel_replies_save_path(ch_id, ch_list)

        if load_from_cache(replies_save_path) is not None:  # can be empty list
            print(f"Channel replies found in cache, skipping: {replies_save_path}")
            return

        reply_timestamps = [x["ts"] for x in channel_hist if "reply_count" in x]
        ch_replies = fetch_channel_replies(reply_timestamps, channel_id)
        ch_name, ch_type = name_from_ch_id(channel_id, channel_list)
        if a.json:
            data_replies = ch_replies
        else:
            header_str = "Threads in %s: %s\n%s Messages" % (
                ch_type,
                ch_name,
                len(ch_replies),
            )
            data_replies = parse_replies(ch_replies, users)
            data_replies = "%s\n%s\n\n%s" % (header_str, sep_str, data_replies)
        save(data_replies, replies_save_path)

    def get_channel_save_path(ch_id, ch_list):
        ch_name, ch_type = name_from_ch_id(ch_id, ch_list)
        return "%s/%s" % (ch_name, ch_name)

    def save_channel_history(channel_hist, channel_id, channel_list, users):
        channel_save_path = get_channel_save_path(channel_id, channel_list)
        if load_from_cache(channel_save_path) is None:
            ch_name, ch_type = name_from_ch_id(channel_id, channel_list)
            if a.json:
                data_ch = channel_hist
            else:
                data_ch = parse_channel_history(channel_hist, users)
                header_str = "%s Name: %s" % (ch_type, ch_name)
                data_ch = (
                        "Channel ID: %s\n%s\n%s Messages\n%s\n\n"
                        % (channel_id, header_str, len(channel_hist), sep_str)
                        + data_ch
                )
            save(data_ch, channel_save_path)
        else:
            print(f"Channel history found in cache, skipping: {channel_save_path}")

        if a.r:
            save_channel_replies(channel_hist, channel_id, channel_list, users)

    ch_list = fetch_channel_list()
    ch_map_id = {v.get('id'): v for v in ch_list}  # @TODO optimize find-by-id methods

    if a.lc:
        user_list = fetch_user_list()
        data = ch_list if a.json else parse_channel_list(ch_list, user_list)
        save(data, "channel_list")
    if a.lu:
        user_list = fetch_user_list()
        data = user_list if a.json else parse_user_list(user_list)
        save(data, "user_list")
    if a.c:
        user_list = fetch_user_list()
        ch = a.ch
        if ch:
            ch_names = [ch]
            if ch.endswith('.json'):
                with open(ch, mode="r") as f:
                    ch_names = json.load(f)
            else:
                ch_names = ch.split(',')
            ch_names = [ch.lstrip('#') for ch in ch_names]
            for ch_name in ch_names:
                ch_id = id_from_ch_name(ch_name, ch_list)
                # what if it WAS an id from the beginning?
                if not ch_id:
                    if ch_name in ch_map_id.keys():
                        ch_id = ch_name
                if ch_id:
                    ch_save_path = get_channel_save_path(ch_id, ch_list)
                    ch_hist = load_from_cache(ch_save_path)
                    if ch_hist is None:
                        ch_hist = fetch_channel_history(ch_id, oldest=a.fr, latest=a.to)
                    save_channel_history(ch_hist, ch_id, ch_list, user_list)
                else:
                    handle_print(f"Channel ID not found for name '{ch_name}', skipping")
        else:
            for ch_id in [x["id"] for x in ch_list]:
                ch_hist = fetch_channel_history(ch_id, oldest=a.fr, latest=a.to)
                save_channel_history(ch_hist, ch_id, ch_list, user_list)
    # elif, since we want to avoid asking for channel_history twice
    elif a.r:
        user_list = fetch_user_list()
        for ch_id in [x["id"] for x in fetch_channel_list()]:
            ch_hist = fetch_channel_history(ch_id, oldest=a.fr, latest=a.to)
            save_channel_replies(ch_hist, ch_id, ch_list, user_list)
