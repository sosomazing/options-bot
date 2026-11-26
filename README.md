# Options Bot: Stage 2 (Alpaca paper connection)

> **PAPER TRADING ONLY.** This project only connects to Alpaca's **paper** (simulated money)
> endpoint, `https://paper-api.alpaca.markets`. It refuses live keys and live URLs, and in
> this stage it **cannot submit, change or cancel orders**.

An automated intraday US options bot for Alpaca, built in small stages. The planned strategy
uses VWAP, EMA 9, EMA 21, RSI 14 and volume. Stage 1 is only the foundation:

| Works now | Comes later |
|---|---|
| Alpaca connection test (stage 2) | Market data and indicators (stage 3+) |
| Market clock: open/closed, next open/close (stage 2) | |
| Safe settings (paper mode enforced) | |
| Read-only Alpaca paper connection | Signals from the strategy |
| Account status, cash, equity, buying power | Paper order entry and exits |
| SQLite database (signals, orders, positions, trades) | Risk limits, end-of-day flattening |
| Logging with secrets removed, a dashboard, tests | |

---

## 1. Install on Windows

### 1.1 Install Python
1. Download **Python 3.13** (3.11 or newer works) from <https://www.python.org/downloads/windows/>.
2. Run the installer and **tick "Add python.exe to PATH"** on the first screen.
3. Open **PowerShell** (Start menu, type "PowerShell") and check:
   ```powershell
   py --version
   ```

