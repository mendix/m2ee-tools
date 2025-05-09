## ** M2EE-tools only support Debian 10 (buster) and Mendix Runtime versions 7-9. Further version support will not be added anymore. **

# Installing a Mendix server based on GNU/Linux

This documentation describes the installation and configuration of the Mendix Runtime software on a system running GNU/Linux. This howto assumes the reader has decent skills concerning administering GNU/Linux server environments.

The best supported operating system to use in order to run a Mendix server, is Debian GNU/Linux. The simple reason for this is that Debian has always been used heavily as operating system at Mendix. When using Debian, we of course recommend to always use the current stable release that is fully supported by the Debian project. Mendix provides readily available Debian packages to help set up the server. Installing them will be covered in the next pages of this documentation.

Installation on other linux based distributions or unix-like operating systems is certainly possible, but it's not supported with readily available software packages to be installed using the operating system package manager. In practice, the actual difference is that the system administrator will have the responsibility to keep the software updated, instead of automatically getting updates using the packaging system.

In order to set up an environment to run Mendix applications, you will need to install the Mendix software, together with some dependencies, provided by your operating system. For each Mendix application that will be run, a separate user account and project folder on the filesystem is required.

## Available documentation:

 * [Introduction and overview](introduction.md)
 * [Installing the Mendix software](install-1.md)
 * [Preparing an application deployment location](install-2.md)
 * [Configuring the application](configure.md)
 * [Using a webserver as reverse http proxy to provide ssl encryption, static content and static and dynamic compression. An example: nginx](nginx.md)
 * [Monitoring a Mendix application process with Munin](munin.md)
 * [Monitoring a Mendix application process using Nagios](nagios.md)
 * [Check the security of your installation using this checklist](security.md)

