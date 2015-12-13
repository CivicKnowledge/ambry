"""Copyright (c) 2013 Clarinova.

This file is licensed under the terms of the Revised BSD License,
included in this distribution as LICENSE.txt

"""

from ..cli import warn
from . import prt
from six import print_

def root_parser(cmd):
    import argparse

    sp = cmd.add_parser('list', help='List bundles and partitions')
    sp.set_defaults(command='root')
    sp.set_defaults(subcommand='list')
    sp.add_argument('-f', '--fields', type=str,
                    help="Specify fields to use. One of: 'locations', 'vid', 'status', 'vname', 'sname', 'fqname")
    sp.add_argument('-s', '--sort', help='Sort outputs on a field')
    group = sp.add_mutually_exclusive_group()
    group.add_argument('-t', '--tab', action='store_true',
                       help='Print field tab seperated, without pretty table and header')
    group.add_argument('-p', '--partitions', action='store_true',
                       help='List partitions instead of bundles')
    group.add_argument('-j', '--json', action='store_true',
                       help='Output as a list of JSON dicts')
    sp.add_argument('term', nargs='?', type=str,
                    help='Name or ID of the bundle or partition')

    sp = cmd.add_parser('makemigration', help='Create empty migration (for developers only).')
    sp.set_defaults(command='root')
    sp.set_defaults(subcommand='makemigration')
    sp.add_argument('migration_name', type=str, help='Name of the migration')

    sp = cmd.add_parser('ckan_export', help='Export dataset to CKAN.')
    sp.set_defaults(command='root')
    sp.set_defaults(subcommand='ckan_export')
    sp.add_argument('dvid', type=str, help='Dataset vid')
    sp.add_argument('-f', '--force', action='store_true',
                    help='Ignore existance error and continue to publish.')
    sp.add_argument('-fr', '--debug-force-restricted', action='store_true',
                    help='Export restricted datasets. For debugging only.')

    sp = cmd.add_parser('info', help='Information about a bundle or partition')
    sp.set_defaults(command='root')
    sp.set_defaults(subcommand='info')
    group = sp.add_mutually_exclusive_group()
    group.add_argument('-c', '--configs', default=False, action='store_true',
                       help=' Also dump the root config entries')
    group.add_argument('-r', '--remote', default=False, action='store_true',
                       help='Information about the remotes')


    sp = cmd.add_parser('doc', help='Start the documentation server')
    sp.set_defaults(command='root')
    sp.set_defaults(subcommand='doc')

    sp.add_argument('-c', '--clean', default=False, action='store_true',
                    help='When used with --reindex, delete the index and old files first. ')
    sp.add_argument('-d', '--debug', default=False, action='store_true', help='Debug mode ')
    sp.add_argument('-p', '--port', help='Run on a sepecific port, rather than pick a random one')

    sp = cmd.add_parser('search', help='Search the full-text index')
    sp.set_defaults(command='root')
    sp.set_defaults(subcommand='search')
    sp.add_argument('term', type=str, nargs=argparse.REMAINDER, help='Query term')
    sp.add_argument('-l', '--list', default=False, action='store_true',
                    help='List documents instead of search')
    sp.add_argument('-i', '--identifiers', default=False, action='store_true',
                    help='Search only the identifiers index')
    sp.add_argument('-r', '--reindex', default=False, action='store_true',
                    help='Generate documentation files and index the full-text search')

    sp = cmd.add_parser('sync', help='Sync with the remotes')
    sp.set_defaults(command='root')
    sp.set_defaults(subcommand='sync')

    sp = cmd.add_parser('remove', help='Remove a bundle from the library')
    sp.set_defaults(command='root')
    sp.set_defaults(subcommand='remove')
    sp.add_argument('term', nargs='?', type=str, help='bundle reference')

    sp = cmd.add_parser('import', help='Import multiple source directories')
    sp.set_defaults(command='root')
    sp.set_defaults(subcommand='import')
    sp.add_argument('-d', '--detach', default=False, action='store_true',
                    help="Detach the imported source. Don't set the location of the imported source as the"
                    " source directory for the bundle ")
    sp.add_argument('-f', '--force', default=False, action='store_true',
                    help='Force importing an already imported bundle')
    sp.add_argument('term', nargs=1, type=str, help='Base directory')

    #
    # Search Command
    #

    sp = cmd.add_parser('search', help='Search for bundles and partitions')
    sp.set_defaults(command='root')
    sp.set_defaults(subcommand='search')
    sp.add_argument('-r', '--reindex', default=False, action='store_true',
                    help='Reindex the bundles')
    sp.add_argument('terms', nargs='*', type=str, help='additional arguments')

    sp = cmd.add_parser('docker', help='Manage docker images and containers')
    sp.set_defaults(command='root')
    sp.set_defaults(subcommand='docker')

    sp.add_argument('-s', '--shell', default=False, action='store_true',
                    help="Run a shell on the current docker host, in a new container")

    sp.add_argument('-i', '--init', default=False, action='store_true',
                    help="Initialilze a new data volume and database")

    sp.add_argument('-n', '--new', default=False, action='store_true',
                    help="With -i, initialize a new database and volume, and report the new DSN")



