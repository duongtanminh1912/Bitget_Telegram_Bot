# Bitget Telegram Bot — Starter v0.1

Python 3.12 paper trading and market observation for Duong Tan Minh. **Simulation and research only. No real-money trading.** The application does not require or accept Bitget API keys and has no exchange order-placement endpoints. Setting `TRADING_MODE=live` prevents startup.

The basic paper engine is deterministic. The optional research pipelines add BTCUSDT M15 models and prospective forward testing, described in sections 8–11.

## 1. Run the offline demo

Open a terminal in the `Bitget_Telegram_Bot` directory:

```bash
python3 -m bot.demo
python3 -m unittest discover -s tests -v
```

The demo proposes a simulated long position, approves it, and simulates a take-profit exit. Its price of 100 is test data, not a BTC quote. The basic demo and engine require no third-party Python packages. ML-specific tests are skipped when their optional dependencies are unavailable.

## 2. Configure Telegram

1. Open the official `@BotFather` account on Telegram, send `/newbot`, choose a name, and obtain the bot token. Keep the token on your machine.
2. Send `/start` to your new bot to open a private conversation.
3. Obtain your Telegram user ID and private chat ID from an update returned by your bot's `getUpdates` method. These IDs are usually equal in a private chat; use the actual values returned. See the official documentation below. Remove any existing webhook before using long polling. Do not run two polling instances for the same bot.
4. Copy `.env.example` to `.env` and fill in `TELEGRAM_BOT_TOKEN`, `TELEGRAM_USER_ID`, and `TELEGRAM_CHAT_ID`. Do not commit `.env` or share it in chat or on GitHub.

```bash
cp .env.example .env
# Edit .env with your text editor

docker compose up -d --build
docker compose logs --tail=50 -f
```

No HTTP ports need to be exposed. The `paper-data` volume preserves balances, positions, signals, the Telegram offset, and audit logs across restarts. `docker compose down` preserves the volume; adding `-v` deletes the simulated account data. Run only one instance per paper volume.

Without Docker, export the variables from `.env` through your terminal or IDE and set `DB_PATH` to `paper.db` in a writable directory. Direct execution does not automatically load `.env`. Then run `python3 -m bot.main`.

### Retrieve IDs without putting the token in shell history

Stop any polling instances, send a new message to your bot in a **private chat**, and run the following snippet. Token input is hidden. Only user and chat IDs are printed, not message contents. Keep the token private.

```bash
python3 - <<'PY'
from getpass import getpass
from bot.main import request

token = getpass('Telegram bot token: ').strip()
try:
    base = 'https://api.telegram.org/bot' + token + '/'
    hook = request(base + 'getWebhookInfo', {})
    if not hook.get('ok'):
        print('Bot authentication failed; check the token.')
    elif hook['result'].get('url'):
        print('The bot has a webhook. Remove it before using polling.')
    else:
        result = request(base + 'getUpdates', {'timeout': 0, 'allowed_updates': ['message', 'callback_query']})
        if not result.get('ok'):
            print('Could not retrieve updates; check the token and other polling instances.')
        found = False
        for update in result.get('result', []):
            message = update.get('message', {})
            if message.get('chat', {}).get('type') == 'private':
                print('TELEGRAM_USER_ID=' + str(message['from']['id']))
                print('TELEGRAM_CHAT_ID=' + str(message['chat']['id']))
                found = True
        if result.get('ok') and not found:
            print('No private message found. Send a new message to the bot and try again.')
except Exception:
    print('Could not connect to Telegram; check the network/token. Do not share token-bearing URLs.')
PY
```

Enter your own IDs and token in `.env`. For Docker, keep `TRADING_MODE=paper` and `DB_PATH=/app/data/paper.db`. No Bitget API key is needed. If several people have messaged the bot, select your own user/chat ID pair.

To run directly using a `.env` file you have edited yourself, first change `DB_PATH` to `paper.db`:

```bash
set -a
source .env
set +a
python3 -m bot.main
```

Commands such as `/help`, `/status`, `/nap`, and `/von` do not require Bitget quotes. `/demo long`, `/demo short`, approvals, and SL/TP checks require access to Bitget's public market API. `python3 -m bot.demo` always runs offline.

