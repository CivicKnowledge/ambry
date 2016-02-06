#
# Class to manage the test directory and prototypes

"""

This class manages the test library directory and databases, primarily by maintaining a "prototype"
of the databases. Tests that require a bundle to operate on can be sped up by copyin the protoitype
rather than creating a new library and building the bundles in it.

For Sqlite libraries, the prototype is held in the /proto directory and copied to the /sqlite directory when
then lirbary is initalized

For postgres libraries, a prototype database is constructed by appending -proto to the end of the name of the
test database. THe proto databse is created and populated, and then flagged for use as a template. When a test
library is created, it is constructed with the proto library as its template.


"""

import logging
import os
import unittest

from ambry.util import ensure_dir_exists, memoize, get_logger
from ambry.library import Library

logger = get_logger(__name__, level=logging.INFO, propagate=False)

DEFAULT_ROOT = '/tmp/ambry-test'  # Default root for the library roots ( The library root is one level down )


class ProtoLibrary(object):
    """Manage test libraries. Creates a proto library, with pre-built bundles, that can be
    copied quickly into a test library, providing bundles to test against"""

    def __init__(self, dsn=None, root=None, config_path=None):
        """

        :param dsn: If specified, the dsn of the test database. If not, defaults to sqlite.
        :param root:
        :param config_path:
        :return:
        """

        from ambry.run import load_config, update_config, load_accounts
        from ambry.util import parse_url_to_dict, unparse_url_dict

        self._root = root

        if not self._root:
            self._root = DEFAULT_ROOT

        if dsn and dsn.startswith('post'):

            self.dsn = dsn

            p = parse_url_to_dict((self.dsn))
            p['path'] = p['path']+'-proto'

            self.proto_dsn = unparse_url_dict(p)

            self._db_type = 'postgres'

        elif dsn and dsn.startswith('sqlite'):

            self.dsn = dsn
            p = parse_url_to_dict((self.dsn))
            p['path'] = p['path'].replace('.db','') + '-proto.db'

            self.proto_dsn = unparse_url_dict(p)

            self._db_type = 'sqlite'

        else:
            self.dsn = 'sqlite:///{}/library.db'.format(self.sqlite_dir())
            self.proto_dsn = 'sqlite:///{}/library.db'.format(self.proto_dir())
            self._db_type = 'sqlite'

        ensure_dir_exists(self._root)

        if config_path is None:
            import test.support
            config_path = os.path.join(os.path.dirname(test.support.__file__), 'test-config')


        self.config = load_config(config_path)

        self.config.update(load_accounts())

        update_config(self.config, use_environ=False)

        assert self.config.loaded[0] == config_path+'/config.yaml'

        self.config.library.database = self.dsn

    def __str__(self):
        return """
root:      {}
dsn:       {}
proto-dsn: {}
""".format(self._root, self.dsn, self.proto_dsn)

    def _ensure_exists(self, dir):
        """Ensure the full path to a directory exists. """

        if not os.path.exists(dir):
            os.makedirs(dir)

    def proto_dir(self, *args):

        base = os.path.join(self._root,'proto')

        self._ensure_exists(base)

        return os.path.join(base, *args)

    def sqlite_dir(self, create = True, *args):

        base = os.path.join(self._root, 'sqlite')

        if create:
            self._ensure_exists(base)

        return os.path.join(base, *args)

    def pg_dir(self, *args):

        base = os.path.join(self._root, 'pg')

        self._ensure_exists(base)

        return os.path.join(base, *args)

    def _create_database(self, pg_dsn=None):
        """Create the database, if it does not exist"""

    def import_bundle(self, l, cache_path):
        """Import a test bundle into a library"""
        from test import bundle_tests

        orig_source = os.path.join(os.path.dirname(bundle_tests.__file__), cache_path)
        imported_bundles = l.import_bundles(orig_source, detach=True, force=True)

        b = next(b for b in imported_bundles).cast_to_subclass()
        b.clean()
        b.sync_in(force=True)
        return b

    def clean_proto(self):
        import shutil
        shutil.rmtree(self.proto_dir())

    def build_proto(self):
        """Builds the prototype library, by building or injesting any bundles that doin't
        exist in it yet. """

        from ambry.orm.exc import NotFoundError

        config = self.config.clone()
        self.proto_dir() # Make sure it exists
        config.library.database = self.proto_dsn

        l = Library(config)

        try:
            b = l.bundle('ingest.example.com-headerstypes')
        except NotFoundError:
            b = self.import_bundle(l, 'ingest.example.com/headerstypes')
            b.log("Build to: {}".format(b.build_fs))
            b.ingest()
            b.close()

        try:
            b = l.bundle('ingest.example.com-stages')
        except NotFoundError:
            b = self.import_bundle(l, 'ingest.example.com/stages')
            b.ingest()
            b.close()

        try:
            b = l.bundle('ingest.example.com-basic')
        except NotFoundError:
            b = self.import_bundle(l, 'ingest.example.com/basic')
            b.ingest()
            b.close()

        try:
            b = l.bundle('build.example.com-coverage')
        except NotFoundError:
            b = self.import_bundle(l,'build.example.com/coverage')
            b.ingest()
            b.source_schema()
            b.schema()
            b.build()
            b.finalize()
            b.close()

        try:
            b = l.bundle('build.example.com-generators')
        except NotFoundError:
            b = self.import_bundle(l,'build.example.com/generators')
            b.run()
            b.finalize()
            b.close()

        try:
            b = l.bundle('build.example.com-casters')
        except NotFoundError:
            b = self.import_bundle(l, 'build.example.com/casters')
            b.ingest()
            b.source_schema()
            b.schema()
            b.build()
            b.finalize()
            b.close()

    def init_library(self, use_proto=True):
        """Initialize either the sqlite or pg library, based on the DSN """
        if self._db_type == 'sqlite':
            return self.init_sqlite(use_proto=use_proto)
        else:

            return self.init_pg(use_proto=use_proto)

    def init_sqlite(self, use_proto=True):

        import shutil

        shutil.rmtree(self.sqlite_dir())

        if use_proto:
            self.build_proto()

            shutil.copytree(self.proto_dir(), self.sqlite_dir(create=False))

            return Library(self.config)

        else:
            self.sqlite_dir() # Ensure it exists
            l = Library(self.config)
            l.create()
            return l

    def init_pg(self, use_proto=True):

        if use_proto:
            #self.create_pg_template()
            #self.build_proto()
            self.create_pg(re_create=True)
        else:
            self.create_pg(re_create=True, template_name='template1')

        l = Library(self.config)
        l.create()
        return l

    @memoize
    def pg_engine(self, dsn):
        """Return a Sqlalchemy engine for a database, by dsn. The result is cached. """
        from ambry.util import select_from_url, set_url_part
        from sqlalchemy import create_engine
        from sqlalchemy.pool import NullPool

        return create_engine(dsn, poolclass=NullPool)

    @property
    @memoize
    def pg_root_engine(self):
        """Return an engine connected to the postgres database, for executing operations on other databases"""
        from ambry.util import set_url_part
        from sqlalchemy import create_engine
        from sqlalchemy.pool import NullPool

        root_dsn = set_url_part(self.dsn, path='postgres')

        return create_engine(root_dsn, poolclass=NullPool)

    def dispose(self):
        self.pg_engine(self.dsn).dispose()
        self.pg_root_engine.dispose()

    @classmethod
    def postgres_db_exists(cls, db_name, conn):
        """ Returns True if database with given name exists in the postgresql. """
        from sqlalchemy.sql.expression import text

        result = conn\
            .execute(
                text('SELECT 1 FROM pg_database WHERE datname=:db_name;'), db_name=db_name)\
            .fetchall()
        return result == [(1,)]

    @classmethod
    def postgres_extension_installed(cls, extension, conn):
        """ Returns True if extension with given name exists in the postgresql. """
        from sqlalchemy.sql.expression import text

        result = conn\
            .execute(
                text('SELECT 1 FROM pg_extension WHERE extname=:extension;'), extension=extension)\
            .fetchall()
        return result == [(1,)]

    def drop_pg(self,database_name):

        with self.pg_root_engine.connect() as conn:
            conn.execute('COMMIT') # we have to close opened transaction.

            if self.postgres_db_exists(database_name, conn):

                try:
                    conn.execute('DROP DATABASE "{}";'.format(database_name))
                    conn.execute('COMMIT;')
                except Exception as e:
                    logger.warn("Failed to drop database '{}': {}".format(database_name, e))
                    conn.execute('ROLLBACK;')
                    raise
                finally:
                    conn.close()

            else:
                logger.warn("Not dropping {}; does not exist".format(database_name))

            conn.close()

    def create_pg_template(self, template_name=None):
        """Create the test template database"""
        from ambry.util import select_from_url

        if template_name is None:
            flag_templ = True
            template_name = select_from_url(self.proto_dsn, 'path').strip('/')
        else:
            flag_templ = False

        # Create the database
        with self.pg_root_engine.connect() as conn:

            if self.postgres_db_exists(template_name, conn):
                return

            conn.execute('COMMIT')  # we have to close opened transaction.

            query = 'CREATE DATABASE "{}" OWNER postgres TEMPLATE template1 encoding \'UTF8\';' \
                .format(template_name)
            conn.execute(query)
            if flag_templ:
                conn.execute("UPDATE pg_database SET datistemplate = TRUE WHERE datname = '{}';"
                             .format(template_name))
            conn.execute('COMMIT;')

            conn.close()

        # Create the extensions, if they aren't already installed
        with self.pg_engine(self.proto_dsn).connect() as conn:
            conn.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm;')
            # Prevents error:   operator class "gist_trgm_ops" does not exist for access method "gist"
            conn.execute('alter extension pg_trgm set schema pg_catalog;')
            conn.execute('CREATE EXTENSION IF NOT EXISTS multicorn;')
            conn.execute('COMMIT;')

            conn.close()

    def create_pg(self, re_create = False, template_name = None):
        from ambry.util import  select_from_url

        import unittest

        database_name = select_from_url(self.dsn, 'path').strip('/')

        if template_name is None:
            template_name = select_from_url(self.proto_dsn, 'path').strip('/')
            load_extensions = False # They are already in template
        else:
            load_extensions = True

        username = select_from_url(self.dsn, 'username')

        if re_create:
            self.drop_pg(database_name)

        with self.pg_root_engine.connect() as conn:

            conn.execute('COMMIT')  # we have to close opened transaction.

            query = 'CREATE DATABASE "{}" OWNER "{}" TEMPLATE "{}" encoding \'UTF8\';' \
                .format(database_name, username, template_name)

            conn.execute(query)

            conn.close()

        # Create the extensions, if they aren't already installed
        if load_extensions:
            with self.pg_engine(self.dsn).connect() as conn:
                conn.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm;')
                # Prevents error:   operator class "gist_trgm_ops" does not exist for access method "gist"
                conn.execute('alter extension pg_trgm set schema pg_catalog;')
                conn.execute('CREATE EXTENSION IF NOT EXISTS multicorn;')
                conn.execute('COMMIT;')

                conn.close()


class TestBase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        pass

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def library(self, dsn=None, use_proto=True):
        """Return a new proto library"""

        from proto import ProtoLibrary

        # IMPLEMENT ME
        # Check AMBRY_TEST_DB and databases.test-postgres for postgres database DSN

        pl = ProtoLibrary(dsn=dsn)

        return pl.init_library(use_proto=use_proto)