def root_command(args, rc):
    from ..library import new_library
    from . import global_logger
    from ambry.orm.exc import DatabaseError


    if args.test_library:
        rc.set_lirbary_database('test')

    try:
        from ambry.library import global_library, Library
        global global_library

        l = Library(rc, echo=args.echo)

        global_library = l

        l.logger = global_logger
        l.sync_config()
    except DatabaseError as e:
        warn('No library: {}'.format(e))
        l = None
    except Exception as e:

        warn('Failed to instantiate library: {}'.format(e))
        l = None

    globals()['root_' + args.subcommand](args, l, rc)


def root_makemigration(args, l, rc):
    from ambry.orm.database import create_migration_template
    file_name = create_migration_template(args.migration_name)
    print('New empty migration created. Now populate {} with appropriate sql.'.format(file_name))


def root_ckan_export(args, library, run_config):
    from ambry.orm.exc import NotFoundError
    from ambry.exporters.ckan import export, is_exported, UnpublishedAccessError
    try:
        bundle = library.bundle(args.dvid)
        if not args.force and is_exported(bundle):
            print('{} dataset is already exported. Update is not implemented!'.format(args.dvid))
            exit(1)
        else:
            try:
                export(bundle, force=args.force, force_restricted=args.debug_force_restricted)
            except UnpublishedAccessError:
                print('Did not publish because dataset access ({}) restricts publishing.'
                      .format(bundle.config.metadata.about.access))
                exit(1)
            print('{} dataset successfully exported to CKAN.'.format(args.dvid))
    except NotFoundError:
        print('Dataset with {} vid not found.'.format(args.dvid))
        exit(1)


def root_list(args, l, rc):
    from tabulate import tabulate
    import json

    if args.fields:
        header = list(str(e).strip() for e in args.fields.split(','))

        display_header = len(args.fields) > 1

    elif not args.partitions:
        display_header = True
        header = ['vid', 'vname', 'state', 'about.title']
    else:
        header = ['vid', 'vname', 'state', 'table']

    records = []

    if args.term and '='in args.term:
        search_key, search_value = args.term.split('=')
        args.term = None
    else:
        search_key, search_value = None, None

    for b in l.bundles:

        if search_key:
            d = dict(b.metadata.kv)
            v = d.get(search_key,None)
            if v and search_value and v.strip() == search_value.strip():
                records.append(b.field_row(header))

        elif not args.partitions:
            records.append(b.field_row(header))
        else:
            for p in b.partitions:
                records.append


    if args.sort:
        idx = header.index(args.sort)
        records = sorted(records, key=lambda r: r[idx])

    if args.term:

        matched_records = []

        for r in records:
            if args.term in ' '.join(str(e) for e in r):
                matched_records.append(r)

        records = matched_records

    if args.tab:
        for row in records:
            print('\t'.join(str(e) for e in row))
    elif args.json:

        rows = {}

        for row in records:
            rows[row[0]] = dict(list(zip(header, row)))

        print(json.dumps(rows))

    elif display_header:
        print(tabulate(records, headers=header))
    else:
        for row in records:
            print ' '.join(row)


def root_info(args, l, rc):
    from ..cli import prt
    from ..dbexceptions import ConfigurationError
    from tabulate import tabulate

    import ambry

    prt('Version:   {}', ambry._meta.__version__)
    prt('Root dir:  {}', rc.library.filesystem_root)

    try:
        if l.filesystem.source():
            prt('Source :   {}', l.filesystem.source())
    except (ConfigurationError, AttributeError) as e:
        prt('Source :   No source directory')

    prt('Configs:   {}', [e[0] for e in rc.loaded])
    prt('Accounts:  {}', rc.accounts.loaded[0])
    if l:
        prt('Library:   {}', l.database.dsn)
        prt('Remotes:   {}', ', '.join([str(r) for r in l.remotes]) if l.remotes else '')
    else:
        prt('No library defined!')

    if args.configs:
        ds = l.database.root_dataset
        prt("Configs:")
        records = []
        for config in ds.configs:
            # Can't use prt() b/c it tries to format the {} in the config.value
            records.append((config.dotted_key,config.value))

        print tabulate(sorted(records, key=lambda e: e[0]), headers=['key','value'])


