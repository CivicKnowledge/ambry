# -*- coding: utf-8 -*-

from sqlalchemy.sql.elements import TextClause
from sqlalchemy.sql.expression import text

from ambry.library.search_backends.base import BaseDatasetIndex, BasePartitionIndex,\
    BaseIdentifierIndex, BaseSearchBackend, IdentifierSearchResult,\
    DatasetSearchResult, PartitionSearchResult

from ambry.util import get_logger

logger = get_logger(__name__)

# debug logging
# import logging
# logger.setLevel(logging.DEBUG)


class PostgresExecMixin(object):

    def execute(self,*args, **kwargs):

        self.backend.library.database.set_connection_search_path()

        return self.backend.library.database.connection.execute(*args, **kwargs)


    def has_table(self, table_name):
        from sqlalchemy.engine.reflection import Inspector

        self.backend.library.database.set_connection_search_path()

        inspector = Inspector.from_engine(self.backend.library.database.engine)

        table_names = inspector.get_table_names(self.backend.library.database._schema)

        return table_name in table_names

class PostgreSQLSearchBackend(BaseSearchBackend):


    def _get_dataset_index(self):
        """ Returns initialized dataset index. """
        return DatasetPostgreSQLIndex(backend=self)

    def _get_partition_index(self):
        """ Returns partition index. """
        return PartitionPostgreSQLIndex(backend=self)

    def _get_identifier_index(self):
        """ Returns identifier index. """
        return IdentifierPostgreSQLIndex(backend=self)

    def _or_join(self, terms):
        """ Joins terms using OR operator.

        Args:
            terms (list): terms to join

        Examples:
            self._or_join(['term1', 'term2']) -> 'term1 | term2'

        Returns:
            str
        """
        from six import text_type

        if isinstance(terms, (tuple, list)):
            if len(terms) > 1:
                return ' | '.join(text_type(t) for t in terms)
            else:
                return terms[0]
        else:
            return terms

    def _and_join(self, terms):
        """ AND join of the terms.

        Args:
            terms (list):

        Examples:
            self._and_join(['term1', 'term2']) -> 'term1 & term2'

        Returns:
            str
        """
        if len(terms) > 1:
            return ' & '.join([self._or_join(t) for t in terms])
        else:
            return self._or_join(terms[0])

    def _join_keywords(self, keywords):
        if isinstance(keywords, (list, tuple)):
            return '(' + self._and_join(keywords) + ')'
        return keywords

