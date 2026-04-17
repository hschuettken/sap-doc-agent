# Spec2Sphere — TLS Configuration

Configure TLS using the `TLS_MODE` env var. Three modes are supported.

---

## Table of Contents

1. [Mode: client_lb (default)](#mode-client_lb-default)
2. [Mode: caddy (automatic Let's Encrypt)](#mode-caddy-automatic-lets-encrypt)
3. [Mode: self_signed (demo only)](#mode-self_signed-demo-only)
4. [Certificate for Widget CORS](#certificate-for-widget-cors)

---

## Mode: `client_lb` (default)

```bash
TLS_MODE=client_lb
```

Your existing reverse proxy (nginx, Traefik, AWS ALB, Cloudflare Tunnel, Azure Application Gateway) terminates TLS and forwards plain HTTP to ports **8260** (Studio) and **8261** (DSP-AI API).

**No TLS configuration is needed on the Compose side.**

### Example: nginx upstream block

```nginx
upstream spec2sphere_studio {
    server 127.0.0.1:8260;
}
upstream spec2sphere_api {
    server 127.0.0.1:8261;
}

server {
    listen 443 ssl;
    server_name studio.example.com;
    ssl_certificate     /etc/ssl/certs/example.com.crt;
    ssl_certificate_key /etc/ssl/private/example.com.key;

    location / {
        proxy_pass http://spec2sphere_studio;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

server {
    listen 443 ssl;
    server_name api.example.com;
    ssl_certificate     /etc/ssl/certs/example.com.crt;
    ssl_certificate_key /etc/ssl/private/example.com.key;

    location / {
        proxy_pass http://spec2sphere_api;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Example: Traefik label (docker-compose.override.yml)

```yaml
services:
  web:
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.spec2sphere.rule=Host(`studio.example.com`)"
      - "traefik.http.routers.spec2sphere.entrypoints=websecure"
      - "traefik.http.routers.spec2sphere.tls.certresolver=letsencrypt"
      - "traefik.http.services.spec2sphere.loadbalancer.server.port=8260"
  dsp-ai:
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.dspai.rule=Host(`api.example.com`)"
      - "traefik.http.routers.dspai.entrypoints=websecure"
      - "traefik.http.routers.dspai.tls.certresolver=letsencrypt"
      - "traefik.http.services.dspai.loadbalancer.server.port=8261"
```

---

## Mode: `caddy` (automatic Let's Encrypt)

```bash
TLS_MODE=caddy
```

A Caddy sidecar container handles TLS automatically via ACME / Let's Encrypt.

### Prerequisites

- Domain DNS A records pointing to this host's public IP
- Ports 80 and 443 reachable from the internet (Let's Encrypt HTTP-01 challenge)

### Step 1 — Create the Caddyfile

Create `ops/Caddyfile`:

```
studio.example.com {
    reverse_proxy web:8080
    encode gzip
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options nosniff
        X-Frame-Options SAMEORIGIN
    }
}

api.example.com {
    reverse_proxy dsp-ai:8000
    encode gzip
}
```

> Note: Inside the compose network, `web` listens on `8080` (internal) and `dsp-ai` on `8000` (internal). The host-mapped ports 8260/8261 are for direct access only — Caddy communicates via the Docker network.

### Step 2 — Add the Caddy override

Create `docker-compose.tls.yml`:

```yaml
services:
  caddy:
    image: caddy:2-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./ops/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy-data:/data
      - caddy-config:/config
    networks:
      - app-network
    depends_on:
      - web
      - dsp-ai

volumes:
  caddy-data:
  caddy-config:
```

### Step 3 — Start with TLS

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d
```

Caddy will obtain and auto-renew Let's Encrypt certificates. Certificates are persisted in the `caddy-data` volume.

### Verification

```bash
curl -sf https://api.example.com/v1/healthz
# Expected: {"status":"ok"}
```

---

## Mode: `self_signed` (demo only)

```bash
TLS_MODE=self_signed
```

Suitable for isolated on-premises demos where Let's Encrypt is not available and the client controls the trust store.

> **Warning:** SAC (cloud-hosted) will refuse to load the widget over a self-signed certificate unless the cert is in the browser's trust store. Self-signed TLS is not viable for production SAC widget deployments.

### Generate a self-signed certificate

Using `mkcert` (recommended — installs a local CA):

```bash
brew install mkcert        # macOS
# or: apt install mkcert   # Linux

mkcert -install
mkcert studio.example.com api.example.com localhost 127.0.0.1

# Outputs:
#   studio.example.com+3.pem
#   studio.example.com+3-key.pem
mkdir -p ops/certs
mv studio.example.com+3.pem ops/certs/fullchain.pem
mv studio.example.com+3-key.pem ops/certs/privkey.pem
```

Using `openssl` (no CA install required):

```bash
mkdir -p ops/certs
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout ops/certs/privkey.pem \
  -out ops/certs/fullchain.pem \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,DNS:studio.example.com,IP:127.0.0.1"
```

### Mount the cert into Caddy

Update `ops/Caddyfile` for self-signed mode:

```
studio.example.com {
    reverse_proxy web:8080
    tls /etc/caddy/certs/fullchain.pem /etc/caddy/certs/privkey.pem
}

api.example.com {
    reverse_proxy dsp-ai:8000
    tls /etc/caddy/certs/fullchain.pem /etc/caddy/certs/privkey.pem
}
```

Add the cert mount in `docker-compose.tls.yml`:

```yaml
services:
  caddy:
    volumes:
      - ./ops/Caddyfile:/etc/caddy/Caddyfile:ro
      - ./ops/certs:/etc/caddy/certs:ro
      - caddy-data:/data
      - caddy-config:/config
```

---

## Certificate for Widget CORS

Browsers enforce the **same-origin policy** on widgets loaded by SAC. The CORS interaction works as follows:

1. The SAC page (e.g. `https://your-tenant.eu10.hcs.cloud.sap`) loads the widget script from `https://api.example.com/widget/main.js`.
2. The browser sends a CORS preflight to `https://api.example.com`.
3. The DSP-AI service checks the `Origin` header against `WIDGET_ALLOWED_ORIGINS`.

**Rules:**

- `WIDGET_ALLOWED_ORIGINS` must contain the **exact** SAC origin, including scheme and no trailing slash.
- `https://your-tenant.eu10.hcs.cloud.sap` and `http://your-tenant.eu10.hcs.cloud.sap` are different origins.
- Wildcards are not supported. List each SAC origin explicitly.

**Example:**

```bash
WIDGET_ALLOWED_ORIGINS=https://your-tenant.eu10.hcs.cloud.sap,https://your-tenant-2.eu10.hcs.cloud.sap
```

After changing `WIDGET_ALLOWED_ORIGINS`, restart `dsp-ai`:

```bash
docker compose restart dsp-ai
```

### Checklist for SAC widget CORS

- [ ] `WIDGET_ALLOWED_ORIGINS` set to exact SAC origin
- [ ] `dsp-ai` running over HTTPS (either `caddy` mode or behind `client_lb` reverse proxy with a valid cert)
- [ ] Certificate is publicly trusted (self-signed will be blocked by the browser when loaded from SAC cloud)
- [ ] `dsp-ai` hostname resolves from the browser (not just from inside the Docker network)

---

*Last updated: Session C, Task 10*
