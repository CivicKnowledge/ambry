

To build the docker container, run, from the root of the distribution: 

    $ python setup.py docker
    
This will create a docker container tagged 'civicknowledge/ambry' using the version of the code in the distribution.

To run the container:

    $ docker run --rm -t -i civicknowledge/ambry 
    
The result will be a shell prompt, with ambry installed, using a local Sqlite database. 

If you want to run another database, use `-e AMBRY_DB`

    $ docker run --rm -t -i -e AMBRY_DB=postgres://<user>:<pass>>@<host>:<port>/ambry civicknowledge/ambry

The AMBRY_DB value can be any valid Ambry database DSN. 