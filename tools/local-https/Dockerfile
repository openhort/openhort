FROM nginx:alpine
COPY nginx.conf /etc/nginx/nginx.conf
RUN mkdir -p /etc/nginx/certs
COPY certs/cert.pem /etc/nginx/certs/
COPY certs/key.pem /etc/nginx/certs/
EXPOSE 8950
