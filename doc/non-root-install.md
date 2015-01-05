# Manual installation of m2ee-tools

Besides using m2ee-tools packages, e.g. for Debian and RHEL, it is also possible to do a manual installation of the Mendix software under a single user account without needing root access.

Example situation in which this might be desirable are:

 * Doing a test installation on your workstation
 * Installing an application on a server where you aren't allowed to use the system package manager, or where using packages from other sources than the 'official' vendor repository is not allowed.
 * Installing on an operating system that has no available m2ee-tools packages (e.g. Solaris).

In these cases, it is often possible to get the Java JRE and a web server installed via the official OS vendor repositories, just not the Mendix part of the stack.

## Create initial directory structure

Create a simple directory structure where all software and the application will be placed:

    example@example.mendix.net:~/mendix 1-$ tree
    .
    ├── application
    └── m2ee-tools
        └── thirdparty

 * The application directory will hold the application specific files, as described on the [application deployment location](install-2.md).
 * The m2ee-tools directory will contain the python deployment tools, together with some small extra third party libraries, in case they're not bundled with your operating system.

## m2ee-tools

Either download the latest m2ee-tools release (choose a vX.Y.Z tag, not a debian/X.Y.Z one) from [the releases page](https://github.com/mendix/m2ee-tools/releases) and extract it in the m2ee-tools directory or directly clone the [m2ee-tools git repository from github](https://github.com/mendix/m2ee-tools.git) and checkout a release tag. Also, when choosing a version (tag), choose one with the vX.Y.Z format (e.g. v0.5.10), and not the `debian/X.Y.Z`. The debian tags are created when doing the additional packaging work to create debian packages.

## PyYAML

At [http://pyyaml.org/wiki/PyYAML](http://pyyaml.org/wiki/PyYAML), or [a mirror at Mendix](http://packages.mendix.com/platform/mirror/thirdparty), a tar.gz of PyYAML is available. Just put the tar.gz into the m2ee-tools/thirdparty directory and extract it.

There is no need to compile C extensions that are available for PyYAML. The pure python implementation is perfectly suitable for the small amount this module has to do, which is only parsing a configuration file.

## Httplib2

At [http://code.google.com/p/httplib2/](http://code.google.com/p/httplib2/), or [a mirror at Mendix](http://packages.mendix.com/platform/mirror/thirdparty), get the tar.gz, and extract it in the m2ee-tools/thirdparty directory.

## Simplejson (only needed with Python 2.5)

When using python 2.5, you'll need the simplejson module from [http://pypi.python.org/pypi/simplejson/](http://pypi.python.org/pypi/simplejson/), or [a mirror at Mendix](http://packages.mendix.com/platform/mirror/thirdparty). In Python 2.6, this module has been added to the standard set of libraries included. Also, extract the tar.gz in the m2ee-tools/thirdparty directory.

## Finishing up...

After gathering all software together, and creating the application folder hierarchy, your mendix directory might look like this example:

    .
    ├── application/
    │   ├── data/
    │   │   ├── database/
    │   │   ├── files/
    │   │   ├── model-upload/
    │   │   └── tmp/
    │   ├── model/
    │   ├── runtimes/
    │   └── web/
    └── m2ee-tools/
        ├── 0.5.10/
        └── thirdparty/
            ├── httplib2-0.7.7/
            └── PyYAML-3.10/

## Some aliases and configuration tweaks

There's some final polishing needed before we can just issue a `m2ee` on the command line to start the deployment helper using the right m2ee-tools version, the right application etc...

First off all, create a `m2ee.yaml` configuration file by concatenating the `system-wide-m2ee.yaml` and `user-specific-m2ee.yaml` files from the examples directory of the latest m2ee-tools version you have. The default location where m2ee searches for this configuration file is `~/.m2ee/m2ee.yaml`. If you do want to place this configuration file inside the application directory instead, then just create some place to store it, preferably under `application/data/`. Have a good look at the example configuration file, just like described at the page [Configuring the application](configure.md).

To be able to just start m2ee-tools using a simple `m2ee` alias, we can set the python library path using a shell variable, so the third party modules will be found, and we can alias the m2ee command to the actual location of the version we want to use right now. If the configuration file is not located at `~/.m2ee/m2ee.yaml`, just add the right location using the `-c` option.

    # put something like this in your ~/.bashrc
    export PYTHONPATH="/home/example/mendix/m2ee-tools/thirdparty/httplib2-0.7.7/python2/:\
    /home/example/mendix/m2ee-tools/thirdparty/PyYAML-3.10/lib/"
    alias m2ee="/home/example/mendix/m2ee-tools/0.5.10/src/m2ee.py \
    -c /home/example/mendix/application/data/config/m2ee.yaml"

By altering these paths and the alias, you can easily switch between m2ee-tools versions and versions of third party libraries. Or, of course, use some symlinks instead.

If your Java JRE installation does not place the java executable in /usr/bin, you want to set a custom PATH to be used when m2ee will start the actual JVM process. Besides the following example configuration snippet, see the full-documented-m2ee.yaml file in the examples directory of the m2ee-tools source for more information on setting or preserving custom environment variables.

    # merge something like this into your m2ee.yaml
    m2ee:
     custom_environment:
      PATH: "/bin:/usr/bin/:/opt/some/weird/jre/version/bin/"

## Further instructions

Next page: [Configuring the application](configure.md)

## Finally...

If you get stuck following these directions, don't hesitate to ask in a support ticket, or on the forum for help. Also it's good to know you can use the -v or -vv options to get more debug and trace information when starting m2ee fails. Have fun!
