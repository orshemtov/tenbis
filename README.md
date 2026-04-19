# tenbis

Daily Shufersal voucher automation: checks your 10bis balance, buys a ₪200 voucher, sends the barcode to your **Vouchers** WhatsApp group, and marks it as used once you or your wife react with any emoji.

Runs fully locally — no AWS, no Telegram, no reverse-engineered API tokens. Everything is Playwright + persistent Chromium profiles, so the session stays alive for weeks.

```
Daily flow (09:00 Jerusalem time, via systemd timer)
─────────────────────────────────────────────────────
1. Scan WhatsApp reactions  ──►  move reacted vouchers to used/
2. Already purchased today?  ──►  exit 0 (idempotent)
3. Check 10bis balance  ──►  skip if < ₪200
4. Purchase Shufersal voucher
5. Save barcode PNG + sidecar JSON to data/vouchers/pending/
6. Send barcode image to "Vouchers" WhatsApp group
7. On any failure  ──►  post ⚠️ alert to the same group
```

---

## Requirements

| Requirement | Notes |
|---|---|
| Linux (Debian/Ubuntu) | Server-side; macOS for local login sessions |
| [mise](https://mise.jdx.dev) | `curl https://mise.run \| sh` |
| Git | `apt install git` |
| Python 3.13 | Installed automatically by mise |
| Chromium system libs | Installed by `bootstrap-server.sh` |

---

## First-time setup (on your laptop)

### 1. Clone and install

```bash
git clone git@github.com:<you>/tenbis.git ~/Projects/tenbis
cd ~/Projects/tenbis
mise install          # installs Python 3.13 + uv
mise run install      # uv sync + playwright install chromium
```

### 2. Configure

```bash
cp .env.example .env
$EDITOR .env          # set TENBIS_EMAIL, WHATSAPP_GROUP_NAME, SERVER, etc.
```

### 3. Log in to 10bis (headed browser, one-time)

```bash
mise run login:tenbis
```

A browser window opens. If you're already logged in you're done. Otherwise:
- The script fills your email and submits.
- Enter the 5-digit OTP when prompted in the terminal.
- The session is saved to `data/10bis-profile/`.

### 4. Log in to WhatsApp Web (headed browser, one-time)

```bash
mise run login:whatsapp
```

Scan the QR code in the browser. Wait for the chat list to appear. Done — session saved to `data/whatsapp-profile/`.

### 5. Sanity-check

```bash
mise run budget         # prints current monthly + daily balance
mise run purchase:dry   # full flow, stops before clicking Submit
```

---

## Server setup

### 1. Clone on the server

```bash
ssh your-server
git clone git@github.com:<you>/tenbis.git ~/tenbis
cd ~/tenbis
```

### 2. Bootstrap (one-time, needs sudo for apt packages)

```bash
bash scripts/bootstrap-server.sh
```

This installs: Chromium system deps, mise, Python 3.13, uv, and all Python packages.

### 3. Configure

```bash
cp .env.example .env
nano .env              # same values as your laptop, set HEADLESS=true
```

### 4. Sync browser profiles from your laptop

Back on your laptop:

```bash
# Make sure SERVER= is set in .env or exported
mise run sync:profiles
```

This rsyncs `data/10bis-profile/` and `data/whatsapp-profile/` to the server.

### 5. Install and enable the systemd timer

On the server:

```bash
mise run server:install
```

This:
- Copies `systemd/tenbis.{service,timer}` to `~/.config/systemd/user/`
- Runs `systemctl --user enable --now tenbis.timer`
- Runs `loginctl enable-linger $USER` so the timer fires even without an active login session

Verify:

```bash
mise run server:status
```

---

## Daily operations

### Check what's scheduled

```bash
mise run server:status
```

### Trigger a run right now

```bash
mise run server:run-now
```

### Watch the logs

```bash
mise run server:logs
```

### Manually check the balance

```bash
mise run budget
```

### Manually purchase (without sending to WhatsApp)

```bash
mise run purchase
```

### Send any unsent pending vouchers to WhatsApp

```bash
mise run send
```

### Scan reactions and move used vouchers

```bash
mise run scan
```

---

## Voucher file layout

```
data/vouchers/
├── pending/
│   ├── 2026-04-19_14-59_913920508201984.png   ← barcode image
│   └── 2026-04-19_14-59_913920508201984.json  ← metadata sidecar
└── used/
    ├── 2026-04-01_09-02_913920012345678.png
    └── 2026-04-01_09-02_913920012345678.json
```

**Sidecar JSON fields:**

| Field | Description |
|---|---|
| `barcode_number` | The barcode digits |
| `amount` | `200.0` |
| `purchased_at` | ISO-8601 timestamp with TZ |
| `whatsapp_group` | `"Vouchers"` |
| `whatsapp_message_id` | `data-id` attribute of the WA message; empty until sent |
| `order_id` | 10bis order ID |

Files are **never** auto-deleted. `used/` is an audit trail.

---

## Troubleshooting

### "10bis session expired"

The WhatsApp group will receive a `⚠️` message. To fix:

```bash
# On your laptop:
mise run login:tenbis
mise run sync:profiles
```

### "WhatsApp session expired"

```bash
# On your laptop:
mise run login:whatsapp
mise run sync:profiles
```

### "Vouchers group not found"

Verify `WHATSAPP_GROUP_NAME` in `.env` matches the **exact** group title (case-sensitive). The selector does an exact-title match.

### Run worked but nothing was purchased

- Check `mise run server:logs` — look for `budget_too_low` or `already_purchased_today`.
- Run `mise run budget` to confirm the balance.

### Debugging Playwright failures

Each Playwright exception saves a full-page screenshot + HTML to:

```
data/debug/<timestamp>/screenshot.png
data/debug/<timestamp>/page.html
```

### Disable the timer temporarily

```bash
systemctl --user stop tenbis.timer
# Re-enable later:
systemctl --user start tenbis.timer
```

---

## Uninstall

```bash
# On the server:
systemctl --user disable --now tenbis.timer tenbis.service
rm ~/.config/systemd/user/tenbis.{service,timer}
systemctl --user daemon-reload
rm -rf ~/tenbis
```

---

## Security

- `.env` contains your 10bis email and can in principle capture session tokens — keep it `chmod 600` and **never commit it**.
- `data/` contains live browser sessions for both 10bis and WhatsApp Web — **never commit it**. Both are in `.gitignore`.
- Use a private GitHub repository.

---

## All mise tasks

| Task | Description |
|---|---|
| `mise run install` | Install deps + Playwright Chromium |
| `mise run install:deps` | Install Chromium system libs (sudo, server once) |
| `mise run login:tenbis` | Headed 10bis login (laptop) |
| `mise run login:whatsapp` | Headed WhatsApp QR login (laptop) |
| `mise run budget` | Print current balance |
| `mise run purchase:dry` | Dry-run purchase (no charge) |
| `mise run purchase` | Buy a voucher |
| `mise run send` | Send unsent vouchers to WhatsApp |
| `mise run scan` | Scan reactions, move used vouchers |
| `mise run run` | Full daily pipeline |
| `mise run sync:profiles` | rsync browser profiles laptop → server |
| `mise run deploy` | git push + server pull + reinstall |
| `mise run server:install` | Install + enable systemd timer (server) |
| `mise run server:status` | Show timer/service status (server) |
| `mise run server:logs` | Tail last 200 log lines (server) |
| `mise run server:run-now` | Trigger an immediate run (server) |
| `mise run fmt` | Format code (ruff) |
| `mise run lint` | Lint code (ruff) |
| `mise run test` | Run tests (pytest) |
