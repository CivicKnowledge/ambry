
class RandomSourcePipe(object):

    def __init__(self, bundle, source):

        self.year = int(source.time)
        self.space = source.space

    def __iter__(self):

        import uuid
        import random
        from datetime import date
        from geoid import civick
        from collections import OrderedDict

        categorical = ['red', 'blue', 'green', 'yellow', 'black']

        states = list(range(2))
        counties = list(range(1, 4))
        tracts = list(range(1, 6))
        bgs = list(range(1, 6))

        rc = random.choice

        for i in range(20000):
            row = OrderedDict()

            row['uuid'] = str(uuid.uuid4())
            row['int'] = random.randint(0, 100)
            row['float'] = random.random() * 100
            row['categorical'] = rc(categorical)
            row['ordinal'] = random.randint(0, 10)
            row['gaussian'] = random.gauss(100, 15)
            row['triangle'] = random.triangular(500, 1500, 1000)
            row['exponential'] = random.expovariate(.001)
            row['year'] = self.year
            row['date'] = date(self.year, random.randint(1, 12), random.randint(1, 28))

            row['bg_gvid'] = str(civick.Blockgroup(rc(states), rc(counties), rc(tracts), rc(bgs)))

            if i == 0:
                yield list(row.keys())

            yield list(row.values())
