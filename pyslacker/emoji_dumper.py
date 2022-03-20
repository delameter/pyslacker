#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# script for batch slack emoji download
# 2022 A. Shavykin <0.delameter@gmail.com>
# -----------------------------------------------------------------------------
# SEMI-MANUAL MODE ONLY
# 1. Fetch all data from this endpoint: https://api.slack.com/methods/emoji.list/
# 2. Save it to a file (.json)
# 3. Activate venv: source venv/bin/activate
# 4. Launch this script, it takes two args; first is path to json-file, second is output dir
#    Example: ./util/emoji-dump.py ./emoji.json ./.slack-backup/emoji/
# -----------------------------------------------------------------------------
from __future__ import annotations

import abc
import json
import locale
import os.path
import sys
from argparse import ArgumentParser, Namespace
from os.path import splitext, realpath
from typing import List, Dict, cast, Tuple

import requests
from requests import Response

from pyslacker.core.adaptive_request_manager import AdaptiveRequestManager
from pyslacker.core.exception_handler import ExceptionHandler
from pyslacker.core.logger import Logger
from pyslacker.util.io import fmt_sizeof


class Downloader:
    def __init__(self):
        self._logger: Logger = Logger.get_instance()

    def download_list(self, emojis: List[EmojiRegular], origin: str):
        if len(emojis) == 0:
            self._logger.info(f'Received empty download list')
            return

        self._logger.info(f'Downloading starts for {len(emojis):n} emojis')
        EmojiDumper.adaptive_request_manager.reinit(len(emojis))

        EmojiDumper.adaptive_request_manager.before_paginated_batch(origin)
        for emoji in emojis:
            try:
                EmojiDumper.adaptive_request_manager.perform_retriable_request(
                    lambda attempt_num: self.download(emoji),
                    lambda emoji: emoji.name,
                )
            except RuntimeError as e:
                self._logger.error(str(e))
                sys.exit(1)

        EmojiDumper.adaptive_request_manager.after_paginated_batch()

    def download(self, emoji: EmojiRegular) -> Tuple[Response, int]:
        if os.path.isfile(emoji.filepath):
            raise FileExistsError(f'File already exists: {emoji.filepath}')

        self._logger.debug(f'Fetching: {emoji.url}')
        response: Response = requests.get(emoji.url, timeout=(10, 30), stream=True)

        self._logger.debug(f'Writing: {emoji.filepath}')
        content_size = 0
        with open(emoji.filepath, 'wb') as fp:
            for chunk in response.iter_content(1024 * 1024):
                fp.write(chunk)
                content_size += len(chunk)
        self._logger.debug(f'Writing done: ({fmt_sizeof(content_size).strip()})')

        return response, content_size


# noinspection PyMethodMayBeStatic
class EmojiFactory:
    def from_url(self, name: str, url: str) -> AbstractEmoji:
        if url.startswith('http'):
            return EmojiRegular(name, url)
        elif url.startswith('alias'):
            return EmojiAlias(name, url.split(':')[1])
        else:
            raise ValueError(f'Invalid/unknown URL type: {url} for {name}')


class AbstractEmoji(metaclass=abc.ABCMeta):
    def __init__(self, name: str):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_regular(self) -> bool:
        return isinstance(self, EmojiRegular)

    @property
    def is_alias(self) -> bool:
        return isinstance(self, EmojiAlias)


class EmojiRegular(AbstractEmoji):
    def __init__(self, name: str, url: str):
        super(EmojiRegular, self).__init__(name)
        self._url: str = url
        self._filename: str|None = None
        self._filepath: str|None = None
        self._file_exists: bool = False

    def set_file(self, output_dir: str, filename: str|None = None):
        if filename is None:
            if self._url is None:
                raise ValueError(f'Neither filename nor url is provided for {self._name}')
            filename = self._name + splitext(self._url)[1]

        self._filename = filename
        self._filepath = realpath(os.path.join(output_dir, self._filename))
        self._file_exists = os.path.isfile(self._filepath)

    @property
    def file_exists(self) -> bool:
        return self._file_exists

    @property
    def filepath(self) -> str:
        return self._filepath

    @property
    def url(self) -> str:
        return self._url