class DatasetPostgreSQLIndex(BaseDatasetIndex,PostgresExecMixin):

    def __init__(self, backend=None):
        assert backend is not None, 'backend argument can not be None.'
        super(self.__class__, self).__init__(backend=backend)

        self.create()

    def search(self, search_phrase, limit=None):
        """ Finds datasets by search phrase.

        Args:
            search_phrase (str or unicode):
            limit (int, optional): how many results to return. None means without limit.

        Returns:
            list of DatasetSearchResult instances.

        """

        query, query_params = self._make_query_from_terms(search_phrase, limit=limit)

        self._parsed_query = (str(query), query_params)

        assert isinstance(query, TextClause)

        datasets = {}

        def make_result(vid=None, b_score=0, p_score=0):
            res = DatasetSearchResult()
            res.b_score = b_score
            res.p_score = p_score
            res.partitions = set()
            res.vid = vid
            return res

        if query_params:
            results = self.execute(query, **query_params)

            for result in results:
                vid, dataset_score = result

                datasets[vid] = make_result(vid, b_score=dataset_score)


        logger.debug('Extending datasets with partitions.')

        for partition in self.backend.partition_index.search(search_phrase):

            if partition.dataset_vid not in datasets:
                datasets[partition.dataset_vid] = make_result(partition.dataset_vid)

            datasets[partition.dataset_vid].p_score += partition.score
            datasets[partition.dataset_vid].partitions.add(partition)

        return list(datasets.values())

    def create(self):
        # create table for dataset documents. Create special table for search to make it easy to replace one
        # FTS engine with another.

        if self.has_table('dataset_index'):
            return

        self.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm;');

        # Prevents error:   operator class "gist_trgm_ops" does not exist for access method "gist"
        self.execute("alter extension pg_trgm set schema pg_catalog;" )


        logger.debug('Creating dataset FTS table and index.')

        query = """\
            CREATE TABLE dataset_index (
                vid VARCHAR(256) NOT NULL,
                title TEXT,
                keywords VARCHAR(256)[],
                doc tsvector
            );
        """

        self.execute(query)

        # create FTS index on doc field.
        query = """\
            CREATE INDEX dataset_index_doc_idx ON dataset_index USING gin(doc);
        """
        self.execute(query)

        # Create index on keyword field
        query = """\
            CREATE INDEX dataset_index_keywords_idx on dataset_index USING gin(keywords);
        """
        self.execute(query)

    def reset(self):
        """ Drops index table. """
        query = """
            DROP TABLE dataset_index;
        """
        self.execute(query)

    def is_indexed(self, dataset):
        """ Returns True if dataset is already indexed. Otherwise returns False.

        Args:
            dataset (orm.Dataset):

        Returns:
            bool: True if dataset is indexed, False otherwise.
        """
        query = text("""
            SELECT vid
            FROM dataset_index
            WHERE vid = :vid;
        """)
        result = self.execute(query, vid=dataset.vid)

        return bool(result.fetchall())

    def all(self):
        """ Returns list with all indexed datasets. """
        datasets = []

        query = text("""
            SELECT vid
            FROM dataset_index;""")

        for result in self.execute(query):
            res = DatasetSearchResult()
            res.vid = result[0]
            res.b_score = 1
            datasets.append(res)
        return datasets

    def _index_document(self, document, force=False):
        """ Adds dataset document to the index. """
        query = text("""
            INSERT INTO dataset_index(vid, title, keywords, doc)
            VALUES(:vid, :title, string_to_array(:keywords, ' '), to_tsvector('english', :doc));
        """)
        self.execute(query, **document)

    def _make_query_from_terms(self, terms, limit=None):
        """ Creates a query for dataset from decomposed search terms.

        Args:
            terms (dict or unicode or string):

        Returns:
            tuple of (TextClause, dict): First element is FTS query, second is parameters
                of the query. Element of the execution of the query is pair: (vid, score).

        """

        expanded_terms = self._expand_terms(terms)

        if expanded_terms['doc']:
            # create query with real score.
            query_parts = ["SELECT vid, ts_rank_cd(setweight(doc,'C'), to_tsquery(:doc)) as score"]
        if expanded_terms['doc'] and expanded_terms['keywords']:
            query_parts = ["SELECT vid, ts_rank_cd(setweight(doc,'C'), to_tsquery(:doc)) "
                           " +  ts_rank_cd(setweight(to_tsvector(coalesce(keywords::text,'')),'B'), to_tsquery(:keywords))"
                           ' as score']
        else:
            # create query with score = 1 because query will not touch doc field.
            query_parts = ['SELECT vid, 1 as score']

        query_parts.append('FROM dataset_index')
        query_params = {}
        where_counter = 0

        if expanded_terms['doc']:
            where_counter += 1
            query_parts.append('WHERE doc @@ to_tsquery(:doc)')
            query_params['doc'] = self.backend._and_join(expanded_terms['doc'])

        if expanded_terms['keywords']:

            query_params['keywords'] = self.backend._and_join(expanded_terms['keywords'])

            kw_q = "to_tsvector(coalesce(keywords::text,'')) @@ to_tsquery(:keywords)"

            query_parts.append( ("AND " if where_counter else "WHERE ") + kw_q )


        query_parts.append('ORDER BY score DESC')
        if limit:
            query_parts.append('LIMIT :limit')
            query_params['limit'] = limit

        query_parts.append(';')
        deb_msg = 'Dataset terms conversion: `{}` terms converted to `{}` with `{}` params query.'\
            .format(terms, query_parts, query_params)
        logger.debug(deb_msg)


        q = text('\n'.join(query_parts)), query_params
        logger.debug('Dataset search query: {}'.format(q))
        return q

    def _delete(self, vid=None):
        """ Deletes given dataset from index.

        Args:
            vid (str): dataset vid.

        """
        assert vid is not None
        query = text("""
            DELETE FROM dataset_index
            WHERE vid = :vid;
        """)
        self.execute(query, vid=vid)

