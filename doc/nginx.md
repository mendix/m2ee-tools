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

## A configuration example

Some basic pieces of nginx configuration to serve up a mendix application could look like this:

    http {
        # See the section about gzip below for more info about these lines
        gzip on;
        gzip_static on;
        gzip_proxied any;
        gzip_types application/json;

        proxy_read_timeout 15m;
        proxy_http_version 1.1;

        # Provide some extra information to the Mendix Runtime about the
        # end user connection
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # This is an important one, make sure to hint the mendix runtime
        # whether https is used to the end user, so the secure flag on
        # session cookies gets set (Mendix >= 3.3.3, 4.2.2)
        proxy_set_header X-Forwarded-Scheme $scheme;

        # Restrict usage of IFrames
        add_header X-Frame-Options SAMEORIGIN;
        # Tell the browser to always use https
        add_header Strict-Transport-Security "max-age=31536000;";

        # Random bots scanning the internet end up here
        # Also see the section about the catch-all server declaration below
        server {
            listen [::]:443 default_server ipv6only=on ssl;
            listen 0.0.0.0:443 default_server ssl;
            server_name _;
            ssl_certificate /etc/ssl/nginx/dummy.crt;
            ssl_certificate_key /etc/ssl/nginx/dummy.key;
            return 503;
        }

        # When specifically accessing our application URL we end up here
        upstream somecust {
            server 127.0.0.1:8000;
            keepalive 8;
        }
        server {
            listen [::]:443;
            listen 0.0.0.0:443;
            server_name some-customer.mendix.com;
            ssl_certificate /etc/ssl/nginx/some-customer.crt;
            ssl_certificate_key /etc/ssl/nginx/some-customer.key;

            # All static content is served directly from the project location
            root /srv/mendix/somecust/web/;

            location / {
                # Instruct the browser to never cache the first login page, since
                # it would prevent us from seeing updates after a change
                if ($request_uri ~ ^/((index[\w-]*|login)\.html)?$) {
                    add_header Cache-Control "no-cache";
                    add_header X-Frame-Options "SAMEORIGIN";
                }
                # Agressively cache these files, since they use a cache bust
                if ($request_uri ~ ^/(.*\.(css|js)|(css|img|js|lib|mxclientsystem|pages|widgets)/.*)\?[0-9]+$) {
                    expires 1y;
                }
                # By default first look if the requests points to static content.
                # If not, proxy it to the runtime process.
                try_files $uri $uri/ @runtime;
            }
            location @runtime {
                proxy_pass http://somecust;
                allow all;
            }
            location = /file {
                proxy_pass http://somecust;
                # Be generous about the size of things that can be uploaded
                client_max_body_size 1G;
                # Never buffer uploads or downloads, directly stream them
                proxy_buffering off;
                proxy_request_buffering off;
            }
            location = /xas/ {
                proxy_pass http://somecust;
            }
            # Never expose the -doc paths on a public application instance
            location ~ ^/\w+-doc/ {
                deny all;
            }
            # Apply an IP Filter restriction on some path, regardless of the fact we're serving
            # static or dynamic content
            location /hello/ {
                try_files $uri $uri/ @runtime;
                allow 198.51.100.0/24;
                allow 2001:db8:4:3770::/120;
                deny all;
            }
        }
    }

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

Another use for a catch-all server declaration is to listen on a non-ssl http port, redirecting the browser to the same url on https. This is a convenience option for users, who do not have to type the https:// explicitely the first time when trying to reach an application. When the Strict-Transport-Security setting is also used, as seen above, this redirect will only be used exactly once. Even when not specifying https the second time, the browser will be instructed to always use it nonetheless.

    server {
        listen [::]:80 default ipv6only=on;
        listen 0.0.0.0:80 default;
        server_name _;
        return 301 https://$host$request_uri;
    }

    server {
        listen [::]:443 default_server ipv6only=on ssl;
        listen 0.0.0.0:443 default_server ssl;
        server_name _;
        ssl_certificate /etc/ssl/nginx/dummy.crt;
        ssl_certificate_key /etc/ssl/nginx/dummy.key;
        return 503;
    }

- - -

[Back to overview](README.md)
