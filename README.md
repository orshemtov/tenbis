# tenbis

Daily Shufersal voucher bot: checks your 10bis balance, buys a ₪200 Shufersal voucher, and sends the barcode image to your **Vouchers** WhatsApp group. Once you or your wife react to the message with any emoji, the bot acknowledges it with 🤖.

Runs locally on a home Linux server — no cloud, no Telegram, no reverse-engineered APIs. Uses Playwright with persistent Chromium profiles.

```
Daily flow  (09:00 Jerusalem time, via systemd timer)
──────────────────────────────────────────────────────
1. Open WhatsApp group
2. Acknowledge any reacted vouchers with 🤖
3. Already sent a voucher today?  →  exit (idempotent)
4. Check 10bis balance  →  skip if too low
5. Purchase ₪200 Shufersal voucher on 10bis
6. Send barcode image + caption to WhatsApp group
7. On any failure  →  post ⚠️ alert to the same group
```

**WhatsApp is the single source of truth** — no local voucher files.
- No reactions = active voucher
- Any reaction = used → bot adds 🤖
- 🤖 present = already acknowledged

---

## Requirements

| | Notes |
|---|---|
| Linux server (Debian/Ubuntu) | For headless production runs |
| macOS laptop | For initial login sessions |
| [mise](https://mise.jdx.dev) | `curl https://mise.run \| sh` |
| Python 3.13 | Installed automatically by mise |
| Chromium system libs | Installed by `bootstrap-server.sh` |

---

## First-time setup (laptop)

### 1. Clone and install

```bash
git clone git@github.com:<you>/tenbis.git ~/Projects/tenbis
cd ~/Projects/tenbis
mise install           # installs Python 3.13 + uv
mise run install       # uv sync + playwright install chromium
```

### 2. Configure

```bash
cp .env.example .env
$EDITOR .env           # set TENBIS_EMAIL, WHATSAPP_GROUP_NAME, SERVER
```

### 3. Log in to 10bis

```bash
mise run login:tenbis
```

A browser opens. The script fills your email and submits. Enter the OTP when prompted in the terminal. Session saved to `data/10bis-profile/`.

### 4. Log in to WhatsApp Web

```bash
mise run login:whatsapp
```

Scan the QR code. Wait for the chat list. Session saved to `data/whatsapp-profile/`.

### 5. Sanity-check

```bash
mise run budget          # print current monthly + daily balance
mise run purchase:dry    # rehearse the full purchase flow, stops before Submit
```

---

## Server setup

### 1. Bootstrap (one-time)

```bash
ssh your-server
git clone git@github.com:<you>/tenbis.git ~/tenbis
cd ~/tenbis
bash scripts/bootstrap-server.sh   # installs mise, Python, uv, Chromium libs
```

### 2. Configure

```bash
cp .env.example .env
nano .env    # same values as laptop; add HEADLESS=true LOG_FORMAT=plain
```

### 3. Sync browser profiles from laptop

```bash
# On your laptop (SERVER= must be set in .env):
mise run sync:profiles
```

### 4. Enable the systemd timer

```bash
# On the server:
mise run server:install
mise run server:status   # verify timer is active
```

---

## Command reference

### Setup

| Command | What it does |
|---|---|
| `mise run install` | Install Python deps + Playwright Chromium |
| `mise run install:deps` | Install Chromium system libs — needs sudo, once on the server |
| `mise run login:tenbis` | Headed 10bis login (laptop) |
| `mise run login:whatsapp` | Headed WhatsApp QR login (laptop) |
| `mise run login:tenbis:server` | Headed 10bis login via xvfb-run (server) |
| `mise run sync:profiles` | rsync browser profiles from laptop → server |
| `mise run deploy` | git push + server pull + reinstall |

### Daily operations

| Command | What it does |
|---|---|
| `mise run run` | **Full daily pipeline** — scan → purchase → send (idempotent) |
| `mise run budget` | Print current 10bis monthly + daily balance |
| `mise run purchase` | Purchase a voucher and send it to WhatsApp (no scan, no idempotency check) |
| `mise run purchase:dry` | Full purchase flow but stop before clicking Submit |
| `mise run scan` | Scan WhatsApp reactions and acknowledge used vouchers with 🤖 |
| `mise run vouchers:list` | Show active / used / acknowledged vouchers from the WhatsApp group |

### Server management

| Command | Where to run | What it does |
|---|---|---|
| `mise run server:install` | server | Install + enable systemd timer |
| `mise run server:status` | server | Show timer + service status |
| `mise run server:logs` | server | Tail last 200 log lines |
| `mise run server:run-now` | server | Trigger an immediate run |

### Dev

| Command | What it does |
|---|---|
| `mise run fmt` | Format code with ruff |
| `mise run lint` | Lint with ruff |
| `mise run test` | Run tests with pytest |

---

## Troubleshooting

### "10bis session expired"

The WhatsApp group receives a ⚠️ message. Fix on your laptop:

```bash
mise run login:tenbis
mise run sync:profiles
```

### "WhatsApp session expired"

```bash
mise run login:whatsapp
mise run sync:profiles
```

### Nothing was purchased

Check the logs — look for `budget_too_low` or `already_sent_today`:

```bash
mise run server:logs
mise run budget
```

### Playwright failure

Every exception saves a screenshot + HTML dump:

```
data/debug/<timestamp>/screenshot.png
data/debug/<timestamp>/page.html
```

### Pause the timer

```bash
systemctl --user stop tenbis.timer
systemctl --user start tenbis.timer   # resume
```

---

## Security

- `.env` and `data/` contain live session tokens — both are gitignored. Never commit them.
- Use a private GitHub repository.
- `chmod 600 .env` on both laptop and server.