## 3. Try the Telegram paper workflow

```text
/help
/status
/nap 200
/von 250
/demo long
```

The initial simulated balance is 100 USDT. `/nap 200` adds 200 simulated USDT; `/von 250` allocates a 250 USDT sizing budget. Press the paper-approval button within 60 seconds. The bot refreshes the Bitget quote, recalculates quantity, and stores a simulated position. Use `/status` to inspect it. Try `/demo short` when no position is open.

`/demo` manually creates a test signal with an approximately 1% stop loss and 2% take profit. It is not an investment strategy or an AI prediction. The basic demo does not generate signals every 15 minutes; optional research and observation services are described later.

| Command | Purpose |
|---|---|
| `/nap 200` | Add simulated funds; no real deposit |
| `/rut 20` | Remove simulated funds; no real withdrawal |
| `/von 50` | Change the budget within available simulated cash |
| `/status`, `/pnl` | Show account status and PnL at the latest stored price |
| `/pause` | Stop new paper signals, clear pending signals, and continue position protection |
| `/resume` | Resume operation without clearing a daily loss halt |
| `/demo long`, `/demo short` | Create manual test signals using a public Bitget quote |

A manual emergency-close command has not been implemented and would be needed before any live trading work.

## 4. Paper risk rules

- Planned risk per trade is 0.5% of the smaller of the budget and simulated equity.
- Quantity equals the loss budget divided by entry-to-stop distance plus fee/slippage reserves, capped at 1x available capital. Quantity is rounded down to six decimal places. This is a simulation rule and does not apply Bitget contract specifications.
- Only one position may be open. Only the configured Telegram user ID and chat ID may issue commands or approve signals.
- Signals expire after 60 seconds. Approval rejects price drift above 0.1%, quotes older than 10 seconds, and future-dated quotes.
- The daily loss limit is 15% of the day's reference equity, including realized PnL, unrealized PnL, and simulated fees. Reaching it closes the simulated position and blocks new entries.
- The day rolls over at 00:00 `Asia/Ho_Chi_Minh` when a valid tick is received. If the bot is offline at midnight, the first valid tick after restart establishes the baseline; exact midnight equity cannot be reconstructed.
- `/von` does not reset the daily baseline or clear a halt. Simulated deposits/withdrawals adjust cash and baseline by the same amount so cash flow is not counted as profit; this also changes the absolute value of the 15% limit. An existing halt remains until the next day. Budget changes and cash flows require a flat account.
- Polling uses last-trade prices rather than mark prices. SL/TP protection runs locally and cannot operate while the bot is stopped or disconnected. Price gaps can produce losses larger than planned.

The basic engine assumes fees of 0.06% and slippage of 0.05% **per side; these are not Bitget's published fee schedule**. It does not include funding, a separate spread model, liquidation, actual leverage, or contract limits. Do not interpret its PnL as proof of profitability. The 15% daily limit is a user-requested setting, not a recommended risk level. The V2/V3 research pipelines include funding as described below.

## 5. Project structure

```text
bot/core.py          Paper balances, positions, risk rules, and SQLite transactions
bot/main.py          Telegram polling and public Bitget market prices
bot/demo.py          Offline demo
tests/               Engine, Telegram authorization, research, and forward-test checks
Dockerfile           Basic Python runtime without third-party dependencies
compose.yaml         Paper service with persistent account storage
.env.example         Configuration template without secrets
```

The basic engine uses SQLite for local operation. It does not include PostgreSQL, FastAPI, a dashboard, or Prometheus. ML research lives in the optional `research/` package. Audit records are stored in the `audit` table; state changes use SQLite transactions to prevent duplicate approvals and preserve account state across restarts.

## 6. Work required before real-money trading

