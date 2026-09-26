# 9. Hosting the prototype so Claude.ai can reach it (HTTPS)

Claude.ai connects to your MCP server **from Anthropic's servers**, not from your browser. So `http://localhost:8001/mcp` can never work, even with HTTPS: for Anthropic, "localhost" is their own machine. The connector needs a **public HTTPS URL**.

| Option | Cost | Setup | Stays online when your PC is off | Best for |
|---|---|---|---|---|
| **A. Tunnel from your PC** (cloudflared) | free | 5 min | no | a quick first try |
| **B. Small cloud server** (Docker + Caddy, automatic HTTPS) | ~€4-6/month, or a free-tier VM | ~20 min | yes | demos to the client, stable URL |

Both options use **demo data only** (SQLite). Don't put real client data on a prototype server (see [03 §9](03-security-authn-authz.md#9-data-protection-and-compliance) and [08](08-production-checklist.md)).

---

## Option A: Tunnel from your PC (no server)

Covered in [00 §5](00-local-quickstart.md#5-test-with-real-claudeai-free-plan): two `cloudflared tunnel --url ...` commands give you two `https://….trycloudflare.com` URLs. Put them in `.env` and restart. Corporate networks often block tunnels; if so, use option B.

---

## Option B: Small cloud server with automatic HTTPS

What runs on the server (`deploy/docker-compose.demo.yml`):

```
Internet ──443──► Caddy (Let's Encrypt certificate, automatic)
                   ├── /mcp, /.well-known/oauth-protected-resource*  ──► MCP server container
                   └── everything else (/admin, /oauth, /api)        ──► gateway container ──► SQLite (volume)
```

Everything sits on **one hostname**, so there's only one URL to manage. The gateway runs in `GATEWAY_ENVIRONMENT=staging`: full production hardening (secure `__Host-` cookies, **MFA mandatory for admins**, API docs hidden, HTTPS URLs enforced), but SQLite is allowed.

### B1. Get a server

Any Linux VM with a public IPv4 address, 1 vCPU / 1-2 GB RAM, Ubuntu 22.04/24.04 or Debian 12, **x86_64**. For example:
- Hetzner Cloud CX22 (~€4/month), DigitalOcean basic droplet (~$6/month), Contabo, OVH
- Free tiers: Google Cloud e2-micro, Oracle Cloud Always Free (prefer an AMD/x86 shape)

In the provider's firewall, open inbound **TCP 22, 80 and 443**. Port 80 is needed for the Let's Encrypt check.

### B2. Get a hostname

- **Have a domain?** Create an `A` record, e.g. `moneta-ai.yourdomain.bg` → server IP.
- **No domain?** Use the free wildcard DNS service **sslip.io**: server IP `203.0.113.10` → hostname `203-0-113-10.sslip.io`. It resolves automatically and Let's Encrypt can issue a certificate for it. If certificate issuance fails (rate limits), use a real domain.

### B3. Install and start (on the server)

```bash
ssh root@<SERVER_IP>

# Docker
curl -fsSL https://get.docker.com | sh

# code (if the repo is private, GitHub asks for your username + a Personal Access Token as the password)
git clone -b claude/moneta-erp-claude-integration-o2v0zy https://github.com/iamalexninov/mcp-moneta.git
cd mcp-moneta

# config
cp deploy/demo.env.example .env
SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
sed -i "s|^GATEWAY_SESSION_SECRET=.*|GATEWAY_SESSION_SECRET=$SECRET|" .env
sed -i "s|^PUBLIC_HOST=.*|PUBLIC_HOST=203-0-113-10.sslip.io|" .env      # <-- your hostname
cat .env

# shortcut for the long compose command (valid for this shell session)
alias dc='docker compose --env-file .env -f deploy/docker-compose.demo.yml'

# build the image (first time ~3-5 min)
dc build

# create admin + demo data (choose your own strong password)
dc run --rm -T gateway python -m gateway.cli create-admin --tenant "Demo Company" --email admin@demo.bg --name "Admin" --password 'Choose-A-Strong-Passw0rd!'
dc run --rm -T gateway python -m gateway.cli seed-demo --tenant "Demo Company"

# MCP server secret -> .env
MCP_SECRET=$(dc run --rm -T gateway python -m gateway.cli register-mcp-server | grep MCP_CLIENT_SECRET | sed 's/^ *MCP_CLIENT_SECRET=//')
sed -i "s|^MCP_CLIENT_SECRET=.*|MCP_CLIENT_SECRET=$MCP_SECRET|" .env
grep MCP_CLIENT_SECRET .env          # must show a long value

# start everything
dc up -d
dc logs -f caddy                     # wait for "certificate obtained successfully", then Ctrl+C
```

### B4. Check it

From your own PC (replace the hostname):

```bash
curl https://203-0-113-10.sslip.io/healthz
# {"status":"ok"}
curl -i -X POST https://203-0-113-10.sslip.io/mcp -H "content-type: application/json" -d "{}"
# HTTP/2 401 ... www-authenticate: Bearer ... resource_metadata="https://203-0-113-10.sslip.io/.well-known/oauth-protected-resource/mcp"

# full Claude-like flow, run from your PC inside the repo with .venv active:
python scripts/e2e_demo.py --mcp-url https://203-0-113-10.sslip.io/mcp --email admin@demo.bg --password 'Choose-A-Strong-Passw0rd!'
```

### B5. Admin panel + MFA

Open `https://<hostname>/admin` and log in. Because this is internet-facing, you are sent to the **MFA** page first. Add the key to an authenticator app (Microsoft/Google Authenticator, 1Password…) and confirm the 6-digit code. From then on, login and the Claude consent page ask for the code.

### B6. Connect Claude.ai

1. Claude.ai → **Customize → Connectors → Add custom connector**
2. Name `Moneta`, URL **`https://<hostname>/mcp`**, then **Add**, then **Connect**
3. Sign in (email, password, MFA code), tick the permissions you want, and approve
4. In a chat or Project: **+ → Connectors → Moneta** on

If you previously added a connector pointing to a tunnel URL, remove it first.

### B7. Day-to-day

| Task | Command (in `~/mcp-moneta`, after `alias dc=...`) |
|---|---|
| Status / logs | `dc ps` · `dc logs -f gateway` · `dc logs -f mcp` |
| Update to latest code | `git pull && dc up -d --build` |
| Restart | `dc restart` |
| Stop (data kept) | `dc down` |
| Wipe everything (DB, keys, certificates) | `dc down -v` |
| Add a user | `dc run --rm -T gateway python -m gateway.cli create-admin --tenant "Demo Company" --email x@y.bg --name X --role sales --password '...'` |

### B8. Hardening for a public prototype

- Demo data only. Strong admin password. MFA is enforced.
- Optional: allow `/mcp` only from Anthropic's egress range `160.79.104.0/21`. Uncomment the `@notanthropic` block in `deploy/Caddyfile`, then `dc restart caddy`. This also blocks `e2e_demo.py` from your PC, which is expected.
- Keep the server patched (`apt update && apt upgrade`), SSH keys only, and consider `ufw` allowing just 22/80/443.

### Troubleshooting

| Symptom | Fix |
|---|---|
| `dc logs caddy` shows ACME/certificate errors | Ports 80/443 not open, or the hostname doesn't resolve to this server (`ping <hostname>`). With sslip.io, check the dashes match the IP. |
| Gateway exits: `Unsafe production configuration` | `GATEWAY_SESSION_SECRET` still empty or default in `.env` |
| MCP exits: `MCP_CLIENT_SECRET is not set` | Redo the MCP secret step in B3, then `dc up -d` |
| Claude.ai: "Couldn't reach the MCP server" | Use exactly `https://<hostname>/mcp`. Check that B4 works from outside. |
| Tool calls fail "no longer authorized" | MCP secret in `.env` doesn't match; run `register-mcp-server` again, update `.env`, `dc up -d` |

> **What was verified:** the staging configuration, the Caddy routing file, admin MFA enforcement and the full OAuth + MCP flow were tested over real HTTPS through Caddy. The Docker image build itself couldn't be run in the development sandbox (its network blocks the Debian package mirrors), so `dc build` on your server is the first real run of the image build.