def root_sync(args, l, config):
    """Sync with the remote. For more options, use library sync
    """

    l.logger.info('args: %s' % args)

    for r in l.remotes:
        prt('Sync with remote {}', r)
        l.sync_remote(r)


def root_search(args, l, rc):

    if args.reindex:
        def tick(message):
            """Writes a tick to the stdout, without a space or newline."""
            import sys

            sys.stdout.write("\033[K{}\r".format(message))
            sys.stdout.flush()

        l.search.index_library_datasets(tick)
        return

    terms = ' '.join(args.terms)
    print(terms)

    results = l.search.search(terms)

    for r in results:
        print(r.vid, r.bundle.metadata.about.title)
        for p in r.partition_records:
            if p:
                print('    ', p.vid, p.vname)


def root_doc(args, l, rc):

    from ambry.ui import app, app_config
    import os

    import logging
    from logging import FileHandler
    import webbrowser

    app_config['port'] = args.port if args.port else 8085

    cache_dir = l.filesystem.logs()

    file_handler = FileHandler(os.path.join(cache_dir, 'web.log'))
    file_handler.setLevel(logging.WARNING)
    app.logger.addHandler(file_handler)

    print('Serving documentation for cache: ', cache_dir)

    url = 'http://localhost:{}/'.format(app_config['port'])

    if not args.debug:
        # Don't open the browser on debugging, or it will re-open on every
        # application reload
        webbrowser.open(url)
    else:
        print('Running at: {}'.format(url))

    app.run(host=app_config['host'], port=int(app_config['port']), debug=args.debug)


def root_remove(args, l, rc):

    b = l.bundle(args.term)

    fqname = b.identity.fqname

    l.remove(b)

    prt('Removed {}'.format(fqname))


def root_import(args, l, rc):
    import yaml
    from fs.opener import fsopendir
    from . import err
    from ambry.orm.exc import NotFoundError
    import os

    fs = fsopendir(args.term[0])

    for f in fs.walkfiles(wildcard='bundle.yaml'):

        prt("Visiting {}".format(f))
        config = yaml.load(fs.getcontents(f))

        if not config:
            err("Failed to get a valid bundle configuration from '{}'".format(f))

        bid = config['identity']['id']

        try:
            b = l.bundle(bid)

            if not args.force:
                prt('Skipping existing  bundle: {}'.format(b.identity.fqname))
                continue

        except NotFoundError:
            b = None

        if not b:
            b = l.new_from_bundle_config(config)
            prt('Loading bundle: {}'.format(b.identity.fqname))
        else:
            prt('Loading existing bundle: {}'.format(b.identity.fqname))

        b.set_file_system(source_url=os.path.dirname(fs.getsyspath(f)))

        b.sync_in()

        if args.detach:
            b.set_file_system(source_url=None)




def root_docker(args, l, rc):
    import os

    if args.init:
        return root_docker_init(args, l, rc)
    elif args.shell:
        return root_docker_shell(args, l, rc)


