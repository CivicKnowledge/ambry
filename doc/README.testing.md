
# Test Environment

The test environment splits tests into four groups: 

- Bundle tests, which are the main functional tests.
- Functional tests, to fill in gaps in the Bundle tests.
- Regression tests, to test that bugs are fixed.
- Unit tests, narrow tests of small parts of interfaces.

The focus of testing and coverage will be on the Bundle and Functional tests -- these are the main tests that will be 
required to pass for releases. 

Regression and Unit tests will be primarily used for development. 

These tests should be broken up into their own directories:

* test/bundle
* test/functional
* test/unit
* test/regression

The `python setup.py test` invocation will only run the bundle and functional tests. There should be another invocation,
`python setup.py unitest` to run both the unitests and regression tests.

## Test Setup

The `test.proto.TestBase` base class has fields and methods for setting up a test library, including:

 * config
 * library()
 * import_single_bundle()
 
 The `config` field contains config used for all tests based on the users `.ambry/config.yaml` (FIXME: it seems tests never use user's config. Check again.) updated with support/test-config/config.yaml` file.
 
 The user's `.ambry/config.yaml` file should have a few extra configuration values for testing:
 
 * filesystem.test: The path to the library root for testing
 * database.test-postgres: A DSN to a postgres database
 * database.test-sqlite: A DSN to a sqlite database.
 
 If `database.test-sqlite` isn't specified, it will default to `library.db` in the test root director.

 DSNs listed about can be changed by `AMBRY_TEST_DB` environmental variable which should contain DSN of the db.
 Examples:

```bash
$ export AMBRY_TEST_DB="postgresql+psycopg2://ambry:secret@127.0.0.1/ambry_test"
$ export AMBRY_TEST_DB="sqlite:////tmp/ambry-test.db"
```

 Some scenarios of the test database usage:
1. Default case: AMBRY_TEST_DB is empty. Is such case ambry takes dsn from library.database setting and adds test postfix for database name. For example, if library.database = 'postgresql+psycopg2://ambry:secret@127.0.0.1/ambry' then 'postgresql+psycopg2://ambry:secret@127.0.0.1/ambry_test' database will be used for testing.
2. Case 2: AMBRY_TEST_DB has value - in such case database from environment variable will be used, `library.database` will be ignored.
 
 Test code should use new bundles, located in test.bundle_tests. To get to these bundles in functional tests, inherit your tests from TestBase and call library() method.
 
```python
class Test(TestBase):
    def setUp(cls):
        library = self.library()
```
 
After this call, `library` will contain loaded bundles. Also there is the way to get library without bundles by calling library() method with `use_proto` parameter equals to True.

```python
class Test(TestBase):
    def setUp(cls):
        library = self.library(use_proto=False)
```


## Bundle functional tests. 

Most of the tests should be functional tests, implemented as bundle tests. Bundle tests are integrated into the
bundles. See the `ambry/test/bundle_tests/ingest.example.com/stages` bundle as an example. The test file is `test.py`, 
and it is a normal python `uittest` test class, with annotations to mark tests for specific parts of the build process:

```
class Test(BundleTest):

    @before_run
    def test_before_run(self):
        print 'BEFORE RUN ', self.bundle.identity

    @after_ingest(stage=1)
    def test_after_ingest(self):
        print 'AFTER INGEST ', self.bundle.identity
```

The  test decorators are in `ambry/bundle/events.py`.

### To run tests:
    1. Install ambry
```bash
$ git clone https://github.com/<githubid>/ambry.git
$ cd ambry
$ pip install -r requirements/dev.txt
```

    2. Provide PostgreSQL credentials
Tests use two databases - sqlite and postgresql. SQLite does not need any credentials, but PostgreSQL needs. You should add postgresql-test section with dsn to the database section of the ambry config. Example:
```yaml
database:
    ...
    postgresql-test: postgresql+psycopg2://ambry:secret@127.0.0.1/
```
Note: Do not include database name to the dsn because each test creates new empty database on each run.

    3. Install multicorn and pg_trgm extensions (tested 19.12.2015, on ambry v0.3.1684).
Ambry uses custom postgres template because ambry tests require pg_trgm and multicorn extensions. I do not know how to 
install extensions on the fly, so you need to create the template and install both extensions before running tests. 
If postgres does not have such template all postgres tests will be skipped.

```bash
# Switch to postgres account
sudo su - postgres

# create template
psql postgres -c 'CREATE DATABASE template0_ambry_test TEMPLATE template0;'

# create ambry library schema
psql template0_ambry_test -c 'CREATE SCHEMA IF NOT EXISTS ambrylib;'

# Grant all privileges on ambrylib schema to ambry user. Assume database user is ambry.
psql template0_ambry_test -c 'GRANT ALL PRIVILEGES ON SCHEMA ambrylib to ambry;'

# install extensions
psql template0_ambry_test -c 'CREATE EXTENSION pg_trgm SCHEMA ambrylib;'
psql template0_ambry_test -c 'CREATE EXTENSION multicorn;'

# Create copy permission needed by test framework to create database.
psql postgres -c "UPDATE pg_database SET datistemplate = TRUE WHERE datname='template0_ambry_test';"

# User from the dsn needs USAGE permission (Assuming your db user is ambry)
psql template0_ambry_test -c 'GRANT USAGE ON FOREIGN DATA WRAPPER multicorn TO ambry;'

# Exit postgres account
exit
```

    4. Run all tests. Note: Do not make previous steps more than once.
```bash
$ python setup.py test
```

### To all run tests with coverage:

    1. Run with coverage
```bash
$ coverage run setup.py test
```
    2. Generage html:
```bash
$ coverage html
```
    3. Open htmlcov/index.html in the browser.

### To run certain test (use pytest):
```bash
py.test test/test_metadata/regression/test_ambry_93.py::Test::test_deletes_removed_keys_from_db
```
or all tests of test_metadata module
```bash
py.test test/test_metadata
```

### To stop testing of first fail:
```bash
py.test test/test_metadata -x
```

### To ignore slow tests while developing:
```bash
py.test test -k-slow
```

