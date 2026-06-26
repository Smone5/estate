# Cloudflare Tunnel Setup

This is a one-time, per-developer setup that gives your local Estate Steward instance a real `https://` URL — no port forwarding, no static IP, no certificates to manage. It's required for full mobile testing (see [Mobile & PWA Testing Guide](./mobile-pwa-testing.md#1-why-https-matters-here-read-this-first)) because voice recording needs a genuine secure context, which a LAN IP over plain HTTP can't provide.

It's free for this use case (Cloudflare's tunnel product has a generous free tier) and takes about 5–10 minutes.

## What you'll end up with

- A `cloudflared` container (already defined in [docker-compose.yml](../docker-compose.yml), behind the `tunnel` profile) that opens an **outbound-only** connection from your machine to Cloudflare's network — no inbound ports need to be opened on your router or firewall.
- A hostname like `estate-dev.yourdomain.com` that proxies HTTPS traffic to your local `nginx` container.
- Two values to drop into your `.env`: `CLOUDFLARE_TUNNEL_TOKEN` and `PUBLIC_BASE_URL`.

## Prerequisites

- A free [Cloudflare account](https://dash.cloudflare.com/sign-up).
- **A domain added to that Cloudflare account**, with Cloudflare set as its DNS provider. If you don't already own a domain:
  - Cloudflare Registrar, Namecheap, Porkbun, etc. all sell domains cheaply (often under $10/yr) — any of these work as long as you add the domain to Cloudflare afterward and update its nameservers.
  - You do **not** need a domain dedicated to this project — a subdomain like `estate-dev.your-existing-domain.com` is fine and won't affect anything else on that domain.

## Step-by-step

### 1. Create the tunnel

1. Go to the [Cloudflare Zero Trust dashboard](https://one.dash.cloudflare.com).
2. Navigate to **Networks → Tunnels**.
3. Click **Create a tunnel**.
4. Choose connector type **Cloudflared**.
5. Give it a name, e.g. `estate-steward-dev`.
6. On the "Install and run a connector" step, Cloudflare shows you a command containing a long token, e.g.:
   ```
   cloudflared tunnel --no-autoupdate run --token eyJhIjoiMD...
   ```
   You don't need to run this command yourself — `docker-compose.yml` already runs it inside the `cloudflared` service. **Copy just the token value** (the long string after `--token`).

### 2. Add a public hostname

Still in the tunnel's configuration (Public Hostname tab):

1. Click **Add a public hostname**.
2. **Subdomain:** pick something like `estate-dev`.
3. **Domain:** select the domain you added to your Cloudflare account.
4. **Service type:** `HTTP`.
5. **URL:** `localhost:80`

   This is `localhost`, not `nginx`, because the `cloudflared` container in this repo runs with `network_mode: host` ([docker-compose.yml](../docker-compose.yml)) — it shares your machine's network namespace directly rather than Docker's internal bridge network, so it reaches the `nginx` container the same way your browser does: via `localhost:80`, which Docker has published to your host machine.
6. Save.

Your full hostname is now something like `https://estate-dev.yourdomain.com`, already routed to your local stack.

### 3. Configure `.env`

Open your `.env` (copy from `.env.example` first if you haven't already: `cp .env.example .env`) and set:

```bash
CLOUDFLARE_TUNNEL_TOKEN=eyJhIjoiMD...    # the token from step 1
PUBLIC_BASE_URL=https://estate-dev.yourdomain.com   # the hostname from step 2
```

`PUBLIC_BASE_URL` matters beyond just the tunnel — it's used by the backend to build absolute links (e.g. in invite emails), so it should always match whatever URL people actually use to reach the app.

### 4. Launch

```bash
./scripts/install_on_phone.sh
```

With `CLOUDFLARE_TUNNEL_TOKEN` set, the script:
- Starts the stack as usual.
- Runs `docker compose --profile tunnel up -d cloudflared`, which brings up the tunnel container using your token.
- Prints `PUBLIC_BASE_URL` as the install link, with a QR code, instead of falling back to a LAN IP.

Your phone can now be on **any** network (cellular data included) — the tunnel handles the connection.

### 5. Verify

- Open the printed `https://` URL in a desktop browser first. You should see the app load normally.
- Open it on your phone and confirm the address bar shows a padlock / `https://`.
- Try the voice recorder (e.g. in the Admin inventory staging panel) — the Record button should now be enabled instead of showing "Voice recording requires a secure HTTPS connection".

## Stopping the tunnel

```bash
docker compose --profile tunnel stop cloudflared
```

The tunnel only runs when explicitly started via the `tunnel` profile — `docker compose up` without `--profile tunnel` (or without going through `install_on_phone.sh`, which adds the flag automatically when a token is present) will not start it.

## Troubleshooting

**"CLOUDFLARE_TUNNEL_TOKEN is set but PUBLIC_BASE_URL is blank in .env"**
The install script requires both values together — it can start the tunnel but can't print a useful link without knowing the hostname you configured in step 2. Add `PUBLIC_BASE_URL` and re-run.

**Tunnel shows as "Inactive" in the Cloudflare dashboard**
The `cloudflared` container probably isn't running. Check `docker compose ps cloudflared` and `docker compose logs cloudflared` — a common cause is an incorrect or expired token pasted into `.env` (re-copy it from the tunnel's connector command in the dashboard).

**Page loads but shows a Cloudflare error (502/523/etc.)**
Usually means the public hostname's service URL is wrong, or `nginx` isn't actually listening on port 80 on your host. Confirm `docker compose ps` shows `nginx` as `Up` and that `curl http://localhost:80` works locally before suspecting the tunnel.

**Multiple developers on the same project**
Each developer should create their **own** tunnel and hostname (e.g. `estate-dev-alice.yourdomain.com`, `estate-dev-bob.yourdomain.com`) under their own Cloudflare account, rather than sharing one token — tunnels are meant to be per-machine, and sharing a token means everyone's local stack fights over the same hostname.
