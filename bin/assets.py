#!/usr/bin/env python

import logging
import os
from abc import ABC
from functools import cached_property
from pathlib import Path

from cli_command_parser import Command, SubCommand, Flag, Counter, Option, Action, main
from cli_command_parser.inputs import Path as IPath, NumRange

from mm.__version__ import __author_email__, __version__  # noqa
from mm.assets import BundleExtractor, Bundle
from mm.client import DataClient
from mm.fs import path_repr
from mm.utils import init_logging

log = logging.getLogger(__name__)

DIR = IPath(type='dir')
FILE = IPath(type='file', exists=True)
FILE_OR_DIR = IPath(type='file|dir', exists=True)


class AssetCLI(Command, description='Memento Mori Asset Manager', option_name_mode='*-'):
    action = SubCommand()
    no_cache = Flag('-C', help='Do not read cached game/catalog data')
    verbose = Counter('-v', help='Increase logging verbosity (can specify multiple times)')

    def _init_command_(self):
        init_logging(self.verbose)

    @cached_property
    def client(self) -> DataClient:
        return DataClient(use_cache=not self.no_cache)


class List(AssetCLI, help='List asset paths'):
    path = Option('-p', help='Show assets relative to the specified path')
    depth: int = Option('-d', help='Show assets up to the specified depth')

    def main(self):
        tree = self.client.asset_catalog.get_asset(self.path) if self.path else self.client.asset_catalog.asset_tree
        for asset in tree.iter_flat(self.depth):
            print(asset)


class Save(AssetCLI, help='Save bundles/assets to the specified directory'):
    item = Action()
    # path = Option('-p', help='Save the specified asset, or all assets inside the specified path', required=True)
    output: Path = Option('-o', type=DIR, help='Output directory', required=True)
    limit: int = Option('-L', help='Limit the number of bundle files to download')
    force = Flag('-F', help='Force bundles to be re-downloaded even if they already exist')
    parallel: int = Option('-P', type=NumRange(min=1), default=4, help='Number of download threads to use in parallel')

    @item(help='Download raw bundles')
    def bundles(self):
        from concurrent.futures import ThreadPoolExecutor, as_completed

        out_dir = self.output.joinpath('bundles')
        out_dir.mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(max_workers=self.parallel) as executor:
            futures = {executor.submit(self.client.get_asset, name): name for name in self._get_bundle_names()}
            log.info(f'Downloading {len(futures)} bundles')
            for future in as_completed(futures):
                bundle_name = futures[future]
                out_path = out_dir.joinpath(bundle_name)
                log.info(f'Saving {bundle_name}')
                out_path.write_bytes(future.result())

    def _get_bundle_names(self) -> list[str]:
        out_dir = self.output.joinpath('bundles')
        if self.force or not out_dir.exists():
            return self.client.asset_catalog.bundle_names

        to_download = [name for name in self.client.asset_catalog.bundle_names if not out_dir.joinpath(name).exists()]
        if self.limit:
            return to_download[:self.limit]
        return to_download

    @item(help='Download bundles and extract the contents')
    def assets(self):
        raise RuntimeError('Not supported yet')


class BundleCommand(AssetCLI, ABC):
    input: Path = Option(
        '-i', type=FILE_OR_DIR, help='Input .bundle file or dir containing .bundle files', required=True
    )

    def iter_src_paths(self):
        if self.input.is_file():
            yield self.input
        else:
            for root, dirs, files in os.walk(self.input):
                for file in files:
                    yield Path(root, file)


class Find(BundleCommand, help='Find bundles containing the specified paths/files'):
    pattern = Option('-p', help='Path pattern to find (supports glob-style wildcards)', required=True)

    def main(self):
        for src_path, content_path in self.iter_matching_contents():
            print(f'Bundle {path_repr(src_path)} contains: {content_path}')

    def iter_bundle_contents(self):
        for src_path in self.iter_src_paths():
            for path in Bundle(src_path).contents:
                yield src_path, path

    def iter_matching_contents(self):
        import posixpath
        from fnmatch import _compile_pattern  # noqa
        from os.path import normcase

        match = _compile_pattern(normcase(self.pattern))
        if os.path is posixpath:  # normcase on posix is NOP. Optimize it away from the loop.
            for src_path, content_path in self.iter_bundle_contents():
                if match(content_path):
                    yield src_path, content_path
        else:
            for src_path, content_path in self.iter_bundle_contents():
                if match(normcase(content_path)):
                    yield src_path, content_path


class Extract(BundleCommand, help='Extract assets from a .bundle file'):
    output: Path = Option('-o', type=DIR, help='Output directory', required=True)
    parallel: int = Option(
        '-P', type=NumRange(min=1), default=4, help='Number of extraction processes to use in parallel'
    )

    def main(self):
        from concurrent.futures import ProcessPoolExecutor, wait

        extractor = BundleExtractor(self.output)
        with ProcessPoolExecutor(
            max_workers=self.parallel, initializer=init_logging, initargs=(self.verbose,)
        ) as executor:
            futures = {
                executor.submit(extractor.extract_bundle, src_path): src_path for src_path in self.iter_src_paths()
            }
            wait(futures)


if __name__ == '__main__':
    main()