### 1.2 Get the code and create a virtual environment
Clone the repository in VS Code (**Ctrl+Shift+P** → **Git: Clone** →
`https://github.com/sosomazing/options-bot.git`), or from PowerShell with
`git clone https://github.com/sosomazing/options-bot.git`. Then open the
`options-bot` folder (**File → Open Folder…**) and a terminal (**Ctrl+`**).

A *virtual environment* (venv) is a private folder of Python packages for this project only,
so it can't clash with anything else on your PC.

```powershell
cd path\to\options-bot
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Your prompt now starts with `(.venv)`. Run `Activate.ps1` again every time you open a new
PowerShell window.

> If PowerShell says *"running scripts is disabled on this system"*, run this once and then try again:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### 1.3 Install the dependencies
```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

| Package | Version | What it's for |
|---|---|---|
| alpaca-py | 0.45.0 | Alpaca's official Python SDK |
| pandas | 3.1.1 | Tables of price bars (used for indicators later) |
| numpy | 2.5.5 | Fast maths for pandas |
| python-dotenv | 1.2.4 | Reads your keys from the `.env` file |
| SQLAlchemy | 2.1.9 | Talks to the SQLite database |
| streamlit | 1.67.0 | The dashboard in your browser |
| pytest | 9.2.0 | Runs the automated tests |
| tzdata | 2026.6 | Time-zone data (Windows has none built in) for New York market times |

---

## 2. Add your Alpaca PAPER keys

1. Sign in at <https://app.alpaca.markets>.
2. Switch to your **Paper** account using the account switcher at the top. Paper key IDs start with **`PK`**.
3. On the Paper dashboard, generate API keys. Copy the **Key ID** and the **Secret Key**.
   Alpaca shows the secret only once.
4. *(Optional)* To start with **$1,000**, reset the paper account from the Paper dashboard
   and set the balance to 1000. The app can't change your Alpaca balance; `STARTING_BALANCE`
   only tells the app what to expect.
5. Create your `.env` file from the example:
   ```powershell
   Copy-Item .env.example .env
   notepad .env
   ```
6. Replace the two placeholder values, save and close:
   ```
   ALPACA_API_KEY=PK...your key id...
   ALPACA_SECRET_KEY=...your secret...
   ALPACA_BASE_URL=https://paper-api.alpaca.markets
   TRADING_MODE=paper
   STARTING_BALANCE=1000
   ```

`.env` is listed in `.gitignore`, so git won't commit it. Never paste your keys into code,
chat or screenshots.

---

## 3. Run it

Run every command from the `options-bot` folder with the venv active.

### 3.1 Connection test (stage 2)
```powershell
python -m options_bot.connection_test
```
It checks each step and stops at the first problem:
```
================================================================
  ALPACA CONNECTION TEST  |  PAPER TRADING ONLY  |  orders DISABLED
================================================================

  [PASS] Load settings (.env): paper mode, keys loaded (hidden)
  [PASS] Paper endpoint check: https://paper-api.alpaca.markets
  [PASS] Account (GET /v2/account): status ACTIVE
  [PASS] Market clock (GET /v2/clock): CLOSED (next open Fri 2026-11-27 09:30 EST)

  Account:       ********1234
  Status:        ACTIVE
  Equity:        $1,000.00
  Buying power:  $...
  Cash:          $1,000.00
  Market:        CLOSED (next open Fri 2026-11-27 09:30 EST)

CONNECTION SUCCESS: connected to the Alpaca PAPER trading API.
```
If something is wrong it ends with `CONNECTION FAILED:` and the reason, for example missing
keys, live keys, wrong keys (HTTP 401/403) or no internet. Your keys are never printed.
Exit codes: `0` success, `2` settings problem, `3` Alpaca problem.

### 3.1b Health check (command line)
```powershell
python -m options_bot
```
You should see the paper banner followed by your account:
```
================================================================
  PAPER TRADING ONLY  |  simulated money  |  orders DISABLED
  Endpoint: https://paper-api.alpaca.markets
================================================================
Account:              ********1234
Status:               ACTIVE
Cash:                 $1,000.00
Equity:               $1,000.00
Buying power:         $...
Options buying power: $...
Options level:        ...
Market:               OPEN (closes Wed 2026-11-25 16:00 EST)
```
Exit codes: `0` OK, `2` settings problem, `3` Alpaca problem, `4` database problem.

### 3.2 Dashboard
```powershell
streamlit run dashboard/app.py
```
Your browser opens <http://localhost:8501>. Only your own computer can open it. The orange
bar at the top is the paper-trading indicator. The dashboard has no trading buttons.

### 3.3 Tests
```powershell
pytest
```
Expected: `117 passed, 1 skipped`. The skipped test is the live connection test. To run it
against your real **paper** account:
```powershell
$env:ALPACA_API_KEY = "PK..."; $env:ALPACA_SECRET_KEY = "..."
pytest -m integration -v
Remove-Item Env:ALPACA_API_KEY, Env:ALPACA_SECRET_KEY
```

---

## 4. How it's built (plain-English tour)

```
options-bot/
├─ options_bot/              the Python package (all the real code)
│  ├─ config.py              reads .env, checks every value, enforces PAPER mode
│  ├─ errors.py              our own error types (settings vs Alpaca vs orders)
│  ├─ logging_setup.py       screen + file logging, with secrets removed
│  ├─ main.py / __main__.py  the "python -m options_bot" health check
│  ├─ connection_test.py     the "python -m options_bot.connection_test" check
│  ├─ broker/
│  │  └─ alpaca_client.py    read-only Alpaca paper client (orders blocked)
│  ├─ db/
│  │  ├─ models.py           tables: signals, orders, positions, trades
│  │  ├─ database.py         opens SQLite, creates tables, sessions
│  │  └─ repository.py       simple save/load helpers
│  └─ strategy/              empty: indicators arrive in a later stage
├─ dashboard/app.py          Streamlit dashboard
├─ tests/                    pytest tests (config, database, broker, logging)
├─ .streamlit/config.toml    dashboard runs on localhost only
├─ data/                     SQLite file is created here (not committed)
├─ logs/                     options_bot.log is written here (not committed)
├─ .env.example              template for your .env (no real values)
├─ requirements.txt          exact package versions
└─ pytest.ini                test settings
```

**Configuration (`config.py`).** Think of it as the gatekeeper. It reads `.env` (real
environment variables win over the file) and checks every value *before* anything connects.
It stops the program ("fails closed") if:
- `TRADING_MODE` is anything other than `paper`;
- `ALPACA_BASE_URL` (or the older `APCA_API_BASE_URL`) is anything other than
  `https://paper-api.alpaca.markets` (a trailing `/v2` is allowed). That includes the live URL,
  `http://`, look-alike hosts and extra ports;
- the key ID starts with `AK` (live) or doesn't start with `PK` (paper);
- a key is missing or still the example placeholder.

Your keys are wrapped in a `Secret` object that prints as `********`. Order submission is a
hard-coded constant, `ORDER_SUBMISSION_ENABLED = False`. No setting can turn it on.

**Broker client (`broker/alpaca_client.py`).** It creates alpaca-py's `TradingClient` with
`paper=True`, which uses the paper URL. It then checks the URL the client actually ended up
with, and disables every method that can change anything: `submit_order`, `replace_order_by_id`,
`cancel_order(s)`, `close_position(s)`, `exercise_options_position`, account configuration,
watchlist edits, and the raw `post/put/patch/delete` calls they all use underneath. The only
things you can do are `get_account_summary()` (`GET /v2/account`: status, equity, buying
power, cash), `get_market_clock()` (`GET /v2/clock`: open or closed, next open and close, in
New York time) and read `endpoint`, which re-checks the paper URL each time. Errors become
clear messages such as "Alpaca rejected the credentials, make sure they are PAPER keys", and
never include your keys.

**Database (`db/`).** One file, `data/options_bot.db`. Each table is a Python class. Money is
stored exactly (`1.10` stays `1.10`). The database itself refuses any order, position or trade
row whose `is_paper` isn't true, and refuses impossible values (negative price, RSI over 100,
duplicate order IDs).

