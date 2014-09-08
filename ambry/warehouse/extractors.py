"""Classes for converting warehouse databases to other formats.

Copyright (c) 2013 Clarinova. This file is licensed under the terms of the
Revised BSD License, included in this distribution as LICENSE.txt
"""

import ogr

class ExtractError(Exception):
    pass

def new_extractor(format, warehouse, cache, force=False):

    ex_class = dict(
        csv=CsvExtractor,
        shapefile=ShapeExtractor,
        geojson=GeoJsonExtractor,
        kml=KmlExtractor
    ).get(format, False)

    if not ex_class:
        raise ValueError("Unknown format: {} ".format(format))

    return ex_class(warehouse, cache, force=force)

class Extractor(object):

    def __init__(self, warehouse, cache, force=False):

        self.warehouse = warehouse
        self.database = self.warehouse.database
        self.cache = cache
        self.force = force

    def mangle_path(self,rel_path):
        return rel_path

    def extract(self, table, cache, rel_path):

        if cache.has(self.mangle_path(rel_path)):
            if self.force:
                cache.remove(self.mangle_path(rel_path), True)
            else:
                return False, rel_path, cache.path(self.mangle_path(rel_path)), (table, self.__class__)

        self._extract(table, cache, rel_path)

        return True, rel_path, cache.path(self.mangle_path(rel_path)),(table, self.__class__)

class CsvExtractor(Extractor):

    def __init__(self, warehouse, cache, force=False):
        super(CsvExtractor, self).__init__(warehouse, cache, force=force)


    def _extract(self, table, cache, rel_path):

        import unicodecsv

        rel_path = self.mangle_path(rel_path)

        row_gen = self.warehouse.database.connection.execute("SELECT * FROM {}".format(table))

        w = unicodecsv.writer(cache.put_stream(rel_path))

        for i,row in enumerate(row_gen):
            if i == 0:
                w.writerow(row.keys())

            w.writerow(row)

        return True, cache.path(rel_path)

class OgrExtractor(Extractor):

    epsg = 4326

    def __init__(self, warehouse, cache, force=False):

        super(OgrExtractor, self).__init__(warehouse, cache, force=force)

        self.mangled_names = {}

    def geometry_type(self, database, table):
        """Return the name of the most common geometry type and the coordinate dimensions"""
        ce = database.connection.execute

        types = ce('SELECT count(*) AS count, GeometryType(geometry) AS type,  CoordDimension(geometry) AS cd '
                   'FROM {} GROUP BY type ORDER BY type desc;'.format(table)).fetchall()

        t = types[0][1]
        cd = types[0][2]

        if not t:
            raise ExtractError("No geometries in {}".format(table))

        return t, cd

    geo_map = {
        'POLYGON': ogr.wkbPolygon,
        'MULTIPOLYGON': ogr.wkbMultiPolygon,
        'POINT': ogr.wkbPoint,
        'MULTIPOINT': ogr.wkbMultiPoint,
        # There are a lot more , add them as they are encountered.
    }

    _ogr_type_map = {
        None: ogr.OFTString,
        '': ogr.OFTString,
        'TEXT': ogr.OFTString,
        'VARCHAR': ogr.OFTString,
        'INT': ogr.OFTInteger,
        'INTEGER': ogr.OFTInteger,
        'REAL': ogr.OFTReal,
        'FLOAT': ogr.OFTReal,
    }

    def ogr_type_map(self, v):
        return self._ogr_type_map[v.split('(',1)[0]] # Sometimes 'VARCHAR', sometimes 'VARCHAR(10)'

    def create_schema(self, database, table, layer):
        ce = database.connection.execute

        for row in ce('PRAGMA table_info({})'.format(table)).fetchall():

            if row['name'].lower() in ('geometry', 'wkt','wkb'):
                continue

            name = self.mangle_name(str(row['name']))

            fdfn = ogr.FieldDefn(name, self.ogr_type_map(row['type']))

            print "CREATE", name, self.ogr_type_map(row['type'])

            if row['type'] == '':
                fdfn.SetWidth(254) # FIXME Wasteful, but would have to scan table for max value.

            layer.CreateField(fdfn)

    def new_layer(self, abs_dest, name, t):

        ogr.UseExceptions()

        driver = ogr.GetDriverByName(self.driver_name)

        ds = driver.CreateDataSource(abs_dest)

        if  ds is None:
            raise ExtractError("Failed to create data source for driver '{}' at dest '{}'".format(self.driver_name, abs_dest))

        srs = ogr.osr.SpatialReference()
        srs.ImportFromEPSG(self.epsg)

        # Gotcha! You can't create a layer with a unicode layername!
        # http://gis.stackexchange.com/a/53939/12543
        layer = ds.CreateLayer(name.encode('utf-8'), srs, self.geo_map[t])

        return ds, layer

    def mangle_name(self, name):

        if len(name) <= self.max_name_len:
            return name

        if name in self.mangled_names:
            return self.mangled_names[name]

        for i in range(0,20):
            mname = name[:self.max_name_len]+str(i)
            if mname not in  self.mangled_names.values():
                self.mangled_names[name] = mname
                return mname

        raise Exception("Ran out of names")

    def _extract_shapes(self, abs_dest, table):

        import ogr
        import os

        t, cd = self.geometry_type(self.database, table)

        ds, layer = self.new_layer(abs_dest, table, t)

        self.create_schema(self.database, table, layer)

        q = "SELECT *, AsText(Transform(geometry, {} )) AS _wkt FROM {}".format(self.epsg, table)

        for i,row in enumerate(self.database.connection.execute(q)):

            feature = ogr.Feature(layer.GetLayerDefn())

            for name, value in row.items():
                if name.lower() in ('geometry', 'wkt', 'wkb', '_wkt'):
                    continue
                if value:
                    try:
                        if isinstance(value, unicode):
                            value = str(value)

                        name = self.mangle_name(str(name))

                        feature.SetField(name, value)
                    except Exception as e:
                        print 'Failed for {}={} ({})'.format(name, value, type(value))
                        raise

            geometry = ogr.CreateGeometryFromWkt(row['_wkt'])

            feature.SetGeometryDirectly(geometry)
            if layer.CreateFeature(feature) != 0:
                import gdal
                raise Exception(
                    'Failed to add feature: {}: geometry={}'.format(gdal.GetLastErrorMsg(), geometry.ExportToWkt()))

            feature.Destroy()

        ds.SyncToDisk()
        ds.Release()

        return True, abs_dest

