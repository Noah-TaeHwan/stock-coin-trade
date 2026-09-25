# 태그를 버전까지 고정한다(2026-09-25 기준 nginx:alpine과 같은 1.31.6).
FROM nginx:1.31.6-alpine

COPY frontend/ /usr/share/nginx/html/
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY docker/nginx-security-headers.conf /etc/nginx/snippets/security-headers.conf

EXPOSE 80