1. Introduce PostgreSQL, migrations, and transaction locking if multiple workers need to share account state.
2. Maintain 15-minute candle storage, baseline strategies, chronological backtests, realistic fees/funding, and checks for look-ahead bias.
3. Train and evaluate ML models against baselines without promising profitability.
4. Read actual balances and identify Classic/UTA account type, quantity increments, tick size, minimum order, margin mode, and exchange limits. Do not automatically allocate the entire account to the bot.
5. Implement an order adapter with client order IDs, partial-fill reconciliation, ambiguous-timeout recovery, confirmed exchange-side SL/TP, reduce-only orders, and an emergency-close control.
6. Reconcile real cash flows against transfer history, maintain a durable daily baseline, use mark prices for PnL, and track funding and position ownership.
7. Test exchange demo execution, network failures, restarts, duplicate orders, stale approvals, rejected SL orders, and loss limits before considering live trading with limited capital.

The research functionality below addresses parts of the data/model work. Exchange execution remains unimplemented.

## 7. Validation history and limitations

The initial expanded suite contained 22 automated tests covering position sizing, duplicate approvals, signal expiry, stale/drifting/future/out-of-order prices, long/short SL/TP, protection while paused, daily halts across restarts and budget changes, day rollover, invalid numbers, Telegram authorization, simulated cash flows, blank commands, malformed callbacks, live-mode rejection, and an offline Telegram flow with mocked APIs.

On November 3, 2026, the Docker image was built and started on the host, all 22 tests passed under Python 3.12, Telegram polling connected, and public Bitget quotes were received. Initial state was paper mode, 100 simulated USDT, and no open position. The basic service does not guarantee message delivery after transport errors or reconstruct every market tick missed while offline. It is not ready for real-money trading.

If sending a Telegram response fails after a command changes state but before the offset is saved, the update may be processed again, such as a repeated simulated deposit/withdrawal. Inspect `/status` after connection errors. Exactly-once processing is not implemented for all Telegram commands. Forward-test notifications have their own persistent event mechanism, described in section 10.

Official references used for the adapters:

- https://www.bitget.com/docs/catalog/classic-contract-market/classic-contract-market
- https://core.telegram.org/bots/api#getupdates
- https://core.telegram.org/bots/api#answercallbackquery

## 8. BTCUSDT M15 model research

The research pipeline is separate from the basic paper program and requires no Bitget key. Direct ML dependencies are pinned in `requirements-ml.txt`; the research image includes Python 3.12 and libgomp. To reproduce the pipeline:

```bash
python3 -m research.data --days 365

docker build -f Dockerfile.research -t bitget-paper-research .
docker run --rm -v "$PWD:/app" bitget-paper-research python -m unittest discover -s tests -v
docker run --rm -v "$PWD:/app" bitget-paper-research python -m research.train
docker run --rm -v "$PWD:/app" bitget-paper-research python -m research.predict
```

The collector saves `data/BTCUSDT_15m.csv` and a manifest with the additional suffix `.json`. It validates closed candles, duplicates, finite numbers, OHLC relationships, history coverage, and missing bars. Incomplete history must not silently become training data. Partial downloads are retained and merged/validated on subsequent runs. Each run still paginates the full requested period to verify coverage.

Features include returns over 1/4/16/96 bars, ATR14, candle range/body, relative volume, volatility, a finite-window EMA12/48 gap over 96 bars, slope, and H1 trend relative to a 24-hour SMA. H1 data is available only after all four constituent M15 bars close. Online and offline feature calculations match. Labels use returns from the next bar's open to the fourth bar's close, with a neutral band of `max(0.27%, 0.5 ATR/close)`. These are initial research hypotheses, not optimized settings.

Candidates are an EMA rule aligned with H1, Logistic Regression, and LightGBM. ML signals use a fixed, uncalibrated score threshold of 0.55. The first 80% of data is used for development and the final 20% for holdout evaluation. Three expanding walk-forward folds use a four-bar gap to remove label overlap across boundaries. Scaling is fitted on training data only. The candidate is selected by mean fold return, not reselected using the holdout.

Backtests use the paper engine with 100 initial USDT, 0.5% risk per trade, a 1x notional cap, and a 15% daily loss halt. Entry is at the next bar's open, SL distance is `max(1.5 ATR, 0.3% entry)`, TP distance is twice the SL distance, and the maximum holding period is four bars. If both barriers are touched in one bar, SL is processed first; opening gaps exit at the actual open. Costs include 0.06% fees and 0.05% slippage per side, plus a double-cost stress test. Funding, liquidity, approval latency, and the exact intrabar price path are excluded from this version. Drawdown uses end-of-bar equity, not every intrabar movement.

