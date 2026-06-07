FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html.template
COPY app.js /usr/share/nginx/html/app.js

ENV NO_AUTH=false

CMD ["/bin/sh", "-c", "envsubst '$NO_AUTH' < /usr/share/nginx/html/index.html.template > /usr/share/nginx/html/index.html && nginx -g 'daemon off;'"]
