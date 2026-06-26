# Session Levels — PickMyTrade + TradingView + Tradovate Setup

**Automate Session Levels strategy alerts to Tradovate via PickMyTrade**

*Generated for MNQ / Session_Levels_Strategy.pine*

---

## Overview

```
TradingView Strategy → Alert (webhook) → PickMyTrade → Tradovate order
```

TradingView decides **when** to trade. PickMyTrade decides **how** to route the order to Tradovate.

---

## Prerequisites

| Requirement | Why |
|-------------|-----|
| **TradingView Pro, Pro+, or Premium** | Webhook alerts are not available on free plans |
| **PickMyTrade account** | Routes alerts to your broker |
| **Tradovate account** (demo or live) | Connected via OAuth in PickMyTrade |
| **Session Levels** on chart | Your `strategy()` script (recommended: **MNQ1!**, 5m) |

**Helpful docs**

- [Automate TradingView Strategies (PickMyTrade)](https://docs.pickmytrade.trade/docs/automate-tradingview-strategies/)
- [TradingView Alerts Setup (PickMyTrade)](https://docs.pickmytrade.trade/docs/tradingview-alerts-setup/)

---

## Step 1 — Connect Tradovate in PickMyTrade

1. Log in at **https://pickmytrade.trade**
2. Go to **Accounts** (or broker settings).
3. Click **Connect to Tradovate**.
4. Complete **OAuth** login with Tradovate.
5. Start with a **Demo / Sim** account until fills match expectations.
6. Confirm **market data** is active on Tradovate (missing data can cause order failures).

> You do not need to buy separate Tradovate API access. PickMyTrade handles vendor connectivity.

---

## Step 2 — Generate the alert in PickMyTrade

1. Open **Create Alert** or **Generate Alert** in the PickMyTrade dashboard.
2. Choose **Strategy-based** automation (not indicator-only).
3. Select your **Tradovate account** (demo first).
4. Configure **symbol**:
   - Set **MNQ** if the chart uses NQ but you trade micros.
   - Leave blank to use the chart symbol (e.g. MNQ1!).
5. Configure **exit handling** for Session Levels:

   Your script manages its own exits:

   - 2R partial (`strategy.close`)
   - Bracket stop + TP
   - Trail stop
   - 2PM flatten

   In PickMyTrade, select **strategy-managed exits** / **multiple exits**.

   **Do not** attach PickMyTrade SL/TP on top — that double-manages risk and diverges from backtests.

6. Set **quantity** to your live size (e.g. 5 or 10 contracts — not backtest scale).
7. Click **Generate Alert**.
8. **Copy the JSON** (alert message).
9. **Copy the Webhook URL** (from your dashboard — use the exact URL provided).

---

## Step 3 — Create the alert in TradingView

1. Open the chart with **Session Levels** loaded.
2. Click **Alert** (+).
3. **Condition:** Session Levels (strategy name).
4. **Options:**
   - **Once per bar close** (matches `process_orders_on_close=true` in Pine).
   - Do not use “every tick”.
5. **Notifications** tab:
   - Enable **Webhook URL**.
   - Paste the PickMyTrade webhook URL exactly (no spaces or extra characters).
6. **Message** tab:
   - Paste **only** the JSON from PickMyTrade.
   - Default JSON uses `{{strategy.order.action}}` — keep unless PickMyTrade docs specify otherwise.
7. Click **Create**.

One strategy alert covers entries **and** exits (`strategy.entry`, `strategy.close`, `strategy.exit`).

---

## Step 4 — Verify before going live

1. **PickMyTrade → Alert logs** — Did the alert arrive? Was JSON valid?
2. **Tradovate demo** — Correct symbol, side, and quantity?
3. Test a **partial** (`2R Partial`) and **trail** exit — exits must come from strategy alerts if Pine manages them.
4. Remember: PickMyTrade strategy automation uses **market orders** at alert time, not Pine limit prices.

---

## Session Levels — live trading notes

| Script behavior | Live implication |
|-----------------|------------------|
| Entries at bar **close** | Up to one bar delay on 5m (e.g. 5 minutes) |
| Partial via `strategy.close` | Separate alert legs; use strategy-managed exits in PMT |
| Bracket + trail in Pine | Do not duplicate SL/TP in PickMyTrade |
| Entry filters (`canTrade`) | No alert when filtered — expected |
| 2PM CT flatten | Should fire a close alert on flatten bar |

**PickMyTrade strategy type:** Use **Flat position** (script only enters when flat). Avoid continuous always-in-market mode unless intended.

---

## Troubleshooting

| Symptom | Likely fix |
|---------|------------|
| Alert fires, nothing in PickMyTrade | Wrong webhook URL or malformed JSON |
| PickMyTrade error, no order | Symbol not mapped (MNQ vs NQ) |
| Wrong contract size | Set quantity in PickMyTrade alert config |
| Double stops / weird exits | Disable PickMyTrade SL/TP; let Pine handle exits |
| No webhook at all | Upgrade TradingView to Pro+ |

---

## Recommended rollout

1. **Tradovate demo** + **1 MNQ** + PickMyTrade.
2. Run **one week** comparing PickMyTrade logs vs Strategy Tester.
3. Scale size only after partials, trails, and flatten behave correctly.
4. Use **live** only when demo matches intent.

---

## Quick checklist

- [ ] TradingView Pro+ (webhooks enabled)
- [ ] Tradovate connected in PickMyTrade (demo first)
- [ ] Symbol set (MNQ if needed)
- [ ] Exit handling = strategy-managed (no PMT SL/TP)
- [ ] Live quantity configured in PickMyTrade
- [ ] Webhook URL pasted in TV alert Notifications
- [ ] JSON pasted in TV alert Message (only JSON)
- [ ] Alert = Once per bar close
- [ ] Test entry, partial, stop, trail, and 2PM flatten on demo

---

*Project: mnq-fvg-backtest · Script: tradingview/Session_Levels_Strategy.pine*
