#!/usr/bin/env python

import json
import logging
from functools import cached_property
from getpass import getpass

from cli_command_parser import Command, Positional, SubCommand, Flag, Counter, Option, ParamGroup, main
from cli_command_parser.exceptions import UsageError

from mm.__version__ import __author_email__, __version__  # noqa
from mm.config import ConfigFile, AccountConfig
from mm.http_client import AuthClient
from mm.output import CompactJSONEncoder

log = logging.getLogger(__name__)


class GameCLI(Command, description='Memento Mori Game Manager', option_name_mode='*-'):
    action = SubCommand()
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')

    def _init_command_(self):
        from mm.logging import init_logging

        init_logging(self.verbose)

    @cached_property
    def auth_client(self) -> AuthClient:
        return AuthClient(use_cache=False)


class Login(GameCLI, help='Log in for the first time'):
    user_id = Option('-i', type=int, required=True, help='Numeric user ID')
    name = Option('-n', required=True, help='Friendly name to associate with the account (locally only)')

    def main(self):
        account = AccountConfig(self.user_id, name=self.name, config_file=ConfigFile())
        client_key = self.auth_client.get_client_key(account, password=getpass('Please enter the account password: '))
        log.debug(f'Received {client_key=}')
        account.client_key = client_key


class Show(GameCLI, help='Show info'):
    item = Positional(choices=('account',), help='The item to show')

    with ParamGroup('Account', required=True, mutually_exclusive=True):
        user_id = Option('-i', type=int, help='Numeric user ID')
        name = Option('-n', help='Friendly name associated with the account')

    sort_keys = Flag('-s', help='Sort keys in dictionaries during serialization')

    def main(self):
        if self.item == 'account':
            self.print(self.auth_client.login(self.account))

    @cached_property
    def account(self) -> AccountConfig:
        config = ConfigFile()
        if user_id := self.user_id:
            try:
                return config.accounts[str(user_id)]
            except KeyError as e:
                raise UsageError(f'Invalid {user_id=} - pick from: {", ".join(sorted(config.accounts))}') from e
        else:
            for account in config.accounts.values():
                if account.name == self.name:
                    return account

            names = ', '.join(sorted(a.name for a in config.accounts.values()))
            raise UsageError(f'Unable to find an account with name={self.name!r} - pick from: {names}')

    def print(self, data):
        print(json.dumps(data, indent=4, sort_keys=self.sort_keys, ensure_ascii=False, cls=CompactJSONEncoder))


if __name__ == '__main__':
    main()