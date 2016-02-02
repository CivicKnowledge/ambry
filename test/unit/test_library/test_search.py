# -*- coding: utf-8 -*-
import fudge
from fudge.inspector import arg

try:
    # py2, mock is external lib.
    from mock import MagicMock, Mock
except ImportError:
    # py3, mock is included
    from unittest.mock import MagicMock, Mock

from ambry.library import Library
from ambry.library.search import Search
from ambry.library.search_backends.whoosh_backend import DatasetWhooshIndex, PartitionWhooshIndex,\
    WhooshSearchBackend
from ambry.library.search_backends.sqlite_backend import SQLiteSearchBackend
from ambry.library.search_backends.postgres_backend import PostgreSQLSearchBackend
from ambry.orm import Dataset

from test.factories import PartitionFactory, DatasetFactory
from test.test_base import TestBase


class SearchTest(TestBase):
    def setUp(self):
        super(self.__class__, self).setUp()
        self._my_library = self.library()
        self.backend = WhooshSearchBackend(self._my_library)

    def tearDown(self):
        super(self.__class__, self).tearDown()
        if hasattr(self, 'backend'):
            self.backend.reset()

    def test_uses_library_driver_backend(self):
        self._my_library.config.services.search = None
        search = Search(self._my_library)
        if self._my_library.database.driver == 'sqlite':
            self.assertIsInstance(search.backend, SQLiteSearchBackend)
        if self._my_library.database.driver == 'postgres':
            self.assertIsInstance(search.backend, PostgreSQLSearchBackend)

    def test_uses_backend_from_config(self):
        self._my_library.config.services.search = 'whoosh'
        search = Search(self._my_library)
        self.assertIsInstance(search.backend, WhooshSearchBackend)

    def test_raises_missing_backend_exception_if_config_contains_invalid_backend(self):
        # services.search
        self._my_library.config.services.search = 'foo'
        try:
            Search(self._my_library)
        except Exception as exc:
            self.assertIn('Missing backend', str(exc))

    def test_uses_default_backend_if_library_database_search_is_not_implemented(self):
        with fudge.patched_context(self._my_library.database, 'driver', 'mysql'):
            search = Search(self._my_library)
            self.assertIsInstance(search.backend, WhooshSearchBackend)

    # index_library_datasets tests
    def test_indexes_library_datasets(self):
        DatasetFactory._meta.sqlalchemy_session = self._my_library.database.session
        ds1 = DatasetFactory()
        ds2 = DatasetFactory()
        ds3 = DatasetFactory()
        self._my_library.database.session.commit()
        self.assertEqual(len(self._my_library.datasets), 3)

        fake_index_one = fudge.Fake().is_callable()\
            .expects_call().with_args(arg.passes_test(lambda x: x.vid == ds1.vid)).returns(True)\
            .next_call().with_args(arg.passes_test(lambda x: x.vid == ds2.vid)).returns(True)\
            .next_call().with_args(arg.passes_test(lambda x: x.vid == ds3.vid)).returns(True)

        with fudge.patched_context(DatasetWhooshIndex, 'index_one', fake_index_one):
            search = Search(self._my_library)
            search.index_library_datasets()

    def test_indexes_library_datasets_partitions(self):
        DatasetFactory._meta.sqlalchemy_session = self._my_library.database.session
        PartitionFactory._meta.sqlalchemy_session = self._my_library.database.session
        ds1 = DatasetFactory()
        self.assertEqual(len(self._my_library.datasets), 1)

        partition1 = PartitionFactory(dataset=ds1)
        self._my_library.database.session.commit()

        fake_index_one = fudge.Fake().is_callable()\
            .expects_call().with_args(arg.passes_test(lambda x: x.vid == partition1.vid)).returns(True)

        with fudge.patched_context(PartitionWhooshIndex, 'index_one', fake_index_one):
            search = Search(self._my_library)
            search.index_library_datasets()

    def test_feeds_tick_function_with_indexed_dataset(self):
        # prepare mocks
        fake_backend = MagicMock(spec=SQLiteSearchBackend)
        fake_backend.dataset_index = Mock()
        fake_backend.partition_index = Mock()
        fake_backend.identifier_index = Mock()

        tick_f = Mock()

        fake_library = MagicMock(spec=Library)
        fake_dataset = MagicMock(spec=Dataset)
        fake_library.datasets = [fake_dataset]

        # run
        search = Search(fake_library, backend=fake_backend)
        search.index_library_datasets(tick_f=tick_f)

        # test
        tick_f.assert_called_once_with('datasets: 1 partitions: 0')
