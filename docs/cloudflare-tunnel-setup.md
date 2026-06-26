# Cloudflare Tunnel Setup

This is a one-time, per-developer setup that gives your local Estate Steward instance a real `https://` URL — no port forwarding, no static IP, no certificates to manage. It's required for full mobile testing (see [Mobile & PWA Testing Guide](./mobile-pwa-testing.md#1-why-https-matters-here-read-this-first)) because voice recording needs a genuine secure context, which a LAN IP over plain HTTP can't provide.

It's free for this use case (Cloudflare's tunnel product has a generous free tier) and takes about 5–10 minutes.

## What you'll end up with

- A `cloudflared` container (already defined in [docker-compose.yml](../docker-compose.yml), behind the `tunnel` profile) that opens an **outbound-only** connection from your machine to Cloudflare's network — no inbound ports need to be opened on your router or firewall.
- A hostname like `estate-dev.yourdomain.com` that proxies HTTPS traffic to your local `nginx` container.
- Two values to drop into your `.env`: `CLOUDFLARE_TUNNEL_TOKEN` and `PUBLIC_BASE_URL`.

## Prerequisites

- A free [Cloudflare account](https://dash.cloudflare.com/sign-up).
- A domain added to that Cloudflare account, with Cloudflare set as its DNS provider — **or** the no-domain alternative in Option C below.

You have three options here, depending on what you already have:

### Option A — You already own a domain

You can use a domain you already own, even if it's currently managed elsewhere (GoDaddy, Namecheap, Google Domains, etc.). You do **not** need a domain dedicated to this project — a subdomain like `estate-dev.your-existing-domain.com` is fine and won't affect anything else on that domain.

1. Go to the main Cloudflare dashboard: https://dash.cloudflare.com (this is different from the Zero Trust dashboard at `one.dash.cloudflare.com` used later for the tunnel itself).
2. Click **Add a domain** and enter your domain.
3. Cloudflare gives you two nameservers. Log into your current registrar (wherever you bought the domain) and update its nameserver records to point to those two.
4. Wait for the zone to show **Active** in Cloudflare — typically a few minutes, occasionally a few hours depending on DNS propagation.
5. Continue to [Step 1](#1-create-the-tunnel) below. The domain will now appear in the dropdown when you add a route.

### Option B — You don't have a domain yet

Any cheap registrar works — you don't need anything fancy:

- [Cloudflare Registrar](https://www.cloudflare.com/products/registrar/) — domains are sold at cost (no markup), and since you're buying through Cloudflare, the domain is automatically added to your account with no nameserver step needed.
- Namecheap, Porkbun, Google Domains, etc. — buy a domain there (often under $10/yr for a `.com`, less for other TLDs), then follow Option A above to add it to Cloudflare and update nameservers.

Either way, once the domain shows **Active** in Cloudflare, continue to [Step 1](#1-create-the-tunnel) below.

### Option C — Skip the domain entirely (Quick Tunnels)

If you just want to try mobile testing once without any domain setup, Cloudflare's **Quick Tunnels** give you a free, temporary `https://<random-name>.trycloudflare.com` URL with zero account configuration:

```bash
docker run --rm cloudflare/cloudflared:latest tunnel --url http://host.docker.internal:80
```

(On Linux, replace `host.docker.internal` with your host's LAN IP, since that Docker networking alias is a Mac/Windows convenience.)

This prints a random `trycloudflare.com` URL in the logs — use that as `PUBLIC_BASE_URL` in `.env` for that session. The tradeoffs: the URL changes every time you restart the container, there's no named tunnel or token, and it doesn't use the `cloudflared` service already wired up in [docker-compose.yml](../docker-compose.yml) — so you'll need to manage it manually rather than through `install_on_phone.sh`. Fine for a one-off test; switch to Option A/B for anything ongoing.

## Step-by-step

### 1. Create the tunnel

1. Go to the [Cloudflare Zero Trust dashboard](https://one.dash.cloudflare.com).
2. Navigate to **Networks → Tunnels**.
3. Click **Create a tunnel**.
4. Choose connector type **Cloudflared**.
5. Give it a name, e.g. `estate-steward-dev`.
6. On the **"Install and run a connector"** step, Cloudflare shows a "Setup Environment" picker labeled **"Choose your operating system to get installation instructions"** with an **Operating System** dropdown (macOS, Windows, Linux, Docker).

   **Select `Docker`** — regardless of what OS your machine actually runs. This repo already runs `cloudflared` for you inside the `cloudflared` service in [docker-compose.yml](../docker-compose.yml); picking macOS/Windows/Linux here would show you a native-binary install command you don't need and shouldn't run. The Docker option is the only one that produces a `docker run cloudflare/cloudflared:latest tunnel --no-autoupdate run --token ...` command — you only need the token out of it, not the command itself.

7. Cloudflare shows a command containing a long token, e.g.:
   ```
   docker run cloudflare/cloudflared:latest tunnel --no-autoupdate run --token eyJhIjoiMD...
   ```
   Don't run this — **copy just the token value** (the long string after `--token`). The repo's own `docker-compose.yml` already has a `cloudflared` service configured to use this token from `.env`.

### 2. Put the token in `.env` and start the connector

The Cloudflare dashboard won't let you add a public hostname until it sees your connector actually online, so the token has to go into `.env` and the `cloudflared` container has to be running *before* you go back to the dashboard.

1. Copy `.env.example` to `.env` if you haven't already: `cp .env.example .env`.
2. Add **only** the token for now (leave `PUBLIC_BASE_URL` blank — you don't have a hostname yet):
   ```bash
   CLOUDFLARE_TUNNEL_TOKEN=eyJhIjoiMD...
   ```
3. Start just the tunnel connector (not the full app stack yet):
   ```bash
   docker compose --profile tunnel up -d cloudflared
   ```

### 3. Confirm the tunnel is connected

Go back to the Cloudflare Zero Trust dashboard (**Networks → Tunnels**) and refresh. Your tunnel should now show status **Connected / Healthy** (it can take 10–30 seconds). If it still shows "Inactive" after a minute, check `docker compose logs cloudflared` — see [Troubleshooting](#troubleshooting) below.

**Don't move on to the next step until it shows Connected** — Cloudflare's UI hides or rejects the "Add a public hostname" step for a tunnel it can't see online.

### 4. Add a public hostname (Cloudflare may call this a "Route")

Now that the tunnel shows **Healthy/Connected** in the Tunnels list, **click the tunnel's name** (e.g. `estate-steward-dev`) to open its configuration page — the Tunnels list itself doesn't have this option, only the individual tunnel's page does.

> Cloudflare's dashboard has changed this UI more than once. Depending on when you're reading this, you may see either:
> - Tabs **Overview / Public Hostname / Private Networks / Access / Edit** — use the **Public Hostname** tab, or
> - Just **Overview / Routes** — use the **Routes** tab (or the **"+ Add route"** button shown directly in the Routes panel on the Overview page).
>
> Either path leads to the same form, asking for the same fields below — Cloudflare just renamed "public hostname" to "route" in newer versions.

1. Click **Public Hostname** (or **Routes** → **Add route**).
   - If a dialog titled **"Add a route"** appears asking you to pick a route type (Published application / Private hostname / Private CIDR / Workers VPC), choose **Published application**. The other three are for Zero Trust private-network access and won't expose the app to your phone over the internet.
2. **Subdomain:** pick something like `estate-dev`.
3. **Domain:** select the domain you added to your Cloudflare account.
4. **Path:** leave blank (matches all paths).
5. **Service URL** (older UI may split this into separate "Service type" + "URL" fields — same idea either way): `http://localhost:80`

   Use `http://`, not `https://` — the form's placeholder text (`https://localhost:8080`) is just an example, not a requirement. Use `localhost`, not `nginx`, because the `cloudflared` container in this repo runs with `network_mode: host` ([docker-compose.yml](../docker-compose.yml)) — it shares your machine's network namespace directly rather than Docker's internal bridge network, so it reaches the `nginx` container the same way your browser does: via `localhost:80`, which Docker has published to your host machine. Cloudflare's edge handles the HTTPS encryption on the public side; the local target stays plain HTTP.
6. Click **Add route** (or **Save**, depending on the UI version).

Your full hostname is now something like `https://estate-dev.yourdomain.com`, already routed to your local stack.

### 5. Add `PUBLIC_BASE_URL` to `.env`

Now that you have the hostname, go back to `.env` and add the second value:

```bash
CLOUDFLARE_TUNNEL_TOKEN=eyJhIjoiMD...               # already set in step 2
PUBLIC_BASE_URL=https://estate-dev.yourdomain.com   # the hostname from step 4
```

`PUBLIC_BASE_URL` matters beyond just the tunnel — it's used by the backend to build absolute links (e.g. in invite emails), so it should always match whatever URL people actually use to reach the app.

### 6. Launch the full stack

```bash
./scripts/install_on_phone.sh
```

With both values set, the script:
- Builds the frontend and starts the rest of the stack as usual.
- Runs `docker compose --profile tunnel up -d cloudflared` again (a no-op if it's already running from step 2 — safe either way).
- Prints `PUBLIC_BASE_URL` as the install link, with a QR code, instead of falling back to a LAN IP.

Your phone can now be on **any** network (cellular data included) — the tunnel handles the connection.

### 7. Verify

- Open the printed `https://` URL in a desktop browser first. You should see the app load normally.
- Open it on your phone and confirm the address bar shows a padlock / `https://`.
- Try the voice recorder (e.g. in the Admin inventory staging panel) — the Record button should now be enabled instead of showing "Voice recording requires a secure HTTPS connection".

## Stopping the tunnel

```bash
docker compose --profile tunnel stop cloudflared
```

The tunnel only runs when explicitly started via the `tunnel` profile — `docker compose up` without `--profile tunnel` (or without going through `install_on_phone.sh`, which adds the flag automatically when a token is present) will not start it.

## Troubleshooting

**The Domain dropdown is empty when adding a route**
Your Cloudflare account has no domain (zone) added yet. The "Add published application" form can't offer a domain you haven't added. See [Prerequisites](#prerequisites) above — Option A if you own a domain, Option B if you need to buy one, or Option C to skip domains entirely with a Quick Tunnel. Once a domain shows **Active** under the main Cloudflare dashboard's domain list, it'll appear in this dropdown.

**"CLOUDFLARE_TUNNEL_TOKEN is set but PUBLIC_BASE_URL is blank in .env"**
The install script requires both values together — it can start the tunnel but can't print a useful link without knowing the hostname you configured in step 2. Add `PUBLIC_BASE_URL` and re-run.

**Tunnel shows as "Inactive" in the Cloudflare dashboard**
The `cloudflared` container probably isn't running. Check `docker compose ps cloudflared` and `docker compose logs cloudflared` — a common cause is an incorrect or expired token pasted into `.env` (re-copy it from the tunnel's connector command in the dashboard).

**Page loads but shows a Cloudflare error (502/523/etc.)**
Usually means the public hostname's service URL is wrong, or `nginx` isn't actually listening on port 80 on your host. Confirm `docker compose ps` shows `nginx` as `Up` and that `curl http://localhost:80` works locally before suspecting the tunnel.

**Multiple developers on the same project**
Each developer should create their **own** tunnel and hostname (e.g. `estate-dev-alice.yourdomain.com`, `estate-dev-bob.yourdomain.com`) under their own Cloudflare account, rather than sharing one token — tunnels are meant to be per-machine, and sharing a token means everyone's local stack fights over the same hostname.
