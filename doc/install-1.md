[Back: Introduction and overview](introduction.md)

# Installing the Mendix software

To be able to run Mendix applications, the following pieces of software need to be installed:

 * Mendix Deployment tools (m2ee-tools), a helper script to manage deployments and application processes.
 * The Java Runtime Environment.

This page describes installation instructions for Debian and RHEL/Centos in case a system wide installation is done using provided software packages. If you want to do a custom installation on another operating system or an installation without the need to use the administrator (root) account, additionally have a look at the documentation to do a [local m2ee-tools and mendix runtime installation](non-root-install.md).

## Deployment Tools for Debian

The deployment tools, written in python are available in a public apt repository. When using Debian Jessie this repository can be added to your apt sources as follows:

    deb http://packages.mendix.com/platform/debian/ jessie main contrib non-free

### GPG keyring

In order to trust this repository, you have to import the GPG keys used by Mendix to sign the Release file.

Step 1: Install the current public key manually, using https to download it:

    # wget -q -O - https://packages.mendix.com/mendix-debian-archive-key.asc | apt-key add -
    OK

Step 2: Install the `debian-mendix-keyring` package from the Mendix repository. Installing this package makes sure that you will automatically receive new public keys when Mendix does a key-rollover to a new key.

    # apt-get install debian-mendix-keyring
    Reading package lists... Done
    Building dependency tree
    Reading state information... Done
    The following NEW packages will be installed:
      debian-mendix-keyring
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
    The following extra packages will be installed:
      python-httplib2 python-m2ee unzip
    Suggested packages:
      postgresql-client zip
    The following NEW packages will be installed:
      m2ee-tools python-httplib2 python-m2ee unzip
    0 upgraded, 4 newly installed, 0 to remove and 0 not upgraded.
    Need to get 336 kB of archives.
    After this operation, 826 kB of additional disk space will be used.
    Do you want to continue [Y/n]?
    [...]

## Deployment Tools for RHEL / Centos

An RPM-version of the deployment tools package can be found at [https://packages.mendix.com/platform/rpm/](https://packages.mendix.com/platform/rpm/)

This package has dependencies on a few small python libraries, of which part of them aren't available in the base distribution of RedHat / Centos. During development and testing the following packages were used from EPEL:

 * [PyYAML-3.10-3.el6.x86_64](http://dl.fedoraproject.org/pub/epel/6/x86_64/repoview/PyYAML.html)
 * [libyaml-0.1.3-1.el6.x86_64](http://dl.fedoraproject.org/pub/epel/6/x86_64/repoview/libyaml.html)
 * [python-httplib2-0.7.4-6.el6.noarch](http://dl.fedoraproject.org/pub/epel/6/x86_64/repoview/python-httplib2.html)

If slightly newer packages than these ones are available at EPEL, don't hesitate to use them.

## Oracle Java JRE or OpenJDK JRE on Debian

In order to run the mendix server, you also need the Oracle Java JRE or the OpenJDK JRE (supported when using Mendix 4.2.0+). Which Java JRE to use depends on the version of the Mendix Business Modeler you're using to create the application that needs to run on your new server.

 * Mendix 3 and 4.0 use JRE 6
 * From Mendix 4.1 on it can use either JRE 6 or 7. Using 7 is recommended.
 * Mendix 5 requires using JRE 7

When using Debian, the OpenJDK JRE is provided by the [openjdk-7-jre-headless](https://packages.debian.org/openjdk-7-jre-headless) package.

Thanks to Oracle, OS Distributions cannot any longer redistribute the Oracle JRE. If you want to use the Oracle JVM, use java-package to create Debian packages of the Oracle JVM yourself. NEVER directly install the self-extracting .bin installer from Oracle on a Debian system. See the [Java](http://wiki.debian.org/Java) and [JavaPackage](http://wiki.debian.org/JavaPackage) pages in the Debian Wiki for more information.

If you have multiple JRE packages installed, make sure you have the preferred one by default in your path. Use update-java-alternatives to choose which java binary will be the default on your search path.
Oracle JRE or OpenJDK JRE on RHEL / Centos

The Oracle JRE is available as rpm at Oracle, and the OpenJDK JRE seems to be available in the default repositories, installable using yum.

## System-wide configuration of m2ee-tools

The m2ee-tools package provides a template configuration file for system-wide configuration, installed in the examples directory in the package documentation under /usr/share/doc. This file is called `system-wide-m2ee.yaml` and can be placed at `/etc/m2ee/m2ee.yaml`.

Instead of using this system-wide configuration file, you can specify these options in the application-specific configuration as well, which will override or replace the system-wide configuration.

- - -

[Next: Preparing an application deployment location](install-2.md)
