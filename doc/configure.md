[Back: Preparing an application deployment location](install-2.md)

# Configuring the application

Almost all configuration concerning running the Mendix application is centralized into the file `~/.m2ee/m2ee.yaml`. This file, in yaml format, describes all file locations and runtime settings of the application and will be read by the m2ee program, provided by the m2ee-tools package.

## Configuration

In the home directory of our example user myapp we create the .m2ee settings directory:

    myapp@example.mendix.net:~ 1-$ mkdir .m2ee

The m2ee-tools package provides a template configuration file, installed in the examples directory in the package documentation under `/usr/share/doc`. You can copy this template configuration file, `user-specific-m2ee.yaml`, to `~/.m2ee/m2ee.yaml`.

Take a look at the example `m2ee.yaml` file. This example configuration file consists of several sections with configurable settings. In this howto, we're focusing on the basic settings to get a simple application running.

We can alter a few options to get a fully working configuration file:

 * In the m2ee section:
   - `app_name`: short description of the application
   - `app_base`: path to the project directory of your application
   - `runtime_port`: TCP port we want the application to present itself for end users (when using the modeler, this defaults to port 8080)
   - `runtime_listen_addresses`: by default, the application process only listens on the localhost address. set this option to "\*" if you want to have the public runtime port accessible from other hosts than localhost
   - `admin_port`: a different TCP port, on which the m2ee helper program communicates with the mendix server process when it's running
   - `admin_pass`: a password which protects the administrative interface, running on the admin TCP port. set this password to e.g. a long random string, it's not used manually anywhere
 * In the logging section, edit the logging options if you want to log to a file directly.
 * In the mxruntime section, you can configure your database login host and credentials, microflow constants and scheduled events.

*For more in-depth information about possible configuration settings, have a look at the `full-documented-m2ee.yaml` file in the examples directory.*

## Try it!

Right now, we can start m2ee using the current configuration:

    myapp@example.mendix.net:\~ 1-$ m2ee
    WARNING: /srv/mendix/myapp/model/model.mdp is not a file\!
    INFO: Application Name: My First Application
    INFO: The application process is not running.
    m2ee(myapp):

For testing purpose, I've created a minimal application in the Mendix 4.1.0 modeler, called empty, exported for deployment to empty-4.1.0.mda. I can upload this file into `/srv/mendix/myapp/data/model-upload/` and unpack it using the unpack command:

    myapp@example.mendix.net:/srv/mendix/myapp 1-$ m2ee
    WARNING: /srv/mendix/myapp/model/model.mdp is not a file\!
    INFO: Application Name: My First Application
    INFO: The application process is not running.
    m2ee(myapp): unpack empty-4.1.0.mda
    INFO: The application process is not running.
    INFO: This command will replace the contents of the model/ and web/ locations,
    using the files extracted from the archive
    Continue? (y)es, (n)o? y
    m2ee(myapp):

Now, try to start the application, let it download the Mendix Runtime if it's the first time you start an application with a specific version, create a user and login to the application on http port 8000, as specified in the configuration setting runtime\_port.

    m2ee(myapp): start
    ERROR: It appears that the Mendix Runtime version which has to be used for your application is not present yet.
    INFO: You can try downloading it using the download_runtime command.
    m2ee(myapp): download_runtime
    INFO: Going to download and extract https://download.mendix.com/runtimes/mendix-4.1.0.tar.gz to /srv/mendix/myapp/runtimes
    [...]
    INFO: Successfully downloaded runtime!
    m2ee(myapp): start
    INFO: The application process is not running.
    INFO: Trying to start the MxRuntime...
    ERROR: Main datastore is out-of-sync with domain model! (42 datastore change queries needed)
    Do you want to (v)iew queries, (s)ave them to a file, (e)xecute and save them, or (a)bort: e
    INFO: Saving DDL commands to /srv/mendix/myapp/data/database/20110420_124306_database_commands.sql
    INFO: The MxRuntime is fully started now.
    m2ee(myapp): create_admin_user
    This option will create an administrative user account, using the preset username
    and user role settings. (modeler or m2eerc)
    Type new password for this user:
    Type new password for this user again:
    m2ee(myapp): status
    INFO: The application process is running, the MxRuntime has status: running
    INFO: Logged in users: []
    m2ee(myapp):

Have a look at the `full-documented-m2ee.yaml` configuration file in the examples location for more explanation about possible configuration options you can add to your m2ee.yaml file.

## At reboot cronjob

When for whatever reason the server you're hosting on gets rebooted, you might want to have your Mendix application restarted automatically.  You can do so by adding an at reboot cronjob in your account, which will startup the application again after a reboot:

    myapp@example.mendix.net:~ 1-$ crontab -l
    # m h  dom mon dow   command
    @reboot /usr/bin/m2ee start
    myapp@example.mendix.net:~ 1-$

## License key activation

The `show_license_information` in the interactive m2ee console can be used to display a generated server ID. Using this server ID, a license key can be obtained which can be installed in the application using the `activate_license` m2ee command. Please contact your Mendix account manager or Mendix Support for further instructions about on premise licensing.

[Back to overview](README.md)
