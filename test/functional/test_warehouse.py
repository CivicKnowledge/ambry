# -*- coding: utf-8 -*-
from __future__ import print_function
import os
import stat
import unittest

from ambry_sources import MPRowsFile
from ambry_sources.sources import GeneratorSource, SourceSpec

from test.factories import PartitionFactory, TableFactory
from test.helpers import assert_sqlite_index, assert_valid_ambry_sources, assert_postgres_index
from test.proto import TestBase

class SQLiteInspector(object):
    # FIXME: Implement inspectors instead of mixin.

    @staticmethod
    def assert_is_indexed(warehouse, partition, column):
        pass


class Mixin(object):
    """ Requires successors provide _get_config method returning RunConfig instance. """

    # helpers

    def _assert_is_indexed(self, warehouse, partition, column):
        ''' Raises AssertionError if column is not indexed. '''
        raise NotImplementedError('Override the method and provide db specific index check.')

        # Check the DSN or engine, then switch to :
        assert_sqlite_index(warehouse._backend._connection, partition, column)
        assert_postgres_index(warehouse._backend._connection, table, column)

    def test_query_mpr_with_auto_install(self):
        if isinstance(self, PostgreSQLTest):
            try:
                assert_valid_ambry_sources('0.1.6')
            except AssertionError:
                self.skipTest('Need ambry_sources >= 0.1.6. Update your installation.')
            assert_shares_group(user='postgres')

        library = self.library()

        bundle = library.bundle('build.example.com-generators')

        # The way I use to get completed bundle is wrong (correct is ingest/schema/build), but it does
        # not matter here. Hacking it to speed up the test.
        PartitionFactory._meta.sqlalchemy_session = bundle.dataset.session
        partition1 = PartitionFactory(dataset=bundle.dataset)
        bundle.wrap_partition(partition1)

        try:
            partition1._datafile = _get_datafile(bundle.build_fs, partition1.cache_key)
            rows = library.warehouse.query('SELECT * FROM {};'.format(partition1.vid))
            self.assertEqual(rows, [(0, 0), (1, 1), (2, 2)])
        finally:
            bundle.progress.close()
            library.warehouse.close()
            library.database.close()

    def test_install_and_query_materialized_partition(self):
        # materialized view for postgres and readonly table for sqlite.
        if isinstance(self, PostgreSQLTest):
            try:
                assert_valid_ambry_sources('0.1.6')
            except AssertionError:
                self.SkipTest('Need ambry_sources >= 0.1.6. Update your installation.')

        library = self.library()

        bundle = library.bundle('build.example.com-generators')

        warehouse = self.get_warehouse()

        # The way I use to get completed bundle is wrong (correct is ingest/schema/build), but it does
        # not matter here. Hacking it to speed up the test.
        PartitionFactory._meta.sqlalchemy_session = bundle.dataset.session
        partition1 = PartitionFactory(dataset=bundle.dataset)
        bundle.wrap_partition(partition1)

        try:
            partition1._datafile = _get_datafile(bundle.build_fs, partition1.cache_key)

            # materialize partition (materialized view for postgres, readonly table for sqlite)
            warehouse.materialize(partition1.vid)

            # query partition.
            rows = warehouse.query('SELECT * FROM {};'.format(partition1.vid))

            # now drop the *.mpr file and check again. Query should return the same data.
            #
            syspath = partition1._datafile.syspath
            os.remove(syspath)
            self.assertFalse(os.path.exists(syspath))
            rows = warehouse.query('SELECT * FROM {};'.format(partition1.vid))
            self.assertEqual(rows, [(0, 0), (1, 1), (2, 2)])
        finally:
            bundle.progress.close()
            warehouse.close()
            library.database.close()

    def test_index_creation(self):
        if isinstance(self, PostgreSQLTest):
            try:
                assert_valid_ambry_sources('0.1.6')
            except AssertionError:
                self.SkipTest('Need ambry_sources >= 0.1.6. Update your installation.')

        library = self.library()

        bundle = library.bundle('build.example.com-generators')

        warehouse = self.get_warehouse()

        # The way I use to get completed bundle is wrong (correct is ingest/source schema/dest schema/build),
        # but it does not matter here. Hacking it to speed up the test.
        PartitionFactory._meta.sqlalchemy_session = bundle.dataset.session
        partition1 = PartitionFactory(dataset=bundle.dataset)
        bundle.wrap_partition(partition1)

        try:
            partition1._datafile = _get_datafile(bundle.build_fs, partition1.cache_key)

            # Index creation requires materialized tables.
            warehouse.materialize(partition1.vid)

            # Create indexes
            warehouse.index(partition1.vid, ['col1', 'col2'])

            # query partition.
            self._assert_is_indexed(warehouse, partition1, 'col1')
            self._assert_is_indexed(warehouse, partition1, 'col2')

            # query indexed data
            rows = warehouse.query('SELECT col1, col2 FROM {};'.format(partition1.vid))
            self.assertEqual(rows, [(0, 0), (1, 1), (2, 2)])
        finally:
            bundle.progress.close()
            warehouse.close()
            library.database.close()

    def test_table_install_and_query(self):
        try:
            assert_valid_ambry_sources('0.1.8')
        except AssertionError:
            self.SkipTest('Need ambry_sources >= 0.1.8. Update your installation.')

        library = self.library()

        bundle = library.bundle('build.example.com-casters')

        # The way I use to get completed bundle is wrong (correct is ingest/schema/build), but it does
        # not matter here. Hacking it to speed up the test.
        PartitionFactory._meta.sqlalchemy_session = bundle.dataset.session
        TableFactory._meta.sqlalchemy_session = bundle.dataset.session

        table1 = TableFactory(dataset=bundle.dataset)
        partition1 = PartitionFactory(dataset=bundle.dataset, table=table1, segment=1)
        partition2 = PartitionFactory(dataset=bundle.dataset, table=table1, segment=2)
        bundle.wrap_partition(partition1)
        bundle.wrap_partition(partition2)

        try:
            partition1._datafile = _get_datafile(bundle.build_fs, partition1.cache_key)
            partition2._datafile = _get_datafile(bundle.build_fs, partition2.cache_key, rows=[[3, 3], [4, 4]])

            # Install table
            library.warehouse.install(table1.vid)

            # query all partitions
            rows = library.warehouse.query('SELECT col1, col2 FROM {};'.format(table1.vid))

            # We need to sort rows before check because the order of the table partitions is unknown.
            self.assertEqual(sorted(rows), sorted([(0, 0), (1, 1), (2, 2), (3, 3), (4, 4)]))
        finally:
            bundle.progress.close()
            library.warehouse.close()
            library.database.close()

    def test_query_with_union(self):
        if isinstance(self, PostgreSQLTest):
            try:
                assert_valid_ambry_sources('0.1.6')
            except AssertionError:
                self.SkipTest('Need ambry_sources >= 0.1.6. Update your installation.')
        else:
            # sqlite tests
            try:
                assert_valid_ambry_sources('0.1.8')
            except AssertionError:
                self.skipTest('Need ambry_sources >= 0.1.8. Update your installation.')

        library = self.library()

        bundle = library.bundle('build.example.com-casters')

        warehouse = self.get_warehouse()

        # The way I use to get completed bundle is wrong (correct is ingest/schema/build), but it does
        # not matter here. Hacking it to speed up the test.
        PartitionFactory._meta.sqlalchemy_session = bundle.dataset.session
        TableFactory._meta.sqlalchemy_session = bundle.dataset.session

        table1 = TableFactory(dataset=bundle.dataset)
        partition1 = PartitionFactory(dataset=bundle.dataset, table=table1, segment=1)
        partition2 = PartitionFactory(dataset=bundle.dataset, table=table1, segment=2)
        bundle.wrap_partition(partition1)
        bundle.wrap_partition(partition2)

        try:
            partition1._datafile = _get_datafile(
                bundle.build_fs, partition1.cache_key)
            partition2._datafile = _get_datafile(
                bundle.build_fs, partition2.cache_key, rows=[[3, 3], [4, 4]])

            # execute nested query.
            query = '''
                SELECT col1, col2 FROM {}
                UNION
                SELECT col1, col2 FROM {};'''\
                .format(partition1.vid, partition2.vid)
            rows = library.warehouse.query(query)

            # We need to sort rows before check because the order of the table partitions is unknown.
            self.assertEqual(sorted(rows), sorted([(0, 0), (1, 1), (2, 2), (3, 3), (4, 4)]))
        finally:
            bundle.progress.close()
            library.warehouse.close()
            library.database.close()

