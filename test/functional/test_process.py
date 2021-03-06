from test.proto import TestBase


class Test(TestBase):
    def test_basic_process_logging(self):
        from ambry.bundle.process import ProcessLogger, ProgressLoggingError

        l = self.library()
        l.drop()
        l.create()

        db = l.database

        pl = ProcessLogger(db.root_dataset)
        pl.clean()

        ps = pl.start('bork', 0, message='Starting')
        ps.done()

        ps = pl.start('bork', 1, message='Starting')
        ps.add('Add 1')
        ps.add('Add 2')
        ps.add('Add 3')  # This one gets updated, so won't appear in output.
        ps.update('Update 1')
        ps.update('Update 2')
        ps.update('Update 3')
        ps.done('Done')
        pl.commit()

        messages = [r.message for r in pl.records if r.stage == 1]

        self.assertEqual(
            sorted([u'Starting', u'Add 1', u'Add 2', u'Update 3', u'Done']),
            sorted(messages))

        with self.assertRaises(ProgressLoggingError):
            ps.add('Should Fail')

        ps = pl.start('Fronk', 2, message='Fronking')

        ps.add('1')
        ps.add_update('2')
        ps.add_update('3')
        ps.add_update('4')
        ps.add('5')
        ps.update('6')

        messages = [r.message for r in pl.records if r.stage == 2]

        self.assertEqual(
            sorted([u'Fronking', u'1', u'4', u'6']),
            sorted(messages))

        with self.assertRaises(ValueError):
            with pl.start('Exc', 3, message='Get Exceptions') as ps:
                raise ValueError('This is an exception')

        messages = [r.message for r in pl.dataset.process_records if r.stage == 3]
        self.assertEqual(
            sorted([u'Get Exceptions', u'This is an exception', 'Failed in context with exception']),
            sorted(messages))

        exc_type = [r.message for r in pl.dataset.process_records if r.stage == 3 and r.exception_trace][0]
        self.assertEqual('This is an exception', exc_type)

        records = []
        children = []
        for r in pl.records:
            records.append(r)
            for c in r.children:
                children.append(c)
        self.assertEqual(len(records), 14)
        self.assertEqual(len(children), 10)

        return
        ##

        ps = pl.start('bork', 20, message='Intervals')
        ps.add('More')
        with pl.interval(lambda: ps.add('here'), interval=1):
            import time

            for i in range(8):
                time.sleep(.5)  # Can't sleep for 10, since it's interrupted by the signal alarm

        ps.done()

        messages = sorted(list(set([r.message for r in db.root_dataset.process_records if r.stage == 20])))

        self.assertEquals(
            sorted([None, u'Intervals', u'More', u'here']),
            sorted(messages))
