[Back: Overview](README.md)

# Introduction and overview

This page tries to provide an overview of the software setup running a custom Mendix server on GNU/Linux. It might help to grasp the full picture before following the rest of the documentation in this section about steps which have to be executed to manually set up a server that runs a Mendix application.

Before starting, I'd highly recommend to ask your local team of Mendix Business Engineers (tm) to give you a demo about how they're using the Mendix Business Modeler to create a working business application.

The following section describes an overview of the parts of the whole setup you'll encounter in the next pages.

                                           (2) MxRuntime
                                        ,------------------.
                               (4) admin                   |
     (1) m2ee-tools  ------------>  port - m2ee admin api  |       _______
                                        |                  |      (       )
                (3) data/   <---------- |  read/write data |      (   D   )
                    model/  <---------- |  read model      |      (   B   )
           ,----->  web/                |                  | <--> (   M   )
           |                   (5) runtime                 |      (   S   )
     (6) nginx ------------------->  port - public api     |      (_______)
           ^                            |  /xas/, /file,   |
           |                            |  /ws/, etc...    |
       end user                         `------------------'

## m2ee-tools

m2ee-tools (1) is the name of a small command line tool, written in python, that helps deploying new application versions which are created by the team that works with the Mendix Business Modeler. This program can start the Mendix Runtime (2) by starting a JVM and pointing it to the right version of the binary (jar) files of tht right Mendix version which need to be available on the system. When the JVM process is started, the m2ee tool connects to the Mendix Runtime to configure it, e.g. by telling it to load a Mendix application model, created with the graphical Mendix Business Modeler, while handling feedback that may occur during startup. The Mendix Runtime is an interpreter, that is responsible of the 'bringing to life' of the designed application.

When the Mendix Runtime is running, the m2ee command line tool can be used to connect back to the Mendix Runtime, issuing commands like setting loglevels, asking how many users are logged in, show currently running actions inside the application, or even telling it to shut down itself.

## The Modeler, Deployment Archives and the project folder

A Mendix application is created using the Mendix Business Modeler and exported to a so-called Deployment Archive. This is a single file containing the complete description about how the application should function. The Deployment Archive can be copied onto the server, after which the m2ee tool can help extracting it, so that the Mendix Runtime can be started using it.

Applications that are made in the Mendix Business Modeler, using the native functionality in the Mendix Platform are also extensible using custom Java code or custom bundled extra libraries. The bytecode class files are part of the Deployment Archive and will be put into the classpath of the Mendix Runtime when starting using the m2ee tool.

Besides the extracted Deployment Archive file, m2ee has its own configuration in a single yaml file, that m2ee will use to properly start and manage the application process. The project folder (3) contains the extracted Deployment Archive file in the model/ and web/ folders, as well as other private data of the application (uploaded files e.a.) in the data/ folder.

## The Mendix Runtime

When started, the Mendix runtime will listen on two different TCP ports, using the HTTP protocol.

The 'admin port' (4) is used by m2ee-tools for administrative commands like sending configuration options, setting loglevels, requesting information about the current status of the application proces, version information, statistics about usage etc... This admin port only provides a simple custom json-rpc style API over HTTP, so there's no visual web-interface or the like present that can be used via a normal web browser. A user interface is provided by the m2ee command line tool. Make sure access to this port is properly firewalled. Only local access is needed.

The 'runtime port' (5) is also a TCP port presenting an HTTP server with json-rpc style API on the main request handler on the /xas/ sub-url. This API is used by the javascript client which runs in the web browser of an end user. Besides this there can be other request handlers listening, to deal with e.g. file upload/downloads on /file or soap webservices on /ws/.

## The web server

The web/ sub-folder in the project folder can be world-readable, so it can be served directly on the root url of the application using a webserver, which can also handle SSL/TLS, and reverse proxy to the Mendix Runtime port. The recommended web server software for use with Mendix is Nginx.

[Next: Installing the Mendix software](install-1.md)
