#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# slack message history exporting tool
# 2022 A. Shavykin <0.delameter@gmail.com>
# -----------------------------------------------------------------------------
# based on https://github.com/sebseager/slack-exporter
# -----------------------------------------------------------------------------
from __future__ import annotations

import argparse
import json
import os
import sys
from argparse import RawDescriptionHelpFormatter, Namespace
from datetime import datetime
from typing import List, Tuple

import requests
from dotenv import load_dotenv
from requests import Response

from pyslacker.core.adaptive_request_manager import AdaptiveRequestManager
from pyslacker.core.exception_handler import ExceptionHandler
from pyslacker.core.logger import Logger
from pyslacker.util.io import fmt_sizeof


# noinspection PyMethodMayBeStatic
class HistoryDumper:
    @staticmethod
    def send_post_request(url, text):
        requests.post(url, json={"text": text})

    @staticmethod
    def send_get_request(url, params) -> Tuple[Response, int]:
        response = requests.get(url, headers=HistoryDumper.HEADERS, params=params, timeout=(10, 30))
        return response, len(response.content)

    @staticmethod
    def fetch_at_cursor(url, params, cursor=None):
        if cursor is not None:
            params["cursor"] = cursor

        try:
            response = HistoryDumper.adaptive_request_manager.perform_retriable_request(
                lambda attempt_num: HistoryDumper.send_get_request(url, params),
            )
        except RuntimeError as e:
            HistoryDumper.logger.error(str(e))
            sys.exit(1)

        d = response.json()
        try:
            if d['ok'] is False:
                HistoryDumper.logger.error(f'API error encountered: {d!s}' % d)
                sys.exit(1)

            next_cursor = None
            if "response_metadata" in d and "next_cursor" in d["response_metadata"]:
                next_cursor = d["response_metadata"]["next_cursor"]
                if str(next_cursor).strip() == "":
                    next_cursor = None

            return next_cursor, d

        except KeyError as e:
            HistoryDumper.logger.error(f'Response processing error: {e!s}')
            return None, []

    @staticmethod
    def fetch_paginated(url, params, combine_key=None):
        next_cursor = None
        result = []
        while True:
            next_cursor, data = HistoryDumper.fetch_at_cursor(
                url, params, cursor=next_cursor,
            )

            try:
                result.extend(data) if combine_key is None else result.extend(
                    data[combine_key]
                )
            except KeyError as e:
                HistoryDumper.logger.error(f'Response processing error: {e!s}')
                sys.exit(1)

            if next_cursor is None:
                break
        return result

    @staticmethod
    def fetch_channel_list(team_id=None):
        channels_path = HistoryDumper.a.o + "/channels.json"
        if os.path.exists(channels_path) is True:  # @FIXME load_from_cache() ?
            with open(channels_path, mode="r") as f:
                cached = json.load(f)
                HistoryDumper.logger.info(f'Channel list loaded from cache: {len(cached):d} channels')
                return cached

        HistoryDumper.logger.info('Channel list fetching starts...')
        api_url = "https://slack.com/api/conversations.list"
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

        HistoryDumper.adaptive_request_manager.reinit()
        HistoryDumper.adaptive_request_manager.before_paginated_batch(api_url)
        channels_list = HistoryDumper.fetch_paginated(
            api_url,
            params,
            combine_key="channels",
        )
        HistoryDumper.adaptive_request_manager.after_paginated_batch()
        HistoryDumper.logger.info(f'Channel list fetch successful: {len(channels_list):d} channels')
        HistoryDumper.save(channels_list, "channels", 'json')

        return channels_list

    @staticmethod
    def fetch_channel_history(channel_id, oldest=None, latest=None):
        HistoryDumper.logger.info(f'Channel history fetching starts ({channel_id})...')
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

        HistoryDumper.adaptive_request_manager.reinit()
        HistoryDumper.adaptive_request_manager.before_paginated_batch(api_url)
        result_list = HistoryDumper.fetch_paginated(
            api_url,
            params,
            combine_key="messages",
        )
        HistoryDumper.adaptive_request_manager.after_paginated_batch()
        HistoryDumper.logger.info(f'Channel history fetch successful ({channel_id}): {len(result_list):d} results')
        return result_list

    # @TODO reads from users.json, writes to users.json and user_list.json. bug? wut
    @staticmethod
    def fetch_user_list(team_id=None):
        users_path = HistoryDumper.a.o + "/users.json"
        if os.path.exists(users_path) is True:  # @FIXME load_from_cache() ?
            with open(users_path, mode="r") as f:
                cached = json.load(f)
                HistoryDumper.logger.info(f'User list loaded from cache: {len(cached):d} users')
                return cached

        HistoryDumper.logger.info('User list fetching starts...')
        api_url = "https://slack.com/api/users.list"
        params = {
            # "token": os.environ["SLACK_USER_TOKEN"],
            "limit": 1000,
            "team_id": team_id,
        }

        HistoryDumper.adaptive_request_manager.reinit()
        HistoryDumper.adaptive_request_manager.before_paginated_batch(api_url)
        users = HistoryDumper.fetch_paginated(
            api_url,
            params,
            combine_key="members",
        )
        HistoryDumper.adaptive_request_manager.after_paginated_batch()

        HistoryDumper.logger.info(f'User list fetch successful: {len(users):d} users')
        HistoryDumper.save(users, "users", 'json')

        return users

    @staticmethod
    def fetch_channel_replies(timestamps, channel_id):
        requests_estimated = len(timestamps)
        if requests_estimated == 0:
            HistoryDumper.logger.info(f'No timestamps - no replies. Skipping ({channel_id})')
            return []

        replies = []
        api_url = "https://slack.com/api/conversations.replies"
        HistoryDumper.logger.info(f'Channel replies fetching starts ({channel_id})...')
        HistoryDumper.logger.info(f'Request amount (estimated): {requests_estimated:d}')

        HistoryDumper.adaptive_request_manager.reinit(requests_estimated)
        HistoryDumper.adaptive_request_manager.before_paginated_batch(api_url)
        for timestamp in timestamps:
            params = {
                # "token": os.environ["SLACK_USER_TOKEN"],
                "channel": channel_id,
                "ts": timestamp,
                "limit": 1000,
            }
            result = HistoryDumper.fetch_paginated(
                api_url,
                params,
                combine_key="messages",
            )
            replies.append(result)

        HistoryDumper.adaptive_request_manager.after_paginated_batch()
        HistoryDumper.logger.info(f'Channel replies fetch successful ({channel_id}): {len(replies):d} results')
        return replies

    @staticmethod
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
                ch_ownership = "created by %s" % HistoryDumper.name_from_uid(channel["creator"], users)
            elif "user" in channel:
                ch_ownership = "with %s" % HistoryDumper.name_from_uid(channel["user"], users)
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

    @staticmethod
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

    @staticmethod
    def name_from_ch_id(channel_id, channels):
        for channel in channels:
            if channel["id"] == channel_id:
                return (
                    (channel["user"], "Direct Message")
                    if "user" in channel
                    else (channel["name"], "Channel")
                )
        return "[null channel]"

    @staticmethod
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

    @staticmethod
    def parse_channel_history(msgs, users, check_thread=False):
        if "messages" in msgs:
            msgs = msgs["messages"]

        messages = [x for x in msgs if x["type"] == "message"]  # files are also messages
        body = ""
        for msg in messages:
            if "user" in msg:
                usr = {
                    "name": HistoryDumper.name_from_uid(msg["user"], users),
                    "real_name": HistoryDumper.name_from_uid(msg["user"], users, real=True),
                }
            else:
                usr = {"name": "", "real_name": "none"}

            timestamp = datetime.fromtimestamp(round(float(msg["ts"]))).strftime(
                "%m-%d-%y %H:%M:%S"
            )
            text = msg["text"] if msg["text"].strip() != "" else "[no message content]"
            for u in [x["id"] for x in users]:  # it takes BILLIONS to iterate user list with 50k users. refactoring required
                text = str(text).replace(
                    "<@%s>" % u, "<@%s> (%s)" % (u, HistoryDumper.name_from_uid(u, users))
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
                    % (x["name"], ", ".join(HistoryDumper.name_from_uid(u, users) for u in x["users"]))
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

    @staticmethod
    def parse_replies(threads, users):
        body = ""
        for thread in threads:
            body += HistoryDumper.parse_channel_history(thread, users, check_thread=True)
            body += "\n"

        return body

    @staticmethod
    def ch_name_from_id(ch_id, ch_list):
        # return ch_map_id.get(ch_id)['name']
        for channel in ch_list:
            if channel['id'] == ch_id:
                return channel['name']

    @staticmethod
    def id_from_ch_name(channel_name, channel_list):
        for channel in channel_list:
            if channel.get('name', None) == channel_name:
                return channel['id']

    logger: Logger = Logger.get_instance(require_new=True)
    adaptive_request_manager: AdaptiveRequestManager = AdaptiveRequestManager.get_instance()

    a: Namespace
    ch_list: List
    ts: str
    sep_str: str

    def __init__(self):
        env_file = os.path.join(os.getcwd(), ".env")
        if os.path.isfile(env_file):
            load_dotenv(env_file)

    def run(self):
        _hanlder = ExceptionHandler()
        try:
            self._invoke()
        except Exception as e:
            _hanlder.handle(e)
        print()

    def _invoke(self):
        try:
            HistoryDumper.HEADERS = {"Authorization": "Bearer %s" % os.environ["SLACK_USER_TOKEN"]}
        except KeyError:
            raise RuntimeError('Missing SLACK_USER_TOKEN in environment variables')
        HistoryDumper.a = HistoryDumper.parse_args()

        HistoryDumper.ts = str(datetime.strftime(datetime.now(), "%m-%d-%Y_%H%M%S"))
        HistoryDumper.sep_str = "*" * 24

        HistoryDumper.adaptive_request_manager.apply_app_args(HistoryDumper.a)

        # ----------------------------------------------------------------------

        HistoryDumper.ch_list = HistoryDumper.fetch_channel_list()
        ch_map_id = {v.get('id'): v for v in HistoryDumper.ch_list}  # @TODO optimize find-by-id methods

        user_list = HistoryDumper.fetch_user_list()

        if HistoryDumper.a.pc:
            data = HistoryDumper.parse_channel_list(HistoryDumper.ch_list, user_list)
            HistoryDumper.save(data, "channels_parsed", 'txt')
        if HistoryDumper.a.pu:
            data = HistoryDumper.parse_user_list(user_list)
            HistoryDumper.save(data, "users_parsed", 'txt')
        if HistoryDumper.a.c:
            ch = HistoryDumper.a.ch
            if ch:
                if ch.endswith('.json'):
                    with open(ch, mode="r") as f:
                        ch_names = json.load(f)
                else:
                    ch_names = ch.split(',')
                ch_names = [ch.lstrip('#') for ch in ch_names]
                for ch_name in ch_names:
                    HistoryDumper.ch_id = HistoryDumper.id_from_ch_name(ch_name, HistoryDumper.ch_list)
                    # what if it WAS an id from the beginning?
                    if not HistoryDumper.ch_id:
                        if ch_name in ch_map_id.keys():
                            HistoryDumper.ch_id = ch_name
                    if HistoryDumper.ch_id:
                        ch_save_path = HistoryDumper.get_channel_save_path(HistoryDumper.ch_id, HistoryDumper.ch_list)
                        ch_hist = HistoryDumper.load_from_cache(ch_save_path)
                        if ch_hist is None:
                            ch_hist = HistoryDumper.fetch_channel_history(HistoryDumper.ch_id, oldest=HistoryDumper.a.fr, latest=HistoryDumper.a.to)
                        HistoryDumper.save_channel_history(ch_hist, HistoryDumper.ch_id, HistoryDumper.ch_list, user_list)
                    else:
                        HistoryDumper.logger.warn(f"Channel ID not found for name '{ch_name}', skipping")
            else:
                for ch_id in [x["id"] for x in HistoryDumper.ch_list]:
                    ch_hist = HistoryDumper.fetch_channel_history(ch_id, oldest=HistoryDumper.a.fr, latest=HistoryDumper.a.to)
                    HistoryDumper.save_channel_history(ch_hist, ch_id, HistoryDumper.ch_list, user_list)
        # elif, since we want to avoid asking for channel_history twice
        elif HistoryDumper.a.r:
            for ch_id in [x["id"] for x in HistoryDumper.fetch_channel_list()]:
                ch_hist = HistoryDumper.fetch_channel_history(ch_id, oldest=HistoryDumper.a.fr, latest=HistoryDumper.a.to)
                HistoryDumper.save_channel_replies(ch_hist, ch_id, HistoryDumper.ch_list, user_list)

    @staticmethod
    def parse_args():
        parser = argparse.ArgumentParser(
            formatter_class=RawDescriptionHelpFormatter,
            epilog='\n'.join([
                "RATE LIMIT COMPENSAION",
                'This program considers rate limiting and by default dynamically adjusts post-request delay to minimize limit errors and work with reasonable speed at the same time. Delay will slowly decrease after some amount of succeessful requests in a row and increase after failed requests. Minimum (which equals initial) delay can be set with -n. Option -A disables dynamic compensation - program just waits a few seconds and then retry. Delay duration is read from "Retry-After" header (if it is provided by web-server) - this algorithm is independent from dynamic compensation and works always).'
            ])
        )
        parser.add_argument(
            "-o",
            help="Directory in which to save output files (default '.slack-backup')",
            default=".slack-backup",
            action="store", type=str
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
        parser.add_argument(
            "--pc", action="store_true", help="Parse channel list and save it in human-readable format alongwith json"
        )
        parser.add_argument(
            "--pu", action="store_true", help="Parse user list and save it in human-readable format alongwith json"
        )
        arm_group = parser.add_mutually_exclusive_group()
        arm_group.add_argument(
            "-n",
            metavar='<MIN_DELAY>',
            action="store",
            type=float,
            help="Set minimum delay beetween requests (default 0, no delay)."
        )
        arm_group.add_argument(
            "-A",
            action="store_true",
            help="Disable adaptive rate limit compensation mechanism (see below)."
        )
        arm_group.add_argument(
            "-v", '--verbose',
            action="store_true",
            help="Provde detailed output."
        )
        return parser.parse_args()

    @staticmethod
    def get_output_dir_path():
        return os.path.abspath(
            os.path.expanduser(os.path.expandvars(HistoryDumper.a.o))
        )

    @staticmethod
    def save(data, filename, fileformat):
        out_dir = HistoryDumper.get_output_dir_path()
        full_filepath = os.path.join(out_dir, filename + '.' + fileformat)

        os.makedirs(os.path.dirname(full_filepath), exist_ok=True)

        HistoryDumper.logger.info(f'Writing to {full_filepath}... ')
        if fileformat == 'json':
            data = json.dumps(data, indent=4, ensure_ascii=False)
        with open(full_filepath, mode="w", encoding="utf-8") as f:
            f.write(data)
        HistoryDumper.logger.info(f'Writing done ({fmt_sizeof(len(data)).strip()})')

    @staticmethod
    def load_from_cache(filename) -> List|None:
        # if file is found: read it and return list
        # if file is not found: return None
        full_filepath = os.path.join(HistoryDumper.get_output_dir_path(), filename + ".json")
        if os.path.exists(full_filepath):
            with open(full_filepath, mode="r", encoding="utf-8") as f:
                return json.load(f)
        else:
            HistoryDumper.logger.debug(f"Cache miss: {filename}")
            return None

    @staticmethod
    def get_channel_replies_save_path(ch_id, ch_list):
        return "%s--replies" % HistoryDumper.get_channel_save_path(ch_id, ch_list)

    @staticmethod
    def save_channel_replies(channel_hist, channel_id, channel_list, users):
        replies_save_path = HistoryDumper.get_channel_replies_save_path(channel_id, channel_list)

        if HistoryDumper.load_from_cache(replies_save_path) is not None:  # can be empty list
            HistoryDumper.logger.info(f"Found in cache, skipping: {replies_save_path}")
            return

        reply_timestamps = [x["ts"] for x in channel_hist if "reply_count" in x]
        ch_replies = HistoryDumper.fetch_channel_replies(reply_timestamps, channel_id)
        ch_name, ch_type = HistoryDumper.name_from_ch_id(channel_id, channel_list)

        HistoryDumper.save(ch_replies, replies_save_path, 'json')
        # @TODO TERRIBLY SLOW, refactoring required
        #if HistoryDumper.a.p:
        #    header_str = "Threads in %s: %s\n%s Messages" % (
        #        ch_type,
        #        ch_name,
        #        len(ch_replies),
        #    )
        #    data_replies = HistoryDumper.parse_replies(ch_replies, users)
        #    data_replies = "%s\n%s\n\n%s" % (header_str, HistoryDumper.sep_str, data_replies)
        #    HistoryDumper.save(data_replies, replies_save_path, 'txt')

    @staticmethod
    def get_channel_save_path(ch_id, ch_list):
        ch_name, ch_type = HistoryDumper.name_from_ch_id(ch_id, ch_list)
        return "%s/%s" % (ch_name, ch_name)

    @staticmethod
    def save_channel_history(channel_hist, channel_id, channel_list, users):
        channel_save_path = HistoryDumper.get_channel_save_path(channel_id, channel_list)
        if HistoryDumper.load_from_cache(channel_save_path) is None:
            ch_name, ch_type = HistoryDumper.name_from_ch_id(channel_id, channel_list)
            HistoryDumper.save(channel_hist, channel_save_path, 'json')
            # @TODO TERRIBLY SLOW, refactoring required
            #if HistoryDumper.a.p:
            #    data_ch = HistoryDumper.parse_channel_history(channel_hist, users)
            #    header_str = "%s Name: %s" % (ch_type, ch_name)
            #    data_ch = (
            #            "Channel ID: %s\n%s\n%s Messages\n%s\n\n"
            #            % (channel_id, header_str, len(channel_hist), HistoryDumper.sep_str)
            #            + data_ch
            #    )
            #    HistoryDumper.save(data_ch, channel_save_path, 'txt')
        else:
            HistoryDumper.logger.info(f"Found in cache, skipping: {channel_save_path}")

        if HistoryDumper.a.r:
            HistoryDumper.save_channel_replies(channel_hist, channel_id, channel_list, users)


if __name__ == "__main__":
    HistoryDumper().run()
