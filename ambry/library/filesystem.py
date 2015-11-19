"""
"""

# Copyright (c) 2015 Civic Knowledge. This file is licensed under the terms of the
# Revised BSD License, included in this distribution as LICENSE.txt

from os.path import join, dirname, isdir
from os import makedirs

class LibraryFilesystem():
    """Build directory names from the filesystem entries in the run configuration

    Each of the method will return a directory based on an entry in the configuration. The
    directory will be created with makedirs.
    """


    def __init__(self,  config):

        self._root = config.library.filesystem_root

        self._config = config

    def _compose(self, name, args):
        """Get a named filesystem entry, and extend it into a path with additional
        path arguments"""

        p = self._config.filesystem[name]

        if args:
            p = join(p, *args)\

        p = p.format(root=self._root)

        if not isdir(p):
            makedirs(p)

        return p

    @property
    def root(self):
        return self._root

    def downloads(self, *args):
        return self._compose('downloads',args)

    def extracts(self, *args):
        return self._compose('extracts',args)

    def python(self, *args):
        return self._compose('python',args)

    def source(self, *args):
        return self._compose('source',args)

    def build(self, *args):
        return self._compose('build',args)

    def logs(self, *args):
        return self._compose('logs',args)

    def search(self, *args):
        """For file-based search systems, like Whoosh"""
        return self._compose('search',args)

    @property
    def database_dsn(self):
        """Substitute the root dir into the database DSN, for Sqlite"""

        if not self._config.library.database:
            return 'sqlite:///{root}/library.db'.format(root=self._root)

        return self._config.library.database.format(root=self._root)

    def s3(self, url, account_acessor):
        from fs.s3fs import S3FS
        from ambry.util import parse_url_to_dict
        from ambry.dbexceptions import ConfigurationError

        import ssl

        _old_match_hostname = ssl.match_hostname

        def _new_match_hostname(cert, hostname):
            if hostname.endswith('.s3.amazonaws.com'):
                pos = hostname.find('.s3.amazonaws.com')
                hostname = hostname[:pos].replace('.', '') + hostname[pos:]
            return _old_match_hostname(cert, hostname)

        ssl.match_hostname = _new_match_hostname

        pd = parse_url_to_dict(url)

        account = account_acessor(pd['netloc'])

        assert account.account_id == pd['netloc']

        s3 = S3FS(
            bucket=pd['netloc'],
            prefix=pd['path'],
            aws_access_key=account.access_key,
            aws_secret_key=account.secret,

        )

        # ssl.match_hostname = _old_match_hostname

        return s3
