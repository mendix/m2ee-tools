# Using Nginx as reverse proxy

This section describes an example of configuring the Nginx web server as reverse proxy between the web browser and a Mendix application server process.

## Why?

 * Serving static content (javascript, css, forms, widgets...)
 * Managing lots of idle browser connections
 * Handling SSL connections
 * Store-and-forward caching of reponses to free up JVM resources while sending a response to the web browser over a slow connection.
 * Handling gzip compression for static and dynamic content

## How?

It's up to you, but here's a simple example, using a single host, connected to the public internet, on which both the web server and application server run. The hostname is example.mendix.net, which has both an IPv4 and an IPv6 address. On this server, we want to run an application with url `https://some-customer.mendix.com`, so we CNAME the application name to the server:

    ~$ host some-customer.mendix.com
    some-customer.mendix.com is an alias for example.mendix.net.
    example.mendix.net has address 192.0.2.66
    example.mendix.net has IPv6 address 2001:db8::31:3024:37:487

Please refer to the official documentation at http://wiki.nginx.org/ for more information about configuration details mentioned below.

## Static and dynamic content

A basic nginx server section to serve up a mendix application could look like this:

    server {
        listen [::]:443;
        listen 0.0.0.0:443;
        ssl_certificate /etc/ssl/nginx/ssl_certificate.pem;
        ssl_certificate_key /etc/ssl/nginx/ssl_certificate.key;

        server_name some-customer.mendix.com;

        # all static content is served directly from the project location
        root /srv/mendix/somecust/web/;

        # locations matching the exact string /xas/ are requests for the main
        # client JSON API, so we send them to the application http port
        location = /xas/ {
            proxy_pass http://127.0.0.1:8000;
        }
        # /file is used for uploading/downloading files into the application,
        # which get registered in the application as FileDocument objects
        location = /file {
            proxy_pass http://127.0.0.1:8000;
            client_max_body_size 512M;
        }
        # optionally, additional sub-urls can be proxied to the application, like
        # /link/ when using the deeplink widget, which registers a request handler
        # on /link/
        # note this one does not have the equals sign after location, because the
        # link widget uses urls like /link/blahblah, and not only /link/
        location /link/ {
            proxy_pass http://127.0.0.1:8000;
        }
        # same story for /ws/, when exposing web services in the application
        # or... use a regular expression to fit them both in one line:
        #location ~ ^/(link|ws)/ {
        #   proxy_pass http://127.0.0.1:8000;
        #}

        # Provide some extra information to the Mendix Runtime about the
        # end user connection
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

        # Restrict using of IFrames
        proxy_set_header X-Frame-Options SAMEORIGIN;

        # This is an important one, make sure to hint the mendix runtime
        # whether https is used to the end user, so the secure flag on
        # session cookies gets set (Mendix >= 3.3.3,4.2.2)
        proxy_set_header X-Forwarded-Scheme $scheme;
    }

When using this example literally for an application on which you want to call a web service, nginx will start looking for a directory named `/ws/` inside the web folder of the project, because the sub url `/ws/` does not get proxied to the application port. So, when getting unexpected 404 not found results on requests, a missing `proxy_pass` might be the cause.

## Set the X-Forwarded-Scheme header!

Pay close attention to the `proxy_set_header` line that adds `X-Forwarded-Scheme`. If you omit this header (with value 'https') when using https between the end users browser and nginx, the mendix runtime will not know about the use of https and will not set the secure flag on cookies, which means the web browser of the end user will also send cookies when the end user tries to connect to the application over plain http. Because it's common practice to provide a redirect to https on the default http port as convenience method for users typing the application url without explicit https, this means cookies are sent unencrypted when the user does so. Be sure to use at least Mendix version 3.3.3 or 4.2.2, because earlier versions did not correctly set the secure cookie flag.

## Using gzip compression

To save bandwith and speed up sending information to the web browser, it is advised to use gzip compression for HTTP content.

The Mendix application server software provides gzipped versions of static content by default, in addition to the full-blown files. Whenever a web browser is capable of receiving compressed content, the Nginx web browser can simply stream the pre-compressed .gz versions to the web browser.

Dynamic content, which are responses from the Mendix application server itself, can only be compressed on the fly. These http responses are of type application/json, and are often very suitable for compression.

The following nginx configuration (which can be placed inside the http configuration section) defines this behaviour, using pre-compressed files and compression on the fly for dynamic content: :

    gzip on;
    # will gzip json responses (from /xas/) on the fly
    gzip_proxied any;
    gzip_types application/json;
    # will automagically present the .gz files
    gzip_static on;

## Using a catch-all server declaration

When your server does not have one yet, perferably configure a default catch-all server declaration, which will match all incoming requests not explicitely mentioning the application url name (e.g. some-customer.mendix.com) in the Host header of the request. This can be useful to, by default, block requests from random scripts that are connecting to the plain IP address or canonical host name (example.mendix.net in this case).

Another use for a catch-all server declaration is to listen on a non-ssl http port, redirecting the browser to the same url on https. This is a convenience option for users, who do not have to type the https:// explicitely when trying to reach an application.

    server {
        listen [::]:80 default ipv6only=on;
        listen 0.0.0.0:80 default;
        server_name _;
        return 301 https://$host$request_uri;
    }

    server {
        listen [::]:443 default ipv6only=on ssl;
        listen 0.0.0.0:443 default ssl;
        server_name _;
        ssl_certificate /etc/ssl/mendix/ssl_certificate.pem;
        ssl_certificate_key /etc/ssl/mendix/ssl_certificate.key;
        return 503;
    }

- - -

[Back to overview](README.md)
