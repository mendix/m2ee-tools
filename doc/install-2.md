[Back: Installing the Mendix software](install-1.md)

# Preparing a deployment location

It is highly recommended to create a separate user per mendix application you want to run on the application server. Using an example user myapp we create an application deployment environment:

    example.mendix.net:~ 0-# adduser --disabled-password --gecos "My First Application,,," myapp
    Adding user `myapp' ...
    Adding new group `myapp' (1001) ...
    Adding new user `myapp' (1001) with group `myapp' ...
    Creating home directory `/home/myapp' ...
    Copying files from `/etc/skel' ...
    example.mendix.net:~ 0-#

Choose a filesystem location to organize application deployments, and create a new directory for 'My First Application'. In this example, we'll use the location `/srv/mendix/`:

    example.mendix.net:~ 0-# mkdir -p /srv/mendix/myapp
    example.mendix.net:~ 0-# cd /srv/mendix/myapp
    example.mendix.net:/srv/mendix/myapp 0-# mkdir runtimes/ web/ model/ data/ data/database data/files data/model-upload data/tmp
    example.mendix.net:/srv/mendix/myapp 0-# chown myapp:myapp * -R
    example.mendix.net:/srv/mendix/myapp 0-# chmod 700 model/ data/
    example.mendix.net:/srv/mendix/myapp 0-# tree
    .
    ├── data
    │   ├── database
    │   ├── files
    │   ├── model-upload
    │   └── tmp
    ├── model
    ├── runtimes
    └── web

    7 directories, 0 files
    #

- - -

[Next: Configuring the application](configure.md)
