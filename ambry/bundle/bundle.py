"""The Bundle object is the root object for a bundle, which includes accessors
for partitions, schema, and the filesystem.

Copyright (c) 2015 Civic Knowledge. This file is licensed under the terms of
the Revised BSD License, included in this distribution as LICENSE.txt

"""

from ..util import get_logger
from ..dbexceptions import ConfigurationError, ProcessError
from ..util import Constant, memoize

class Bundle(object):

    def __init__(self, dataset, library, source_url=None, build_url=None):
        import logging

        self._dataset = dataset
        self._library = library
        self._logger = None

        assert bool(library)

        self._log_level = logging.INFO

        self._errors = []
        self._warnings = []

        self._source_url = source_url
        self._build_url = build_url

        self._pipeline_editor = None # A function that can be set to edit the pipeline, rather than overriding the method


    def set_file_system(self, source_url=None, build_url=None):
        """Set the source file filesystem and/or build  file system"""

        assert isinstance(source_url, basestring) or source_url is  None
        assert isinstance(build_url, basestring) or build_url is  None

        if source_url:
            self._source_url = source_url
            self.dataset.config.library.source.url = self._source_url
            self.dataset.commit()

        if build_url:
            self._build_url = build_url
            self.dataset.config.library.build.url = self._build_url
            self.dataset.commit()


    def cast_to_subclass(self, clz):
        return clz(self._dataset, self._library, self._source_url, self._build_url)

    def cast_to_build_subclass(self):
        """
        Load the bundle file from the database to get the derived bundle class,
        then return a new bundle built on that class

        :return:
        """
        from ambry.orm import File
        bsf = self.build_source_files.file(File.BSFILE.BUILD)
        return self.cast_to_subclass(bsf.import_bundle())

    def cast_to_meta_subclass(self):
        """
        Load the bundle file from the database to get the derived bundle class,
        then return a new bundle built on that class

        :return:
        """
        from ambry.orm import File

        bsf = self.build_source_files.file(File.BSFILE.BUILDMETA)
        return self.cast_to_subclass(bsf.import_bundle())

    def import_lib(self):
        from ambry.orm import File
        self.build_source_files.file(File.BSFILE.LIB).import_lib()

    def commit(self):
        return self.dataset.commit()

    @property
    def dataset(self):
        from sqlalchemy import inspect

        if inspect(self._dataset).detached:
            vid = self._dataset.vid
            self._dataset = self._dataset._database.dataset(vid)

        return self._dataset

    @property
    def identity(self):
        return self.dataset.identity

    @property
    def library(self):
        return self._library

    @property
    def schema(self):
        """Return the Schema acessor"""
        from schema import Schema
        return Schema(self)

    @property
    def partitions(self):
        """Return the Schema acessor"""
        from partitions import Partitions
        return Partitions(self)

    def partition(self, ref):
        """Return the Schema acessor"""
        from partitions import Partitions
        for p in self.partitions:
            if p.vid == str(ref):
                return p
        return None

    def wrap_partition(self, p):
        from partitions import PartitionProxy
        return PartitionProxy(self, p)

    def delete_partition(self, vid_or_p):

        try:
            vid = vid_or_p.vid
        except AttributeError:
            vid = vid_or_p

        vid = vid_or_p.vid

        print '!!!!', vid

        p = self.partition(vid)

        self.dataset._database.session.delete(p._partition)


    def source(self, name):
        source =  self.dataset.source_file(name)

        if not source:
            return None

        source._cache_fs = self._library.download_cache
        source._library = self._library
        return source

    @property
    def sources(self):

        for source in self.dataset.sources:
            source._cache_fs = self._library.download_cache
            source._library = self._library
            yield source

    @property
    def metadata(self):
        """Return the Metadata acessor"""
        return self.dataset.config.metadata

    @property
    def build_source_files(self):
        """Return acessors to the build files"""

        from files import BuildSourceFileAccessor
        return BuildSourceFileAccessor(self.dataset, self.source_fs)

    @property
    @memoize
    def source_fs(self):
        from fs.opener import fsopendir

        source_url = self._source_url if self._source_url else self.dataset.config.library.source.url 
        
        if not source_url:
            raise ConfigurationError('Must set source URL either in the constructor or the configuration')
        
        return fsopendir(source_url)

    @property
    @memoize
    def build_fs(self):
        from fs.opener import fsopendir

        build_url = self._build_url if self._build_url else self.dataset.config.library.build.url
        
        if not build_url:
            raise ConfigurationError('Must set build URL either in the constructor or the configuration')

        return fsopendir(build_url)

    def do_pipeline(self, source=None):
        """COnstruct the meta pipeline. This method shold not be overridden; iverride meta_pipeline() instead. """

        resolved_source = self.source(source) if isinstance(source, basestring) else source

        if not resolved_source and source:
            from ..etl import PipelineError
            raise PipelineError('Failed to resolve source name: {}'.format(source))

        pl = self.pipeline(source)

        return pl

    def pipeline(self, source=None):
        """Construct the ETL pipeline for all phases. Segments that are not used for the current phase
        are filtered out later. """
        from ambry.etl.pipeline import Pipeline, MergeHeader, MangleHeader, WriteToPartition, SelectPartition
        from ambry.etl.intuit import TypeIntuiter

        if source:
            source = self.source(source) if isinstance(source, basestring) else source
        else:
            source = None

        pl =  Pipeline(
                bundle = self,
                source=source.source_pipe() if source else None,
                source_first=None,
                source_row_intuit=None,
                source_coalesce_rows=MergeHeader(),
                source_type_intuit=TypeIntuiter(),
                source_last=None,
                write_source_schema=None,
                schema_first=None,
                source_map_header=MangleHeader(),
                dest_map_header=None,
                dest_cast_columns=None,
                dest_augment=None,
                schema_last=None,
                write_dest_schema=None,
                build_first=None,
                select_partition = SelectPartition(),
                build_last=None,
                write_to_table= WriteToPartition()
        )

        self.modify_pipe_from_metadata(pl)

        self.edit_pipeline(pl)

        return pl

    def modify_pipe_from_metadata(self, pl):
        """Modify the pipeline based on entries in the pipeline section of the metadata"""
        import ambry.etl

        for group_name, e in self.metadata.pipeline.items():

            if isinstance(e, basestring):
                e = eval(e)
            else:
                e = [ eval(i) for i in e]

            pl[group_name] = e


    def set_edit_pipeline(self, f):
        """Set a function to edit the pipeline"""

        self._pipeline_editor = f

    def edit_pipeline(self, pipeline):
        """Called after the meta pipeline is constructed, to allow per-pipeline modification."""

        if self._pipeline_editor:
            self._pipeline_editor(pipeline)

        return pipeline

    @property
    def logger(self):
        """The bundle logger."""
        import sys

        if not self._logger:

            ident = self.identity
            template = "%(levelname)s " + ident.sname + " %(message)s"

            self._logger = get_logger(__name__, template=template, stream=sys.stdout)

            self._logger.setLevel(self._log_level)

        return self._logger

    def log(self, message, **kwargs):
        """Log the messsage."""
        self.logger.info(message)

    def error(self, message):
        """Log an error messsage.

        :param message:  Log message.

        """
        if message not in self._errors:
            self._errors.append(message)

        self.set_error_state()
        self.logger.error(message)

    def warn(self, message):
        """Log an error messsage.

        :param message:  Log message.

        """
        if message not in self._warnings:
            self._warnings.append(message)

        self.logger.warn(message)

    def fatal(self, message):
        """Log a fatal messsage and exit.

        :param message:  Log message.

        """
        import sys

        self.logger.fatal(message)
        sys.stderr.flush()
        if self.exit_on_fatal:
            sys.exit(1)
        else:
            from ..dbexceptions import FatalError

            raise FatalError(message)

    ##
    ## Build Process
    ##

    STATES = Constant()
    STATES.NEW = 'new'
    STATES.SYNCED = 'synced'
    STATES.DOWNLOADED = 'downloaded'
    STATES.CLEANING = 'cleaning'
    STATES.CLEANED = 'cleaned'
    STATES.PREPARING = 'preparing'
    STATES.PREPARED = 'prepared'
    STATES.BUILDING = 'building'
    STATES.BUILT = 'built'
    STATES.FINALIZING = 'finalizing'
    STATES.FINALIZED = 'finalized'
    STATES.INSTALLING = 'installing'
    STATES.INSTALLED = 'installed'
    STATES.META = 'meta'

    # Other things that can be part of the 'last action'
    STATES.INFO = 'info'

    ##
    ## Source Synced
    ##

    def do_sync(self, force = None, defaults = False):

        if self.is_finalized:
            self.error("Can't sync; bundle is finalized")
            return False

        ds = self.dataset

        syncs  = self.build_source_files.sync(force, defaults)

        self.state = self.STATES.SYNCED
        self.log("---- Synchronized ----")
        self.dataset.commit()

        return syncs

    def sync(self, force=None, defaults = False):
        """

        :param force: Force a sync in one direction, either ftr or rtf.
        :param defaults [False] If True and direction is rtf, write default source files
        :return:
        """

        if self.is_finalized:
            self.error("Can't sync; bundle is finalized")
            return False

        self.do_sync(force, defaults = defaults)

        return True

    ##
    ## Do All; Run the full process

    def run(self):

        if self.is_finalized:
            self.error("Can't run; bundle is finalized")
            return False

        #if not b.do_clean():
        #    b.error('Run: failed to clean')
        #    return False

        if not self.do_sync():
            self.error('Run: failed to sync')
            return False

        if not self.do_meta():
            self.error('Run: failed to meta')
            return False

        b = self.cast_to_build_subclass()

        if not b.do_prepare():
            b.error('Run: failed to prepare')
            return False

        if not b.do_build():
            b.error('Run: failed to build')
            return False

        b.finalize()

        return b

    ##
    ## Clean
    ##

    @property
    def is_clean(self):
        return self.state == self.STATES.CLEANED

    def do_clean(self):

        if self.clean():
            if self.post_clean():
                self.log("---- Done Cleaning ----")
                self.state = self.STATES.CLEANED
                r = True
            else:
                self.log("---- Post-cleaning ended in Failure ----")
                self.set_error_state()
                self.state = self.STATES.CLEANING  # the clean() method removes states, so we put it back
                r = False

        else:
            self.log("---- Cleaning ended in failure ----")
            self.state = self.STATES.CLEANING  # the clean() method removes states, so we put it back
            self.set_error_state()
            r = False

        self.set_last_access(Bundle.STATES.CLEANED)
        self.dataset.commit()
        return r

    def clean(self):
        """Clean generated objects from the dataset, but only if there are File contents
         to regenerate them"""
        from ambry.orm import ColumnStat, File
        from sqlalchemy.orm import object_session

        if self.is_finalized:
            self.warn("Can't clean; bundle is finalized")
            return False

        self.state = self.STATES.CLEANING

        ds = self.dataset
        s = object_session(ds)

        # FIXME. There is a problem with the cascades for ColumnStats that prevents them from beling deleted with the
        # partitions. Probably, the are seen to be owed by the columns instead.
        s.query(ColumnStat).filter(ColumnStat.d_vid == ds.vid).delete()

        self.dataset.partitions[:] = []

        if ds.bsfile(File.BSFILE.SOURCES).has_contents:
            self.dataset.sources[:] = []

        if ds.bsfile(File.BSFILE.SOURCESCHEMA).has_contents:
            self.dataset.source_tables[:] = []

        if ds.bsfile(File.BSFILE.SCHEMA).has_contents:
            self.dataset.tables[:] = []


        ds.config.build.clean()
        ds.config.process.clean()

        ds.commit()

        return True

    def post_clean(self):
        pass
        return True

    def download(self):
        """Download referenced source files and bundles. BUndles will be instlaled in the warehouse"""

        raise NotImplementedError()

    def load_requirements(self):
        """If there are python library requirements set, append the python dir
        to the path."""

        import sys

        for module_name, pip_name in self.metadata.requirements.items():
            self._library.install_packages(module_name, pip_name)

        python_dir = self._library.filesystem.python()
        sys.path.append(python_dir)

    ##
    ## Prepare
    ##

    @property
    def is_prepared(self):
        return self.state == Bundle.STATES.PREPARED

    def do_prepare(self):
        """This method runs pre_, main and post_ prepare methods."""

        self.load_requirements()

        self.import_lib()

        r = True

        if self.pre_prepare():
            self.state = self.STATES.PREPARING
            self.log("---- Preparing ----")
            if self.prepare_main():
                self.state = self.STATES.PREPARED
                if self.post_prepare():
                    self.log("---- Done Preparing ----")
                else:
                    self.set_error_state()
                    self.log("---- Post-prepare exited with failure ----")
                    r = False
            else:
                self.set_error_state()
                self.log("---- Prepare exited with failure ----")
                r = False
        else:
            self.log("---- Skipping prepare ---- ")

        self.set_last_access(Bundle.STATES.PREPARED)

        self.dataset.commit()

        return r

    def prepare_main(self):
        """This is the methods that is actually called in do_prepare; it
        dispatches to developer created prepare() methods."""
        return self.prepare()

    def prepare(self):
        from ambry.orm.exc import NotFoundError

        return True

    def pre_prepare(self):
        """"""
        from ambry.orm import File

        if self.is_finalized:
            self.warn("Can't prepare; bundle is finalized")
            return False

        self.do_sync()

        self.build_source_files.record_to_objects()

        return True

    def post_prepare(self):
        """"""

        for t in self.schema.tables:
            if not bool(t.description):
                self.error("No title ( Description of id column ) set for table: {} ".format(t.name))

        self.build_source_files.objects_to_record()

        self.commit()

        return True

    ##
    ## Meta
    ##

    def do_meta(self, source_name = None,  print_pipe=False):
        """
        Synchronize with the files and run the meta pipeline, possibly creating new objects. Then, write the
        objects back to file records and synchronize.

        :param force:
        :return:
        """
        from ambry.orm.file import File

        if self.is_finalized:
            self.error("Can't meta; bundle is finalized")
            return False

        if self.is_built:
            self.error("Can't meta; bundle is built")
            return False

        self.import_lib()

        self.do_sync()

        self.build_source_files.record_to_objects()

        self.load_requirements()

        self.log("---- Meta ---- ")

        self.meta(source_name=source_name, print_pipe=print_pipe)

        self.build_source_files.objects_to_record()

        self.build_source_files.file(File.BSFILE.SOURCES).objects_to_record()
        self.build_source_files.file(File.BSFILE.SOURCESCHEMA).objects_to_record()
        self.build_source_files.file(File.BSFILE.SCHEMA).objects_to_record()

        self.do_sync()

        self.set_last_access(Bundle.STATES.META)

        return True

    def meta_make_source_tables(self, pl):
        from ambry.etl.intuit import TypeIntuiter

        ti = pl[TypeIntuiter]

        source = pl.source.source

        if not source.st_id:

            for c in ti.columns:
                source.source_table.add_column(c.position, source_header=c.header, dest_header=c.header,
                                               datatype=c.resolved_type)

    def meta_make_dest_tables(self, pl):

        source = pl.source.source
        dest = pl.source.source.dest_table

        for c in source.source_table.columns:

            dest.add_column(name=c.dest_header, datatype =  c.column_datatype,
                            derivedfrom=c.dest_header,
                            summary=c.summary, description=c.description)

    def meta_log_pipeline(self, pl):
        """Write a report of the pipeline out to a file """
        import os

        self.build_fs.makedir('pipeline', allow_recreate=True)
        self.build_fs.setcontents(os.path.join('pipeline','meta-'+pl.file_name+'.txt' ), unicode(pl), encoding='utf8')

    def meta(self, source_name = None, print_pipe=False):
        from ..etl import PrintRows, augment_pipeline
        from ..orm.source import SourceError

        self.load_requirements()

        for i, source in enumerate(self.sources):

            try:
                if source_name and source.name != source_name:
                    self.logger.info("Skipping {} ( only running {} ) ".format(source.name, source_name))
                    continue

                self.logger.info("Running meta for source: {} ".format(source.name))

                pl = self.do_pipeline(source).meta_phase

                augment_pipeline(pl, tail_pipe=PrintRows)

                pl.run()

                if print_pipe:
                    self.logger.info(pl)

                self.meta_log_pipeline(pl)
                self.meta_make_source_tables(pl)
                self.meta_make_dest_tables(pl)

                source.dataset.commit()

            except Exception as e:
                raise
                self.error('Failed to meta process source {}: {} '.format(source.name, e))

    ##
    ## Build
    ##

    @property
    def is_built(self):
        """Return True is the bundle has been built."""
        return bool(self.dataset.config.build.state.built)

    def do_build(self, table_name = None, force=False, print_pipe=False):

        if self.pre_build(force):
            self.state = self.STATES.BUILDING
            self.log("---- Build ---")
            if self.build(table_name, print_pipe=print_pipe):
                self.state = self.STATES.BUILT
                if self.post_build():
                    self.log("---- Done Building ---")
                    r = True
                else:
                    self.log("---- Post-build failed ---")
                    self.set_error_state()
                    r = False

            else:
                self.log("---- Build exited with failure ---")
                self.set_error_state()
                r = False
        else:
            self.log("---- Skipping Build ---- ")
            self.set_error_state()
            r = False

        self.set_last_access(Bundle.STATES.BUILD)
        return r

    # Build the final package
    def pre_build(self, force = False):

        if not self.is_prepared:
            self.error("Build called before prepare completed ( state = {})".format(self.state))
            return False

        if self.is_built and not force:
            self.error("Bundle is already built. Skipping  ( Use --clean  or --force to force build ) ")
            return False

        if self.is_finalized:
            self.error("Can't build; bundle is finalized")
            return False

        self.load_requirements()

        self.import_lib()

        return True

    def build_log_pipeline(self, table_name, pl):
        """Write a report of the pipeline out to a file """
        import os

        self.build_fs.makedir('pipeline', allow_recreate=True)
        self.build_fs.setcontents(os.path.join('pipeline', 'build-' + table_name + '.txt'), unicode(pl),
                                  encoding='utf8')

    def build(self, target_table_name = None, source_name = None, print_pipe=False):
        from ..etl import PrintRows, augment_pipeline
        from collections import defaultdict

        sources_for_table = defaultdict(set)

        for i, source in enumerate(self.sources):
            sources_for_table[source.dest_table.name].add(source)

        for table_name, sources in sources_for_table.items():

            if target_table_name and table_name != target_table_name:
                self.logger.info("Skipping sources {}, table {} ( only running table {} ) "
                                 .format(','.join(s.name for s in sources), table_name, target_table_name))
                continue

            self.logger.info("Running build for table: {} ".format(table_name))

            pl = self.do_pipeline().build_phase

            if print_pipe:
                augment_pipeline(pl, tail_pipe=PrintRows())

            pl.run(source_pipes = [s.source_pipe() for s in sources])

            if print_pipe:
                self.logger.info(pl)

            self.build_log_pipeline(table_name, pl)
            self.build_post_build_source(pl)

        self.dataset.commit()

        return True

    def build_unify_partitions(self):
        """For all of the segments for a partition, create the parent partition, combine the children into the parent,
        and delete the children. """

        from collections import defaultdict
        from ..orm.partition import Partition
        from ..etl.stats import Stats

        # Group the segments by their parent partition name, which is the
        # same name, without the segment.
        partitions = defaultdict(set)
        for p in self.dataset.partitions:
            if p.type == p.TYPE.SEGMENT:
                name = p.identity.name
                name.segment = None
                partitions[name].add(p)

        # For each group, copy the segment partitions to the parent partitions, then
        # delete the segment partitions.
        for name, segments in partitions.items():

            self.log("Coalescing segments for partition {} ".format(name))

            parent = self.partitions.get_or_new_partition(name, type = Partition.TYPE.UNION)
            stats = Stats(parent.table)

            pdf = parent.datafile
            for seg in sorted(segments, key = lambda s: str(s.name)):

                self.log("Coalescing segment  {} ".format(seg.identity.name))

                reader = self.wrap_partition(seg).datafile.reader()
                header = None
                for row in reader:

                    if header is None:
                        header = row
                        pdf.insert_header(row)
                        stats.process_header(row)
                    else:
                        pdf.insert_body(row)
                        stats.process_body(row)

                reader.close()

            pdf.close()
            parent.finalize(stats)

            for s in segments:
                self.wrap_partition(s).datafile.delete()
                self.dataset._database.session.delete(s)


    def build_post_build_source(self, pl):

        from ..etl import PartitionWriter

        try:
            for p in pl[PartitionWriter].partitions:
                self.logger.info("Finalizing partition {}".format(p.identity.name))
                # We're passing the datafile path into filanize b/c finalize is on the ORM object, and datafile is
                # on the proxy.
                p.finalize()
                # FIXME SHouldn't need to do this commit, but without it, somce stats get added multiple
                # times, causing an error later. Probably could be avoided by adding the states to the
                # collection in the dataset
                self.commit()

        except IndexError:
            self.error("Pipeline didn't have a PartitionWriters, won't try to finalize")

        self.commit()

    def build_post_combine_stats(self):

        pass

    def build_post_write_bundle_file(self):

        path = self.library.create_bundle_file(self)

    def post_build(self):
        """After the build, update the configuration with the time required for
        the build, then save the schema back to the tables, if it was revised
        during the build."""

        self.build_unify_partitions()

        self.build_post_write_bundle_file()

        return True

    ##
    ## Update
    ##

    # Update is like build, but calls into an earlier version of the package.
    def pre_update(self):
        from time import time

        if not self.database.exists():
            raise ProcessError(
                "Database does not exist yet. Was the 'prepare' step run?")

        if not self.get_value('process', 'prepared'):
            raise ProcessError("Update called before prepare completed")

        self._update_time = time()

        self._build_time = time()

        return True

    def update_main(self):
        """This is the methods that is actually called in do_update; it
        dispatches to developer created update() methods."""
        return self.update()

    def update(self):

        self.update_copy_schema()
        self.prepare()
        self.update_copy_partitions()

        return True

    def post_build_test(self):

        f = getattr(self, 'test', False)

        if f:
            try:
                f()
            except AssertionError:
                import traceback
                import sys

                _, _, tb = sys.exc_info()
                traceback.print_tb(tb)  # Fixed format
                tb_info = traceback.extract_tb(tb)
                filename, line, func, text = tb_info[-1]
                self.error("Test case failed on line {} : {}".format(line, text))
                return False

    def post_build_time_coverage(self):
        """Collect all of the time coverage for the bundle."""
        from ambry.util.datestimes import expand_to_years

        years = set()

        # From the bundle about
        if self.metadata.about.time:
            for year in expand_to_years(self.metadata.about.time):
                years.add(year)

        # From the bundle name
        if self.identity.btime:
            for year in expand_to_years(self.identity.btime):
                years.add(year)

        # From all of the partitions
        for p in self.partitions.all:
            if 'time_coverage' in p.record.data:
                for year in p.record.data['time_coverage']:
                    years.add(year)

        self.metadata.coverage.time = sorted(years)

        self.metadata.write_to_dir()

    def post_build_geo_coverage(self):
        """Collect all of the geocoverage for the bundle."""
        from ..dbexceptions import BuildError
        from geoid.civick import GVid
        from geoid import NotASummaryName

        spaces = set()
        grains = set()

        def resolve(term):
            places = list(self.library.search.search_identifiers(term))

            if not places:
                raise BuildError(
                    "Failed to find space identifier '{}' in full text identifier search".format(term))

            return places[0].vid

        if self.metadata.about.space:  # From the bundle metadata
            spaces.add(resolve(self.metadata.about.space))

        if self.metadata.about.grain:  # From the bundle metadata
            grains.add(self.metadata.about.grain)

        if self.identity.bspace:  # And from the bundle name
            spaces.add(resolve(self.identity.bspace))

        # From all of the partitions
        for p in self.partitions.all:
            if 'geo_coverage' in p.record.data:
                for space in p.record.data['geo_coverage']:
                    spaces.add(space)

            if 'geo_grain' in p.record.data:
                for grain in p.record.data['geo_grain']:
                    grains.add(grain)

        def conv_grain(g):
            """Some grain are expressed as summary level names, not gvids."""
            try:
                c = GVid.get_class(g)
                return str(c().summarize())
            except NotASummaryName:
                return g

        self.metadata.coverage.geo = sorted(spaces)
        self.metadata.coverage.grain = sorted(conv_grain(g) for g in grains)

        self.metadata.write_to_dir()

    ##
    ## Finalize
    ##

    @property
    def is_finalized(self):
        """Return True if the bundle is installed."""
        return self.state == self.STATES.FINALIZED

    def do_finalize(self):
        """Call's finalize(); for similarity with other process commands. """
        return self.finalize()

    def finalize(self):
        self.state = self.STATES.FINALIZED
        self.commit()
        return True

    ##
    ## check in to remote
    ##

    def checkin(self):

        if not ( self.is_finalized or self.is_prepared):
            self.error("Can't checkin; bundle state must be either finalized or prepared")
            return False

        self.commit()
        self.library.checkin(self)

    @property
    def is_installed(self):
        """Return True if the bundle is installed."""

        r = self.library.resolve(self.identity.vid)

        return r is not None


    ##
    ##
    ##

    def remove(self):
        """Delete resources associated with the bundle."""
        pass # Remove files in the file system other resource.


    #######
    #######

    def field_row(self, fields):
        """Return a list of values to match the fielsds values"""

        row = self.dataset.row(fields)

        for i, f in enumerate(fields):
            if f == 'state':
                row[i] = self.state

        return row

    def clear_states(self):
        return self.dataset.config.build.clean()

    @property
    def state(self):
        return self.dataset.config.build.state.current

    @property
    def error_state(self):
        """Set the error condition"""
        from time import time

        self.dataset.config.build.state.lastime = time()
        return self.dataset.config.build.state.error

    @state.setter
    def state(self, state):
        """Set the current build state and record the tim eto maintain history"""
        from time import time

        self.dataset.config.build.state.current = state
        self.dataset.config.build.state.error = False
        self.dataset.config.build.state[state] = time()
        self.dataset.config.build.state.lastime = time()

    def set_error_state(self):
        from time import time

        self.dataset.config.build.state.error = time()

    def set_last_access(self, tag):
        """Mark the time that this bundle was last accessed"""

        self.dataset.config.build.access.last = tag
        self.dataset.commit()
