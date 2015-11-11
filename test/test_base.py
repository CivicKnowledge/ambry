"""
Created on Jun 22, 2012

@author: eric
"""
import os

import unittest

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.sql.expression import text

from six.moves.urllib.parse import urlparse
from six.moves import input as six_input

from ambry.identity import DatasetNumber
from ambry.orm import Database, Dataset
from ambry.orm.database import POSTGRES_SCHEMA_NAME, POSTGRES_PARTITION_SCHEMA_NAME
from ambry.run import get_runconfig

from ambry.util import memoize

MISSING_POSTGRES_CONFIG_MSG = 'PostgreSQL is not configured properly. Add postgres-test '\
    'to the database config of the ambry config.'
SAFETY_POSTFIX = 'ab1kde2'  # Prevents wrong database dropping.


class TestBase(unittest.TestCase):
    def setUp(self):

        super(TestBase, self).setUp()
        self.dsn = 'sqlite://'  # Memory database

        # Make an array of dataset numbers, so we can refer to them with a single integer
        self.dn = [str(DatasetNumber(x, x)) for x in range(1, 10)]

        self.db = None

    def tearDown(self):
        pass
    def ds_params(self, n, source='source'):
        return dict(vid=self.dn[n], source=source, dataset='dataset')

    @classmethod
    def get_rc(cls):
        """Create a new config file for test and return the RunConfig.

         This method will start with the user's default Ambry configuration, but will replace the
         filesystet.root with the value of filesystem.test, then depending on the value of the AMBRY_TEST_DB
         environmental variable, it will set library.database to the DSN of either database.test-sqlite or
         database.test-postrgres

        """

        from fs.opener import fsopendir
        import os

        rc = get_runconfig()

        config = rc.config

        try:
            del config['accounts']
        except KeyError:
            pass

        config.filesystem.root = config.filesystem.test

        db = os.environ.get('AMBRY_TEST_DB', 'sqlite')

        try:
            config.library.database = config.database['test-sqlite']
        except KeyError:
            sqlite_dsn = 'sqlite:///{root}/library.db'
            config.library.database = sqlite_dsn
            print "WARN: missing config for test database 'test-{}', using '{}' ".format(db, sqlite_dsn)

        cls._db_type = db

        test_root = fsopendir(rc.filesystem('test'))

        with test_root.open('.ambry.yaml', 'w', encoding='utf-8') as f:
            config.dump(f)

        return get_runconfig(test_root.getsyspath('.ambry.yaml'))

    @classmethod
    def config(cls):
        return cls.get_rc()

    @classmethod
    def library(cls):
        from ambry.library import new_library
        return new_library(cls.config())

    @classmethod
    def import_bundles(cls, clean = True, force_import = False):
        """
        Import the test bundles into the library, from the test.test_bundles directory
        :param clean: If true, drop the library first.
        :param force_import: If true, force importaing even if the library already has bundles.
        :return:
        """

        from test import bundle_tests
        import os

        l = cls.library()

        if clean:
            l.drop()
            l.create()

        bundles = list(l.bundles)

        if len(bundles) == 0 or force_import:
            l.import_bundles(os.path.dirname(bundle_tests.__file__), detach=True)

    def new_dataset(self, n=1, source='source'):
        return Dataset(**self.ds_params(n, source=source))

    def new_db_dataset(self, db, n=1, source='source'):
        return db.new_dataset(**self.ds_params(n, source=source))

    def copy_bundle_files(self, source, dest):
        from ambry.bundle.files import file_info_map
        from fs.errors import ResourceNotFoundError

        for const_name, (path, clz) in list(file_info_map.items()):
            try:
                dest.setcontents(path, source.getcontents(path))
            except ResourceNotFoundError:
                pass

    def dump_database(self, table, db=None):

        if db is None:
            db = self.db

        for row in db.connection.execute('SELECT * FROM {}'.format(table)):
            print(row)

    def new_database(self):
        # FIXME: this connection will not be closed properly in a postgres case.
        db = Database(self.dsn)
        db.open()
        return db

    def setup_bundle(self, name, source_url=None, build_url=None, library=None):
        """Configure a bundle from existing sources"""
        from test import bundles
        from os.path import dirname, join
        from fs.opener import fsopendir
        from fs.errors import ParentDirectoryMissingError
        from ambry.library import new_library
        import yaml
        from ambry.util import parse_url_to_dict

        if not library:
            rc = self.get_rc()
            library = new_library(rc)
        self.library = library

        self.db = self.library._db

        if not source_url:
            source_url = 'mem://source'.format(name)

        if not build_url:
            build_url = 'mem://build'.format(name)

        for fs_url in (source_url, build_url):
            d = parse_url_to_dict((fs_url))

            # For persistent fs types, make sure it is empty before the test.
            if d['scheme'] not in ('temp','mem'):
                assert fsopendir(fs_url).isdirempty('/')

        test_source_fs = fsopendir(join(dirname(bundles.__file__), 'example.com', name))

        config = yaml.load(test_source_fs.getcontents('bundle.yaml'))

        b = self.library.new_from_bundle_config(config)
        b.set_file_system(source_url=source_url, build_url=build_url)

        self.copy_bundle_files(test_source_fs, b.source_fs)

        return b

    def new_bundle(self):
        """Configure a bundle from existing sources"""
        from ambry.library import new_library
        from ambry.bundle import Bundle

        rc = self.get_rc()

        self.library = new_library(rc)

        self.db = self.library._db

        return Bundle(self.new_db_dataset(self.db), self.library, build_url='mem://', source_url='mem://')