# FIXME Run this test only if we have a Sqlite library
class InMemorySQLiteTest(TestBase, Mixin):

    def get_warehouse(self):
        return self.library().warehouse(dsn="sqlite:///")

# FIXME Run this test only if we have a Sqlite library
class FileSQLiteTest(TestBase, Mixin):

    def get_warehouse(self):
        return self.library().warehouse()


# FIXME: Run this test only if we have a Postgres library
class PostgreSQLTest(TestBase, Mixin):

    def get_warehouse(self):
        return self.library().warehouse()


def assert_shares_group(user=''):
    """ Checks that the given user shares group with user who executes tests.

    Args:
        user (str): system username

    Raises:
        AssertionError: if given user is not the member of the tests executor group.

    """
    assert user, 'user is required attribute.'
    import getpass
    import grp
    import pwd
    current_user_group_id = pwd.getpwnam(getpass.getuser()).pw_gid
    current_user_group = grp.getgrgid(current_user_group_id).gr_name

    other_user_groups = [g.gr_name for g in grp.getgrall() if user in g.gr_mem]
    if current_user_group not in other_user_groups:
        details_link = 'https://github.com/CivicKnowledge/ambry_sources#making-mpr-files-readable-by-postgres-user'
        raise AssertionError(
            'This test requires postgres user to be in the {} group.\n'
            'Hint: see {} for details.'.format(current_user_group, details_link))


