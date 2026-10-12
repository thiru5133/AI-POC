FROM nginx:1.27-alpine
# nginx fills ${HB_BACKEND_API_KEY} from the environment at start (official image templates)
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY public /usr/share/nginx/html
EXPOSE 80
