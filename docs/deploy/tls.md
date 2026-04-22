# TLS Options for Spec2Sphere

## Mode 1: Client-Provided Reverse Proxy (default, `TLS_MODE=client_lb`)

The recommended production setup. Your client's reverse proxy (nginx, HAProxy, Azure
Application Gateway, etc.) terminates TLS and forwards plain HTTP to port 8260.

No changes to `docker-compose.yml`. Just set:
```
SPEC2SPHERE_BASE_URL=https://spec2sphere.client.example.com
```

---

## Mode 2: Bundled Caddy Sidecar (`TLS_MODE=caddy`)

For demos or self-hosted installations without an existing reverse proxy.
Caddy obtains a Let's Encrypt certificate automatically.

Add to `docker-compose.yml`:
```yaml
caddy:
  image: caddy:2-alpine
  ports:
    - "80:80"
    - "443:443"
  volumes:
    - ./ops/Caddyfile:/etc/caddy/Caddyfile:ro
    - caddy-data:/data
  environment:
    DOMAIN: ${SPEC2SPHERE_DOMAIN}
  networks:
    - default

volumes:
  caddy-data:
```

Create `ops/Caddyfile`:
```
{$DOMAIN} {
    reverse_proxy web:8260
}
```

Set `SPEC2SPHERE_DOMAIN=spec2sphere.client.example.com` in `.env`.

Requires: outbound port 80/443 from the server, a valid DNS A record.

---

## Mode 3: Self-Signed Certificate (`TLS_MODE=self_signed`)

For internal / air-gapped demos only. Browsers will warn.

Generate a cert:
```bash
openssl req -x509 -newkey rsa:4096 -nodes \
  -keyout ops/tls/key.pem -out ops/tls/cert.pem \
  -days 365 -subj "/CN=spec2sphere.local"
```

Add an nginx sidecar to `docker-compose.yml`:
```yaml
nginx-tls:
  image: nginx:alpine
  ports:
    - "443:443"
  volumes:
    - ./ops/nginx-tls.conf:/etc/nginx/conf.d/default.conf:ro
    - ./ops/tls:/etc/nginx/tls:ro
  networks:
    - default
```

`ops/nginx-tls.conf`:
```nginx
server {
    listen 443 ssl;
    ssl_certificate /etc/nginx/tls/cert.pem;
    ssl_certificate_key /etc/nginx/tls/key.pem;
    location / {
        proxy_pass http://web:8260;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```