def is_group_readable(filepath):
    """ Returns True if given file is group readable, otherwise returns False.

    Args:
        filepath (str):

    """
    st = os.stat(filepath)
    return bool(st.st_mode & stat.S_IRGRP)


def get_perm(filepath):
    return stat.S_IMODE(os.lstat(filepath)[stat.ST_MODE])


def _get_generator_source(rows=None):
    if not rows:
        rows = [
            [0, 0],
            [1, 1],
            [2, 2]]

    def gen(rows=rows):
        # generate header
        yield ['col1', 'col2']

        # generate some rows
        for row in rows:
            yield row
    return GeneratorSource(SourceSpec('foobar'), gen())


def _get_datafile(fs, path, rows=None):
    datafile = MPRowsFile(fs, path)
    datafile.load_rows(_get_generator_source(rows=rows))
    return datafile


class BundleWarehouse(TestBase):

    def test_bundle_warehouse_install(self):

        l = self.library()

        b = l.bundle('build.example.com-casters')

        wh = b.warehouse('test')
        print(wh.dsn)

        wh.clean()

        self.assertEqual(0, len(wh.list()))

        self.assertEquals('p00casters006003', wh.install('build.example.com-casters-simple'))
        self.assertEquals('p00casters004003', wh.install('build.example.com-casters-integers'))
        self.assertEquals('p00casters002003', wh.install('build.example.com-casters-simple_stats'))
        self.assertEqual('pERJQxWUVb005001', wh.materialize('build.example.com-generators-demo'))

        self.assertEqual(4, len(wh.list()))

    def test_bundle_warehouse_query(self):
        l = self.library()

        b = l.bundle('build.example.com-casters')
        wh = b.warehouse('test')
        wh.clean()

        self.assertEqual(0, len(wh.list()))

        self.assertEqual(20, sum( 1 for row in wh.query("SELECT * FROM p00casters004003")))
        self.assertEqual(6000, sum(1 for row in wh.query("SELECT * FROM p00casters006003")))
        self.assertEqual(4000, sum(1 for row in wh.query("SELECT * FROM pERJQxWUVb005001")))

        p = l.partition('p00casters004003')

        self.assertEqual(20, sum(1 for row in wh.query("SELECT * FROM {}".format(p.vname))))
        self.assertEqual(20, sum(1 for row in wh.query("SELECT * FROM {}".format(p.name))))


        self.assertEqual(3, len(wh.list()))

    def test_library_warehouse_query(self):
        l = self.library()

        b = l.bundle('build.example.com-casters')
        wh = l.warehouse
        wh.clean()

        self.assertEqual(0, len(wh.list()))

        self.assertEqual(20, sum(1 for row in wh.query("SELECT * FROM p00casters004003")))
        self.assertEqual(6000, sum(1 for row in wh.query("SELECT * FROM p00casters006003")))
        self.assertEqual(4000, sum(1 for row in wh.query("SELECT * FROM pERJQxWUVb005001")))

        self.assertEqual(3, len(wh.list()))