class PartitionPostgreSQLIndex(BasePartitionIndex,PostgresExecMixin):

    def __init__(self, backend=None):
        assert backend is not None, 'backend argument can not be None.'
        super(self.__class__, self).__init__(backend=backend)

        self.create()

    def _make_query_from_terms(self, terms, limit=None):
        """ Creates a query for partition from decomposed search terms.

        Args:
            terms (dict or unicode or string):

        Returns:
            tuple of (TextClause, dict): First element is FTS query, second is
            parameters of the query. Element of the execution of the query is
            tuple of three elements: (vid, dataset_vid, score).

        """
        expanded_terms = self._expand_terms(terms)
        terms_used = 0

        if expanded_terms['doc']:
            # create query with real score.
            query_parts = ["SELECT vid, dataset_vid, ts_rank_cd(setweight(doc,'C'), to_tsquery(:doc)) as score"]
        if expanded_terms['doc'] and expanded_terms['keywords']:
            query_parts = ["SELECT vid, dataset_vid, ts_rank_cd(setweight(doc,'C'), to_tsquery(:doc)) "
                           " +  ts_rank_cd(setweight(to_tsvector(coalesce(keywords::text,'')),'B'), to_tsquery(:keywords))"
                           ' as score']
        else:
            # create query with score = 1 because query will not touch doc field.
            query_parts = ['SELECT vid, dataset_vid, 1 as score']

        query_parts.append('FROM partition_index')
        query_params = {}
        where_count = 0

        if expanded_terms['doc']:
            query_parts.append('WHERE doc @@ to_tsquery(:doc)')
            query_params['doc'] = self.backend._and_join(expanded_terms['doc'])
            where_count += 1
            terms_used += 1

        if expanded_terms['keywords']:
            query_params['keywords'] = self.backend._and_join(expanded_terms['keywords'])

            kw_q = "to_tsvector(coalesce(keywords::text,'')) @@ to_tsquery(:keywords)"

            query_parts.append(("AND " if where_count else "WHERE ") + kw_q)

            where_count += 1
            terms_used += 1

        if expanded_terms['from']:

            query_parts.append(("AND " if where_count else "WHERE ") + ' from_year >= :from_year')

            query_params['from_year'] = expanded_terms['from']
            where_count += 1
            terms_used += 1

        if expanded_terms['to']:

            query_parts.append(("AND " if where_count else "WHERE ") + ' to_year <= :to_year')

            query_params['to_year'] = expanded_terms['to']
            where_count += 1
            terms_used += 1

        query_parts.append('ORDER BY score DESC')

        if limit:
            query_parts.append('LIMIT :limit')
            query_params['limit'] = limit

        if not terms_used:
            logger.debug('No terms used; not creating query')
            return None, None

        query_parts.append(';')
        deb_msg = 'Dataset terms conversion: `{}` terms converted to `{}` with `{}` params query.'\
            .format(terms, query_parts, query_params)
        logger.debug(deb_msg)

        return text('\n'.join(query_parts)), query_params

    def search(self, search_phrase, limit=None):
        """ Finds partitions by search phrase.

        Args:
            search_phrase (str or unicode):
            limit (int, optional): how many results to generate. None means without limit.

        Generates:
            PartitionSearchResult instances.
        """
        query, query_params = self._make_query_from_terms(search_phrase, limit=limit)

        self._parsed_query = (str(query), query_params)

        if query is not None:

            self.backend.library.database.set_connection_search_path()

            results = self.execute(query, **query_params)

            for result in results:
                vid, dataset_vid, score = result
                yield PartitionSearchResult(
                    vid=vid, dataset_vid=dataset_vid, score=score)

    def _as_document(self, partition):
        """ Converts partition to document indexed by to FTS index.

        Args:
            partition (orm.Partition): partition to convert.

        Returns:
            dict with structure matches to BasePartitionIndex._schema.

        """
        doc = super(self.__class__, self)._as_document(partition)

        # pass time_coverage to the _index_document.
        doc['time_coverage'] = partition.time_coverage
        return doc

    def _index_document(self, document, force=False):
        """ Adds parition document to the index. """

        time_coverage = document.pop('time_coverage', [])
        from_year = None
        to_year = None
        if time_coverage:
            from_year = int(time_coverage[0]) if time_coverage and time_coverage[0] else None
            to_year = int(time_coverage[-1]) if time_coverage and time_coverage[-1] else None

        query = text("""
            INSERT INTO partition_index(vid, dataset_vid, title, keywords, doc, from_year, to_year)
            VALUES(
                :vid, :dataset_vid, :title,
                string_to_array(:keywords, ' '),
                to_tsvector('english', :doc),
                :from_year, :to_year); """)

        self.execute(query, from_year=from_year, to_year=to_year, **document)

    def create(self):

        if self.has_table('partition_index'):
            return

        logger.debug('Creating partition FTS table.')
        # create table for partition documents. Create special table for search to make it easy to replace one
        # FTS engine with another.
        query = """\
            CREATE TABLE partition_index (
                vid VARCHAR(256) NOT NULL,
                dataset_vid VARCHAR(256) NOT NULL,
                from_year INTEGER,
                to_year INTEGER,
                title TEXT,
                keywords VARCHAR(256)[],
                doc tsvector
            );
        """
        self.execute(query)

        # create FTS index on doc field.
        query = """\
            CREATE INDEX partition_index_doc_idx ON partition_index USING gin(doc);
        """
        self.execute(query)

        # Create index on keywords field
        query = """\
            CREATE INDEX partition_index_keywords_idx on partition_index USING gin(keywords);
        """
        self.execute(query)

    def reset(self):
        """ Drops index table. """
        query = """
            DROP TABLE partition_index;
        """
        self.execute(query)

    def _delete(self, vid=None):
        """ Deletes partition with given vid from index.

        Args:
            vid (str): vid of the partition document to delete.

        """
        assert vid is not None
        query = text("""
            DELETE FROM partition_index
            WHERE vid = :vid;
        """)
        self.execute(query, vid=vid)

    def is_indexed(self, partition):
        """ Returns True if partition is already indexed. Otherwise returns False. """
        query = text("""
            SELECT vid
            FROM partition_index
            WHERE vid = :vid;
        """)
        result = self.execute(query, vid=partition.vid)
        return bool(result.fetchall())

    def all(self):
        """ Returns list with vids of all indexed partitions. """
        partitions = []

        query = text("""
            SELECT dataset_vid, vid
            FROM partition_index;""")

        for result in self.execute(query):
            dataset_vid, vid = result
            partitions.append(PartitionSearchResult(dataset_vid=dataset_vid, vid=vid, score=1))
        return partitions