class PostgreSQLTestBase(TestBase):
    """ Base class for database tests who requires postgresql database. """

    def setUp(self):
        super(PostgreSQLTestBase, self).setUp()
        # Create database and populate required fields.
        self._create_postgres_test_db()
        self.dsn = self.__class__.postgres_test_db_data['test_db_dsn']
        self.postgres_dsn = self.__class__.postgres_test_db_data['postgres_db_dsn']
        self.postgres_test_db = self.__class__.postgres_test_db_data['test_db_name']

    def tearDown(self):
        super(PostgreSQLTestBase, self).tearDown()
        self._drop_postgres_test_db()

    @classmethod
    def _drop_postgres_test_db(cls):
        # drop test database
        if hasattr(cls, 'postgres_test_db_data'):
            test_db_name = cls.postgres_test_db_data['test_db_name']
            assert test_db_name.endswith(SAFETY_POSTFIX), 'Can not drop database without safety postfix.'

            engine = create_engine(cls.postgres_test_db_data['postgres_db_dsn'])
            connection = engine.connect()
            connection.execute('commit')
            connection.execute('DROP DATABASE {};'.format(test_db_name))
            connection.execute('commit')
            connection.close()
        else:
            # no database were created.
            pass

    @classmethod
    def _create_postgres_test_db(cls, conf=None):
        if not conf:
            conf = TestBase.get_rc()  # get_runconfig()

        # we need valid postgres dsn.
        if not ('database' in conf.dict and 'postgres-test' in conf.dict['database']):
            # example of the config
            # database:
            #     postgres-test: postgresql+psycopg2://user:pass@127.0.0.1/ambry
            raise unittest.SkipTest(MISSING_POSTGRES_CONFIG_MSG)
        dsn = conf.dict['database']['postgres-test']
        parsed_url = urlparse(dsn)
        postgres_user = parsed_url.username
        db_name = parsed_url.path.replace('/', '')
        test_db_name = '{}_test_{}'.format(db_name, SAFETY_POSTFIX)
        postgres_db_dsn = parsed_url._replace(path='postgres').geturl()
        test_db_dsn = parsed_url._replace(path=test_db_name).geturl()

        # connect to postgres database because we need to create database for tests.
        engine = create_engine(postgres_db_dsn, poolclass=NullPool)
        with engine.connect() as connection:
            # we have to close opened transaction.
            connection.execute('commit')

            # drop test database created by previuos run (control + c case).
            if cls.postgres_db_exists(test_db_name, engine):
                assert test_db_name.endswith(SAFETY_POSTFIX), 'Can not drop database without safety postfix.'
                while True:
                    delete_it = six_input(
                        '\nTest database with {} name already exists. Can I delete it (Yes|No): '.format(test_db_name))
                    if delete_it.lower() == 'yes':
                        try:
                            connection.execute('DROP DATABASE {};'.format(test_db_name))
                            connection.execute('commit')
                        except:
                            connection.execute('rollback')
                        break

                    elif delete_it.lower() == 'no':
                        break

            #
            # check for test template with required extensions.

            TEMPLATE_NAME = 'template0_ambry_test'
            cls.test_template_exists = cls.postgres_db_exists(TEMPLATE_NAME, connection)

            if not cls.test_template_exists:
                raise unittest.SkipTest(
                    'Tests require custom postgres template db named {}. '
                    'See DEVEL-README.md for details.'.format(TEMPLATE_NAME))

            query = 'CREATE DATABASE {} OWNER {} TEMPLATE {} encoding \'UTF8\';'\
                .format(test_db_name, postgres_user, TEMPLATE_NAME)
            connection.execute(query)
            connection.execute('commit')
            connection.close()

        # create db schemas needed by ambry.
        engine = create_engine(test_db_dsn, poolclass=NullPool)
        engine.execute('CREATE SCHEMA IF NOT EXISTS {};'.format(POSTGRES_SCHEMA_NAME))
        engine.execute('CREATE SCHEMA IF NOT EXISTS {};'.format(POSTGRES_PARTITION_SCHEMA_NAME))

        # verify all modules needed by tests are installed.
        with engine.connect() as conn:

            if not cls.postgres_extension_installed('pg_trgm', conn):
                raise unittest.SkipTest(
                    'Can not find template with pg_trgm extension. See DEVEL-README.md for details.')

            if not cls.postgres_extension_installed('multicorn', conn):
                raise unittest.SkipTest(
                    'Can not find template with multicorn extension. See DEVEL-README.md for details.')

        cls.postgres_test_db_data = {
            'test_db_name': test_db_name,
            'test_db_dsn': test_db_dsn,
            'postgres_db_dsn': postgres_db_dsn}
        return cls.postgres_test_db_data

    @classmethod
    def postgres_db_exists(cls, db_name, conn):
        """ Returns True if database with given name exists in the postgresql. """
        result = conn\
            .execute(
                text('SELECT 1 FROM pg_database WHERE datname=:db_name;'), db_name=db_name)\
            .fetchall()
        return result == [(1,)]

    @classmethod
    def postgres_extension_installed(cls, extension, conn):
        """ Returns True if extension with given name exists in the postgresql. """
        result = conn\
            .execute(
                text('SELECT 1 FROM pg_extension WHERE extname=:extension;'), extension=extension)\
            .fetchall()
        return result == [(1,)]