**Logging (`logging_setup.py`).** Messages go to the screen and to `logs/options_bot.log`
(rotated at 1 MB, 5 copies kept). A filter removes your exact key values, and anything shaped
like an Alpaca key or a `secret=...` pair, before a line is written. That includes error
tracebacks.

**Tests (`tests/`).** 117 automated checks. Config tests try live URLs, live keys, live mode and
bad values. Database tests save and load every table and try to break the safety rules.
Broker tests use a fake Alpaca client (no network) and also build the real alpaca-py client
to prove it targets the paper URL and that every write method is blocked. One test fails if a
future alpaca-py version adds a new write method we haven't blocked.

---

## 5. Troubleshooting

| Message | Fix |
|---|---|
| `ALPACA_API_KEY is missing` | Create `.env` (step 2) in the `options-bot` folder. |
| `looks like a LIVE key` | You copied keys from the Live account. Switch to Paper and generate paper keys. |
| `Alpaca rejected the credentials (HTTP 401/403)` | Keys are wrong, incomplete or regenerated. Copy them again from the Paper dashboard. |
| `Could not reach Alpaca paper API` | Check your internet, VPN or firewall. |
| `running scripts is disabled` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `No module named options_bot` | Run commands from the `options-bot` folder with the venv active. |

---

## 6. Official Alpaca references

- Alpaca docs home (see the *Paper Trading*, *Authentication* and *Options Trading* sections): <https://docs.alpaca.markets/>
- Account endpoint (`GET /v2/account`): <https://docs.alpaca.markets/reference/getaccount>
  (this is the link alpaca-py itself uses)
- Market clock (`GET /v2/clock`): alpaca-py `TradingClient.get_clock()`
- alpaca-py SDK source: <https://github.com/alpacahq/alpaca-py>

Every endpoint in this project comes from alpaca-py 0.45.0's own code, not from memory:
`BaseURL.TRADING_PAPER = "https://paper-api.alpaca.markets"`,
`BaseURL.TRADING_LIVE = "https://api.alpaca.markets"` (always refused), and
`TradingClient.get_account()` calls `GET /account` on the `/v2` API.