Outputs:

- `artifacts/report.md` and `report.json`: results, assumptions, and the data hash.
- `artifacts/evaluated.joblib`: the snapshot used for holdout evaluation.
- `artifacts/model.joblib`: a snapshot refitted on all resolved labels for future observation.

Load only artifacts generated by this trusted local pipeline; joblib is not safe for untrusted downloads. Data and model artifacts are excluded from Git. Classification accuracy does not establish profitability, particularly when neutral labels dominate.

Paper-proposal eligibility requires positive mean CV return, at least two positive folds out of three, at least 30 holdout trades, positive holdout return under normal and doubled costs, and holdout drawdown below 10%. Otherwise the model remains **observe_only** with no approval button for model-generated positions. This is a paper screening rule, not sufficient evidence for live trading. Once a holdout has been inspected, further tuning makes it development data; use a new period for subsequent evaluation.

Enable integration with the same paper service/volume, keeping only one polling instance:

```bash
docker compose -f compose.yaml -f compose.ml.yaml up -d --build
docker compose -f compose.yaml -f compose.ml.yaml logs --tail=50 -f
```

- `/model`: evaluation results and paper-proposal eligibility.
- `/predict`: a forecast based on the latest closed M15 candle.
- The model observes each closed bar once and records `model_forecast` audit events. It does not backfill historical signals. `/pause` stops automatic signals.
- An eligible model may propose a position only during the first minute after the signal candle closes. Telegram approval is still required within 60 seconds. SL/TP uses ATR; position expiry is persisted and checked across pauses/restarts. If expiry occurs while disconnected, the next valid tick closes the position.
- Models older than 14 days or missing the latest closed candle cannot forecast/propose. Collect and retrain, then restart the service to load the new artifact.
- `/demo long` and `/demo short` remain manual tests independent of ML results.

The first run on November 3, 2026 used 35,040 continuous candles covering 365 days. LightGBM was selected but remained **observe_only**: only one trade occurred across all three folds, and none in the holdout. No trading edge was established. See `artifacts/report.md` for full results.

At that stage, all 37 tests passed in the deployed Python 3.12 image. Checks included causal and matching online/offline features, pagination without missing bars, stop-first execution when both barriers are touched, costs, expiry across restart/pause, no proposals from observe-only models, and approval before opening a paper position. The deployed bot recorded M15 forecasts in its audit log and retained prior paper state.

