"""Object-Relational Mapping classess, based on Sqlalchemy, for tracking operations on a bundle

Copyright (c) 2015 Civic Knowledge. This file is licensed under the terms of the
Revised BSD License, included in this distribution as LICENSE.txt
"""
__docformat__ = 'restructuredtext en'

from six import iteritems

from sqlalchemy import event
from sqlalchemy import Column as SAColumn, Integer, Float
from sqlalchemy import Text, String, ForeignKey

from ambry.identity import ObjectNumber
from sqlalchemy.orm import relationship

from . import Base, MutationDict, JSONEncodedObj

class Process(Base):
    """Track processes and operations on database objects"""
    __tablename__ = 'processes'

    id = SAColumn('pr_id', Integer, primary_key=True)

    group = SAColumn('pr_group', Integer, ForeignKey('processes.pr_id'), nullable=True, index=True)
    parent = relationship('Process',  remote_side=[id], backref='children')

    stage = SAColumn('pr_stage', Integer, default=0)
    phase = SAColumn('pr_phase', Text, doc='Process phase: such as ingest or build')

    hostname = SAColumn('pr_host', Text)
    pid = SAColumn('pr_pid', Integer)

    d_vid = SAColumn('pr_d_vid', String(13), ForeignKey('datasets.d_vid'), nullable=False, index=True)
    dataset = relationship('Dataset', backref='process_records')

    t_vid = SAColumn('pr_t_vid', String(15), ForeignKey('tables.t_vid'), nullable=True, index=True)
    table = relationship('Table', backref='process_records')

    s_vid = SAColumn('pr_s_vid', String(17), ForeignKey('datasources.ds_vid'), nullable=True, index=True)
    source = relationship('DataSource', backref='process_records')

    p_vid = SAColumn('pr_p_vid', String(17), ForeignKey('partitions.p_vid'), nullable=True, index=True)
    partition = relationship('Partition', backref='process_records')

    created = SAColumn('pr_created', Float,
                        doc='Creation date: time in seconds since the epoch as a integer.')

    modified = SAColumn('pr_modified', Float,
                        doc='Modification date: time in seconds since the epoch as a integer.')

    item_type = SAColumn('pr_type', Text, doc='Item type, such as table, source or partition')

    item_count = SAColumn('pr_count', Integer, doc='Number of items processed')
    item_total = SAColumn('pr_items', Integer, doc='Number of items to be processed')

    message = SAColumn('pr_message', Text)

    state = SAColumn('pr_state', Text)

    exception_class = SAColumn('pr_ex_class', Text)
    exception_trace = SAColumn('pr_ex_trace', Text)

    log_action = SAColumn('pr_action', Text)

    data = SAColumn('pr_data', MutationDict.as_mutable(JSONEncodedObj))

    def __repr__(self):

        return "{} {}/{} {}:{} {} {}".format(
            self.d_vid, self.hostname, self.pid, self.phase if self.phase else '?', self.stage ,
            self.log_action, self.message)

    def __str__(self):

        return "{} {}/{} {}:{} {} {}".format(
            self.d_vid, self.hostname, self.pid, self.phase if self.phase else '?', self.stage ,
            self.log_action, self.message)

    @property
    def log_str(self):
        import platform
        import os

        parts = []

        # This bit only gets executed when records stored in the database from one node or process are
        # read from another. It won't print out in normall logging,
        if self.hostname != platform.node() or self.pid != os.getpid():
            hostpid = "({}@{})".format(self.pid, self.hostname)
            parts.append(hostpid)

        am = {
            'start': ">",
            'add': '+',
            'update': '.',
            'done': "<",
            '': '?',
            None: '?'
        }

        phase_str = self.phase if self.phase else '?'

        if self.stage:
            phase_str = phase_str + ':' + str(self.stage)

        parts.append(phase_str)

        action_char = am.get(self.log_action,'')

        if self.state == 'error':
            action_char = '!'

        parts.append(action_char)

        if self.s_vid:
            parts.append(self.s_vid)

        if self.t_vid:
            parts.append(self.t_vid)

        if self.p_vid:
            parts.append(self.p_vid)

        parts.append(self.message if self.message else '')

        if self.item_count:
            ic = 'processed '+str(self.item_count)

            if self.item_total:
                ic += ' of {}'.format(self.item_total)

            if self.item_type:
                ic += ' '+self.item_type

            parts.append(ic)



        return ' '.join(parts)

    @property
    def dict(self):
        """A dict that holds key/values for all of the properties in the
        object.

        :return:

        """
        from collections import OrderedDict

        return  OrderedDict( (p.key,getattr(self, p.key)) for p in self.__mapper__.attrs
             if p.key not in ('partition', 'source', 'table','dataset', 'children', 'parent'))


    @staticmethod
    def before_insert(mapper, conn, target):
        from time import time
        target.created = time()

        Process.before_update(mapper, conn, target)

    @staticmethod
    def before_update(mapper, conn, target):
        from time import time
        target.modified = time()


event.listen(Process, 'before_insert', Process.before_insert)
event.listen(Process, 'before_update', Process.before_update)
