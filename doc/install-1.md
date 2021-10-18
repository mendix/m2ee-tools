[Back: Introduction and overview](introduction.md)

# Installing the Mendix software

To be able to run Mendix applications, the following pieces of software need to be installed:

 * Mendix Deployment tools (m2ee-tools), a helper script to manage deployments and application processes.
 * The Java Runtime Environment.

This page describes installation instructions for Debian in case a system wide installation is done using provided software packages. If you want to do a custom installation on another operating system or an installation without the need to use the administrator (root) account, additionally have a look at the documentation to do a [local m2ee-tools and mendix runtime installation](non-root-install.md).

## Deployment Tools for Debian

The deployment tools, written in python are available in a public apt repository. When e.g. using Debian Buster this repository can be added to your apt sources as follows:

    deb http://packages.mendix.com/platform/debian/ buster main contrib non-free

### GPG keyring

In order to trust this repository, you have to import the GPG keys used by Mendix to sign the Release file.

Step 1: Install the current public key manually, using https to download it:

    # wget -q -O - https://packages.mendix.com/mendix-debian-archive-key.asc | apt-key add -
    OK

Step 2: Fetch the package lists. This should succeed without any GPG verification error now.

    # apt-get update
    [...]
    Get:5 http://packages.mendix.com/platform/debian buster InRelease [10.9 kB]
    [...]

Step 3: Install the `debian-mendix-archive-keyring` package from the Mendix repository. Installing this package makes sure that you will automatically receive new public keys when Mendix does a key-rollover to a new key.

    # apt-get install debian-mendix-archive-keyring
    Reading package lists... Done
    Building dependency tree
    Reading state information... Done
    The following NEW packages will be installed:
      debian-mendix-archive-keyring
    0 upgraded, 1 newly installed, 0 to remove and 0 not upgraded.
    Need to get 6,472 B of archives.
    After this operation, 53.2 kB of additional disk space will be used.
    [...]

### Install!

Now you can install m2ee-tools:

    # apt-get install m2ee-tools
    Reading package lists... Done
    Building dependency tree
    Reading state information... Done
    The following additional packages will be installed:
      python-httplib2 python-m2ee python-yaml
    The following NEW packages will be installed:
      m2ee-tools python-httplib2 python-m2ee python-yaml
    0 upgraded, 5 newly installed, 0 to remove and 0 not upgraded.
    Need to get 691 kB of archives.
    After this operation, 1,743 kB of additional disk space will be used.
    Do you want to continue? [Y/n]
    [...]

## Oracle Java JRE or OpenJDK JRE on Debian

In order to run the Mendix server, you also need an OpenJDK or Oracle Java JRE runtime environment. Which Java JRE to use depends on the version of the Mendix Business Modeler you're using to create the application that needs to run on your new server.

 * Mendix 6 and 7 need JRE 8
 * From Mendix 8 on, a recent OpenJDK version should be used.

For Debian, the OpenJDK JRE that is packaged in Debian can be used.

If you have multiple JRE packages installed, make sure you either have the prefered one by default in your path. Use update-java-alternatives to choose which java binary will be the default on your search path. Alternatively, use the `javabin` option in the m2ee configuration file to specify the exact location of the java executable. More explanation about the configuration file is available in the next documentation pages.

- - -

[Next: Preparing an application deployment location](install-2.md)