class EmojiAlias(AbstractEmoji):
    def __init__(self, name: str, alias_for_name: str):
        super(EmojiAlias, self).__init__(name)
        self._alias_for_name: str = alias_for_name
        self._alias_for: EmojiRegular|None = None

    @property
    def alias_for_name(self) -> str:
        return self._alias_for_name

    @property
    def alias_for(self) -> EmojiRegular|None:
        return self._alias_for

    def set_alias_reference(self, alias: EmojiRegular):
        self._alias_for = alias


class EmojiSet:
    def __init__(self, api_response: dict, output_dir: str):
        self._logger = Logger.get_instance()
        self._emoji_factory = EmojiFactory()
        self._emoji_map: Dict[str, AbstractEmoji] = {}
        self._emojis_regular: List[EmojiRegular] = []

        self._parse_api_response(api_response)
        self._logger.info(f'Loaded {len(self._emoji_map):n} emoji definitions')

        self._set_dir(output_dir)
        self._set_alias_references()

    def get_by_name(self, name: str) -> AbstractEmoji:
        if name not in self._emoji_map.keys():
            raise KeyError(f'Emoji with name "{name}" not defined')
        return self._emoji_map[name]

    def get_for_downloading(self) -> List[EmojiRegular]:
        return [e for e in self._emojis_regular if not e.file_exists]

    def _parse_api_response(self, api_response: dict):
        if not api_response['ok']:
            raise RuntimeError(f'Api error encountered: {api_response!s}')

        for name, url in api_response['emoji'].items():
            self._emoji_map[name] = self._emoji_factory.from_url(name, url)

    def _set_dir(self, output_dir: str):
        files_exist = 0
        for emoji in self._emoji_map.values():
            if not emoji.is_regular:
                continue

            emoji = cast(EmojiRegular, emoji)
            emoji.set_file(output_dir)
            self._emojis_regular.append(emoji)

            if emoji.file_exists:
                files_exist += 1

        self._logger.info(f'Found {files_exist:n} already existing files')

    def _set_alias_references(self):
        for emoji in self._emoji_map.values():
            if not emoji.is_alias:
                continue
            emoji = cast(EmojiAlias, emoji)
            try:
                resolving_emoji = emoji
                while True:
                    alias = self.get_by_name(resolving_emoji.alias_for_name)
                    if isinstance(alias, EmojiRegular):
                        break
                    resolving_emoji = alias

                emoji.set_alias_reference(alias)
            except KeyError:
                self._logger.warn(f'No emoji named "{emoji.alias_for_name}" found - probably generic non-slack emoji name')


# noinspection PyMethodMayBeStatic
class JsonReader:
    def read(self, filepath: str) -> dict:
        try:
            with open(filepath, 'r', encoding='utf-8') as fp:
                return json.load(fp)
        except Exception as e:
            raise RuntimeError(f'Reading failed: {filepath}') from e


# noinspection PyMethodMayBeStatic
class EmojiDumper:
    adaptive_request_manager: AdaptiveRequestManager

    def __init__(self):
        locale.setlocale(locale.LC_ALL, '')

        self.logger = Logger.get_instance(require_new=True)
        EmojiDumper.adaptive_request_manager = AdaptiveRequestManager.get_instance()
        self.args: Namespace

    def run(self):
        _hanlder = ExceptionHandler()
        try:
            self._invoke()
        except Exception as e:
            _hanlder.handle(e)
        print()

    def _parse_args(self) -> Namespace:
        parser = ArgumentParser(
            description='Backup Slack workspace emojis',
            add_help=False,
        )
        parser.add_argument('input_file', metavar='<file>',  help='file to read API response from')
        parser.add_argument('output_dir', metavar='<dir>', help='directory where downloaded images will be saved')
        return parser.parse_args()

    def _invoke(self):
        self.args = self._parse_args()
        api_response = JsonReader().read(self.args.input_file)
        emoji_set = EmojiSet(api_response, self.args.output_dir)
        Downloader().download_list(emoji_set.get_for_downloading(),
                                   realpath(self.args.input_file))


if __name__ == '__main__':
    EmojiDumper().run()