class ShapeExtractor(OgrExtractor):
    driver_name = 'Esri Shapefile'
    max_name_len = 8 # For ESRI SHapefiles

    def mangle_path(self,rel_path):
        if not rel_path.endswith('.zip'):
            rel_path += '.zip'

        return rel_path

    def zip_dir(self, layer_name, source_dir, dest_path):
        """
        layer_name The name of the top level directory in
        """
        import zipfile
        import os

        zf = zipfile.ZipFile(dest_path, 'w', zipfile.ZIP_DEFLATED)

        for root, dirs, files in os.walk(source_dir):
            for f in files:
                zf.write(os.path.join(root, f), os.path.join(layer_name, f))

            zf.close()

    def _extract(self, table, cache, rel_path):

        from ambry.util import temp_file_name
        from ambry.util.flo import copy_file_or_flo
        import shutil
        import os

        rel_path = self.mangle_name(rel_path)

        shapefile_dir = temp_file_name()

        self._extract_shapes(shapefile_dir, table)

        zf =  temp_file_name()

        self.zip_dir(table, shapefile_dir,  zf)

        copy_file_or_flo(zf, cache.put_stream(rel_path))

        shutil.rmtree(shapefile_dir)
        os.remove(zf)

        return cache.path(rel_path)

class GeoJsonExtractor(OgrExtractor):
    driver_name = 'GeoJSON'
    max_name_len = 40

    def temp_dest(self):
        from ambry.util import temp_file_name
        return temp_file_name()

    def _extract(self, table, cache, rel_path):
        from ambry.util import temp_file_name
        from ambry.util.flo import copy_file_or_flo
        import os

        rel_path = self.mangle_name(rel_path)

        tf = temp_file_name() +'.geojson'

        self._extract_shapes(tf, table)

        copy_file_or_flo(tf, cache.put_stream(rel_path))

        os.remove(tf)

        return cache.path(rel_path)

class KmlExtractor(OgrExtractor):
    driver_name = 'KML'
    max_name_len = 40

    def _extract(self, table, cache, rel_path):
        import tempfile
        from ambry.util import temp_file_name
        from ambry.util.flo import copy_file_or_flo
        import os

        rel_path = self.mangle_name(rel_path)

        tf = temp_file_name()

        self._extract_shapes(tf, table)

        copy_file_or_flo(tf, cache.put_stream(rel_path))

        os.remove(tf)

        return cache.path(rel_path)