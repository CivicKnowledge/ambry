# -*- coding: utf-8 -*-
# Bundle test code

from ambry.bundle.test import BundleTest
from ambry.bundle.events import *

class Test(BundleTest):

    @before_ingest()
    def test_before_ingest(self):
        pass

    @before_ingest()
    def test_before_ingest(self):
        pass

    @after_ingest()
    def test_after_ingest(self):

        self.assertInSourceHeaders('simple', [u'id', u'uuid', u'int', u'float'])

    @after_run
    def test_after_run(self):
        pass