def root_docker_init(args, l, rc):
    """Initialize a new docker volumes and database container, and report the database DSNs"""

    from docker.errors import NotFound, NullResource
    import string
    import random
    from ambry.util import parse_url_to_dict
    from docker.utils import kwargs_from_env
    from . import fatal, docker_client

    client = docker_client()

    def id_generator(size=12, chars=string.ascii_lowercase + string.digits):
        return ''.join(random.choice(chars) for _ in range(size))

    # Check if the postgres image exists.

    postgres_image = 'civicknowledge/postgres'

    try:
        inspect = client.inspect_image(postgres_image)
    except NotFound:
        fatal(('Database image {i} not in docker. Run \'python setup.py docker -D\' or '
               ' \'docker pull {i}\'').format(i=postgres_image))


    volumes_image = 'cogniteev/echo'

    try:
        inspect = client.inspect_image(volumes_image)
    except NotFound:
        prt('Pulling image for volumns container: {}'.format(volumes_image))
        client.pull(volumes_image)


    # Assume that the database host IP is also the docker host IP. This usually be true
    # externally to the docker host, and internally, we'll alter the host:port to
    # 'db' anyway.
    db_host_ip = parse_url_to_dict(kwargs_from_env()['base_url'])['netloc'].split(':',1)[0]

    try:
        d = parse_url_to_dict(l.database.dsn)
    except AttributeError:
        d = {'query':''}

    if 'docker' not in d['query'] or args.new:
        username = id_generator()
        password = id_generator()
        database = id_generator()
    else:
        username = d['username']
        password = d['password']
        database = d['path'].strip('/')

    volumes_c = 'ambry_volumes_{}'.format(username)
    db_c = 'ambry_db_{}'.format(username)

    #
    # Create the volume container
    #

    try:
        inspect = client.inspect_container(volumes_c)
        prt('Found volume container {}'.format(volumes_c))
    except NotFound:
        prt('Creating volume container {}'.format(volumes_c))

        r = client.create_container(
            name=volumes_c,
            image=volumes_image,
            volumes=['/var/ambry', '/var/backups'],
            host_config = client.create_host_config()
        )

    #
    # Create the database container
    #

    try:
        inspect = client.inspect_container(db_c)
        prt('Found db container {}'.format(db_c))
    except NotFound:
        prt('Creating db container {}'.format(db_c))
        kwargs = dict(
            name=db_c,
            image=postgres_image,
            volumes=['/var/ambry', '/var/backups'],
            ports=[5432],
            environment={
                'ENCODING': 'UTF8',
                'BACKUP_ENABLED': 'true',
                'BACKUP_FREQUENCY': 'daily',
                'BACKUP_EMAIL': 'eric@busboom.org',
                'USER': username,
                'PASSWORD': password,
                'SCHEMA': database,
                'POSTGIS': 'true'
            },
            host_config=client.create_host_config(
                volumes_from=[volumes_c],
                port_bindings={5432: ('0.0.0.0',)}
            )
        )

        r = client.create_container(**kwargs)

        client.start(r['Id'])

        inspect = client.inspect_container(r['Id'])

    port =  inspect['NetworkSettings']['Ports']['5432/tcp'][0]['HostPort']

    dsn = 'postgres://{username}:{password}@{host}:{port}/{database}?docker'.format(
            username=username, password=password, database=database, host=db_host_ip, port=port)

    if l and l.database.dsn != dsn:
        prt("Set the library.database configuration to this DSN:")
        prt(dsn)

def root_docker_shell(args, l, rc):
    """Run a shell in an Ambry builder image, on the current docker host"""

    from . import docker_client, get_docker_links
    from docker.errors import NotFound, NullResource
    import os

    client = docker_client()

    username, dsn, volumes_c, db_c, envs = get_docker_links(l)

    shell_name = 'ambry_shell_{}'.format(username)

    # Check if the  image exists.

    image = 'civicknowledge/ambry'

    try:
        inspect = client.inspect_image(image)
    except NotFound:
        fatal(('Database image {i} not in docker. Run \'python setup.py docker -b\' or '
               ' \'docker pull {i}\'').format(i=_image))

    try:
        inspect = client.inspect_container(shell_name)
        running = inspect['State']['Running']
        exists = True
    except NotFound as e:
        running = False
        exists = False

    # If no one is using is, clear it out.
    if exists and not running:
        prt('Container {} exists but is not running; recreate it from latest image'.format(shell_name))
        client.remove_container(shell_name)
        exists = False

    if not running:

        kwargs = dict(
            name=shell_name,
            image=image,
            detach=False,
            tty=True,
            stdin_open=True,
            environment=envs,
            host_config=client.create_host_config(
                volumes_from=[volumes_c],
                port_bindings={5432: ('0.0.0.0',)}
            ),
            command='/bin/bash'
        )

        prt('Starting container with image {} '.format(image))

        r = client.create_container(**kwargs)

        while True:
            try:
                inspect = client.inspect_container(r['Id'])
                break
            except NotFound:
                prt('Waiting for container to be created')

        prt('Starting {}'.format(inspect['Id']))
        os.execlp('docker', 'docker', 'start', '-a', '-i', inspect['Id'])

    else:

        prt("Exec new shell on running container")
        os.execlp('docker', 'docker', 'exec', '-t', '-i', inspect['Id'], '/bin/bash')