Implementation references: [TimeSeriesSplit and gap](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html), [LightGBM Python](https://lightgbm.readthedocs.io/en/stable/Python-Intro.html).

## 9. V2 — trade outcomes and prospective validation

V2 artifacts live in `artifacts/v2`, separate from V1 and the paper wallet. The learning target is **net trade profitability after SL/TP or timeout**, rather than an up/down/neutral label. The dataset also retains a TP-before-SL flag for analysis. Logistic/Ridge and LightGBM estimate win probability and expected net return for both long and short outcomes. Probabilities are calibrated with a sigmoid on a chronological segment after training. The fixed filter requires win probability >=55% and expected net return >=0.03%; thresholds are not lowered in response to the final diagnostic block.

The study uses 84 days with complete M1 and funding coverage; the funding API returned approximately 90 days. It downloaded 120,960 M1 candles, checked their aggregated OHLC against M15, and generated 15,042 executable long/short examples. Labels and replay include a one-minute approval delay, rejection for price drift >0.1%, fees/slippage, stop-first ordering if both barriers are touched in the same minute, and actual funding rates using M1 close as a mark-price proxy. Funding at the exact entry time is excluded; positions held through settlement/expiry are charged once. Liquidity and the price path within a minute are not fully modeled.

```bash
python3 -m research.microdata --days 84
python3 -m research.funding

docker run --rm -v "$PWD:/app" bitget-paper-research python -m research.improve
docker run --rm -v "$PWD:/app" bitget-paper-research python -m research.improve --horizon 240
```

`artifacts/v2/report.md` covers a maximum one-hour hold; `artifacts/v2_240/report.md` covers a maximum four-hour hold. Both use M15 signals. The first two evaluation windows select the candidate; the final window provides diagnostics. This period was already viewed in earlier research, so results are explicitly **exploratory historical analysis**, not a fresh untouched holdout. V1/V2 accuracy cannot be compared directly because labels and periods differ. Brier scores against a constant calibration-period win-rate forecast assess probability quality, not trading profitability.

The one-hour configuration produced no qualifying trades. The four-hour configuration produced one winning trade during candidate selection and none in the final diagnostic block. This is insufficient evidence of improved trade win rates. All V2 artifacts keep `paper_proposals_enabled=false`; no automatic promotion to order placement is implemented.

Run the independent prospective observation service:

```bash
docker compose -f compose.research.yaml up -d --build
docker compose -f compose.research.yaml logs --tail=20
```

This service receives no Telegram/Bitget credentials and does not mount the paper wallet volume. It records forecasts during the first minute after each M15 close, only for bars after the research period. It does not backdate predictions after observing subsequent prices. Both directions are retained as controls, with at most one direction passing the filter. After one hour, outcomes are scored using M1 and funding and stored in `data/shadow/forward.db`. Samples overlap in time and represent hypothetical unit-position outcomes, **not portfolio PnL**. Statistics are separated by model hash.

Models older than 14 days stop recording new predictions. Retrain, retain a new version, and restart the service. Telegram `/model` and `/predict` still refer to V1; V2 is observed separately. To inspect newly recorded samples:

```bash
docker compose -f compose.research.yaml exec -T shadow python -c 'from research.shadow import Shadow; print(Shadow("/app/artifacts/v2", "/app/shadow/forward.db").summary())'
```

Further progress requires evaluating predictions frozen before their outcomes are known. Changes to data, features, SL/TP, or thresholds should be versioned and evaluated separately. Do not include historical research results in prospective win-rate statistics.

## 10. Monitor V2 forward tests through Telegram

With `compose.yaml` and `compose.ml.yaml`, the bot reads the V2 ledger through a **read-only** mount. The V2 service records state and notification events in the same SQLite transaction. Telegram reads events and saves its cursor after successful delivery. Connection failures are retried. A timeout after Telegram accepts a message can cause duplicate notifications, but does not create a trade.

```bash
docker compose -f compose.research.yaml up -d --build
docker compose -f compose.yaml -f compose.ml.yaml up -d --build
```

Telegram commands:

- `/forward`: service heartbeat, recorded/scored/rejected samples, net win rate, and mean net return, separating controls from qualifying signals and preferred directions.
- `/predict2`: the latest V2 forecast recorded before subsequent price action, including estimated profitability, reference price, SL/TP, and expiry. Old forecasts are not recalculated using new prices.
- `/results`: up to four recent preferred-direction results for the current model version. Rejected price-drift samples are not counted as losses.
- `/model2`: V2 objectives and evaluation limitations.
- `/pause`: stop automatic notifications while V2 continues collecting/scoring data to avoid sample selection bias. Notifications during the pause are skipped, but records remain accessible through `/predict2`, `/results`, and `/forward`. `/resume` enables new notifications.

The worker stores both long and short forecasts for each closed candle. Following the single-direction presentation update below, automatic notifications show only the preferred direction and its eventual result. V2 notifications contain no order-approval or position-opening controls. Configuring `FORWARD_DB` disables automatic V1 messages; `/model` and `/predict` still query V1 manually.

Read net win rates together with sample counts and costs. Recorded samples are not actual exchange trades; control directions and consecutive periods may overlap. Do not sum sample returns into portfolio profit or drawdown. With no scored samples, the bot reports insufficient data rather than a 0% win rate.

On November 3, 2026, the first live-market forecast pair was confirmed recorded at **22:15:07 Asia/Ho_Chi_Minh**, before its hypothetical 22:16 entry. Neither direction passed the filter. Its evaluation deadline was 23:15, with scoring dependent on complete M1 and funding data. This established recording before outcomes, not a trade win rate.

At that stage, 74 tests passed on the deployed image. Read-only SQLite access, cursor advancement after successful delivery, and an actual `/forward` status message to the configured Telegram chat were verified. The first validation snapshot contained two controls, zero scored samples, and zero qualifying signals; no prospective win rate was available then.

### One plan: direction, leverage, SL, and TP

V2 notifications and `/predict2` display **one preferred direction**. A qualifying direction takes priority. Otherwise, the higher expected net return wins, followed by higher win probability when tied. An exact tie uses a deterministic side-name ordering without consulting future outcomes. This changes presentation and preferred-direction scoring; it does not train a new model with a different win rate.

Displayed leverage is **fixed at 1x**, not optimized or learned by the model. SL distance from the reference price is `max(1.5 ATR14, 0.3% price)` and TP distance is twice that; short levels reverse the long arrangement. The reference belongs to the closed signal candle and is not a current entry quote. Unqualified plans remain explicitly labeled as observation-only and do not create orders.

`/results` and automatic result notifications show only each bar's preferred direction. `/forward` includes a preferred-direction group for measuring one choice per bar, while retaining separate qualifying-signal and two-direction control groups. The worker preserves both original forecasts without changing stored scores or outcomes. Consecutive preferred directions may still overlap and do not represent portfolio PnL.

## 11. V3 — common technical indicators

V3 adds **RSI14, MACD12/26/9, Bollinger Bands20/2, ADX14 and DI+/DI-, Stochastic14/3/3, OBV, rolling VWAP20, and MFI14** using TA-Lib 0.6.8. Combined with the 14 base features and directional interactions, it uses 42 inputs. These are transformations of price and volume, not independent information sources such as order books or news.

Each indicator is computed with TA-Lib on exactly 200 closed bars available at prediction time; the active candle is excluded. EMA/Wilder initialization is reset within this window so training and online calculations match. Values may differ slightly from charts initialized using longer histories. The V3 online collector requests 300 candles to retain at least 200 closed bars after removing the active candle. OBV uses its 20-bar change normalized by volume; VWAP is a rolling 20-bar value, not session-anchored VWAP.

The matched comparison changes only features: examples/labels, LightGBM parameters, chronological calibration, SL/TP, latency, and costs are held constant. Results are saved in `artifacts/v3/report.md`, with per-fold trade details in CSV files in the same directory. Historical results remain exploratory.

Final diagnostic results when forcing one preferred direction per bar and replaying a single-position portfolio:

| Feature set | Trades | Net win rate | Simulated return |
|---|---:|---:|---:|
| V2 baseline | 538 | 19.70% | -60.57% |
| V3 with indicators | 540 | 18.33% | -61.73% |

Neither branch produced trades passing the probability/edge filter. Since this did not establish improvement, **V2 remains the default model** and V3 runs as a parallel observation experiment. Leverage stays at 1x, thresholds and SL/TP rules are unchanged, and real-money trading remains disabled.

```bash
docker build -f Dockerfile.research -t bitget-paper-indicators .
docker run --rm -v "$PWD:/app" bitget-paper-indicators python -m research.indicator_study
docker compose -f compose.research.yaml up -d --build shadow-indicators
docker compose -f compose.yaml -f compose.ml.yaml up -d --build
```

V3 records prospective data separately in `data/shadow/forward_v3.db`; its statistics are not mixed with V2. Telegram `/indicators` shows the experimental V3 plan, SL/TP, and RSI/ADX/MACD values frozen at prediction time. Until the next valid candle window, it reports that it is waiting rather than backdating a prediction. `/predict2` and automatic notifications remain on V2; V3 does not add a second automatic message stream.

All 88 tests passed, including TA-Lib and direct Bollinger/VWAP formula checks, no future-data leakage, matching online/offline calculations over 200-bar windows, finite outputs under constant prices/volumes, compatibility with older model schemas, and frozen indicator snapshots instead of recalculation using later prices.

Formula/library references: [TA-Lib momentum](https://ta-lib.github.io/ta-lib-python/func_groups/momentum_indicators.html), [Bollinger Bands](https://ta-lib.github.io/ta-lib-python/func_groups/overlap_studies.html), [TA-Lib 0.6.8](https://pypi.org/project/TA-Lib/0.6.8/).