class IdentifierPostgreSQLIndex(BaseIdentifierIndex,PostgresExecMixin):

    def __init__(self, backend=None):
        assert backend is not None, 'backend argument can not be None.'
        super(self.__class__, self).__init__(backend=backend)

        self.create()

    def search(self, search_phrase, limit=None):
        """ Finds identifiers by search phrase.

        Args:
            search_phrase (str or unicode):
            limit (int, optional): how many results to return. None means without limit.

        Returns:
            list of IdentifierSearchResult instances.

        """

        query_parts = [
            'SELECT identifier, type, name, similarity(name, :word) AS sml',
            'FROM identifier_index',
            'WHERE name % :word',
            'ORDER BY sml DESC, name']

        query_params = {
            'word': search_phrase}

        if limit:
            query_parts.append('LIMIT :limit')
            query_params['limit'] = limit

        query_parts.append(';')

        query = text('\n'.join(query_parts))

        self.backend.library.database.set_connection_search_path()

        results = self.execute(query, **query_params).fetchall()

        for result in results:
            vid, type, name, score = result
            yield IdentifierSearchResult(
                score=score, vid=vid,
                type=type, name=name)

    def _index_document(self, identifier, force=False):
        """ Adds identifier document to the index. """

        query = text("""
            INSERT INTO identifier_index(identifier, type, name)
            VALUES(:identifier, :type, :name);
        """)
        self.execute(query, **identifier)

    def create(self):

        if self.has_table('identifier_index'):
            return

        logger.debug('Creating identifier FTS table.')

        query = """
            CREATE TABLE identifier_index (
                identifier VARCHAR(256) NOT NULL,
                type VARCHAR(256) NOT NULL,
                name TEXT);
        """
        self.execute(query)

        # create index for name.
        query = """
            CREATE INDEX identifier_index_name_idx ON identifier_index USING gist (name gist_trgm_ops);
        """
        self.execute(query)

    def reset(self):
        """ Drops identifier index table. """
        query = """
            DROP TABLE identifier_index;
        """
        self.execute(query)

    def _delete(self, identifier=None):
        """ Deletes given identifier from index.

        Args:
            identifier (str): identifier of the document to delete.

        """
        query = text("""
            DELETE FROM identifier_index
            WHERE identifier = :identifier;
        """)
        self.execute(query, identifier=identifier)

    def is_indexed(self, identifier):
        """ Returns True if identifier is already indexed. Otherwise returns False. """
        query = text("""
            SELECT identifier
            FROM identifier_index
            WHERE identifier = :identifier;
        """)
        result = self.execute(query, identifier=identifier['identifier'])
        return bool(result.fetchall())

    def all(self):
        """ Returns list with all indexed identifiers. """
        identifiers = []

        query = text("""
            SELECT identifier, type, name
            FROM identifier_index;""")

        for result in self.execute(query):
            vid, type_, name = result
            res = IdentifierSearchResult(
                score=1, vid=vid, type=type_, name=name)
            identifiers.append(res)
        return identifiers

