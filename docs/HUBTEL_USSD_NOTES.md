# Hubtel Programmable Services (USSD) — notes

Source: pasted by the project owner from Hubtel's developer docs
(`api-reference-prog-services` and the `Programmable Services` reference
page), most recently updated 26 Nov 2026. These notes are the source of
truth for the stub endpoints in `app/routes/hubtel.py`. Anything Hubtel's
docs didn't give us is listed under **Open items** below and must be
verified before real voting logic is built on top of this stub.

## Request Hubtel sends to our Service Interaction URL

`POST` with a JSON body:

| Field | Meaning |
|---|---|
| `Type` | **CONFIRMED (26 Nov 2026):** `"Initiation"` (first message of a session), `"Response"` (later message), or `"Timeout"` (the user cancelled/the session timed out). Compared case-insensitively in `app/services/ussd.py`. `"Release"` is handled the same as `"Timeout"` (both end the session, create no transaction) since some Hubtel docs use that name for the same event. An unknown `Type` must never cause a 500 -- it ends the session politely instead (see `handle_interaction`) |
| `Message` | What the user typed. On `Initiation` over USSD, this is the dialed string |
| `ServiceCode` | The dialed short code, or a service id |
| `Operator` | For USSD: one of `"tigo"`, `"airtel"`, `"mtn"`, `"vodafone"` |
| `ClientState` | Data we asked Hubtel to echo back from our previous reply. Arrives only on the *next* request, then is discarded |
| `Mobile` | The user's phone number, e.g. `233200585542` |
| `SessionId` | Unique id of the session |
| `Sequence` | Integer — position of the message in the session |
| `Platform` | **CONFIRMED (26 Nov 2026):** `"USSD"`, `"Webstore"` or `"Hubtel-App"`. We never assume USSD -- every response always carries all the mandatory fields below regardless of platform, and messages stay plain GSM-safe text. `Type` and `Platform` are logged (no personal data) for every interaction |

## Response we must return from the Service Interaction URL

JSON body:

| Field | Required? | Meaning |
|---|---|---|
| `SessionId` | Mandatory | Same value as the request |
| `Type` | Mandatory | `"response"` keeps the session open, `"release"` ends it, `"AddToCart"` ends the session and sends the user to checkout to pay |
| `Message` | Mandatory | Text shown to the user. `"\n"` is a new line; options are written as text, e.g. `"\n1. Confirm"` |
| `Label` | Mandatory | A title (used by the web and app channels) |
| `DataType` | Mandatory | One of `"display"`, `"input"`, `"confirm"`, `"select"` |
| `FieldType` | Mandatory | One of `"text"`, `"phone"`, `"email"`, `"number"`, `"decimal"`, `"textarea"` |
| `Mask`, `Item`, `ServiceCode`, `Data`, `Sequence`, `ClientState` | Optional | `Item` is only used with `AddToCart` and must be empty otherwise. `Data` is used with `confirm` and `select` |

Example shape used by the stub (ends the session with a short message):

```json
{
  "SessionId": "<same as request>",
  "Type": "release",
  "Message": "<event name>: voting opens soon",
  "Label": "<title>",
  "DataType": "display",
  "FieldType": "text"
}
```

VERIFY: whether a `"release"` response really needs `Label`, `DataType` and
`FieldType` filled in, or whether Hubtel ignores them once the session is
ending. The stub sends them anyway since the docs mark all three mandatory.

## AddToCart response

We return this when the user confirms their vote purchase. It ends the
USSD session and sends the user to Hubtel's checkout to pay:

```json
{
  "SessionId": "<same as request>",
  "Type": "AddToCart",
  "Message": "The request has been submitted. Please wait for a payment prompt soon",
  "Item": {
    "ItemName": "<short text>",
    "Qty": 1,
    "Price": 1.50
  },
  "Label": "<same text as Message>",
  "DataType": "display",
  "FieldType": "text"
}
```

`Price` is a decimal number of cedis (not pesewas), e.g. `1.50` for 150
pesewas.

## Transaction status check

```
GET https://api-txnstatus.hubtel.com/transactions/<COLLECTION_ACCOUNT>/status?clientReference=<reference>
Authorization: Basic <base64 of API id:secret>
```

Our reading is that `clientReference` is the USSD `SessionId`. **VERIFY.**

**CONFIRMED (26 Nov 2026):** the status word is one of `"Paid"`,
`"Unpaid"` or `"Refunded"`:
- `"Paid"`: exactly as before -- confirm the amount matches, record the
  vote, send the final callback.
- `"Unpaid"`: not paid yet. Treated exactly like `"pending"` -- no vote,
  no failure, stays pending, the sweep checks again later. Never marked
  `"failed"` just for being `"Unpaid"`.
- `"Refunded"`: if no vote exists yet, flagged `needs_review` with reason
  `"refunded by Hubtel"` and no vote is created. If a vote already
  exists, flagged `needs_review` with reason `"refunded after vote was
  recorded"` and the vote is left exactly as it is -- reversing it is an
  organisers' decision, not an automatic one. No final callback is sent
  either way. See `process_hubtel_payment` in
  `app/services/hubtel_fulfilment.py`.
- Anything else: `"unknown"`, logged safely (no personal data), never
  treated as `"paid"`.

**SUPERSEDED (see 28 Nov 2026 entry below) -- kept for history only:** an
earlier "CONFIRMED" note here claimed the amount fields were flat,
capitalized top-level fields (`Amount`/`Charges`/`AmountAfterCharges`,
no envelope). That claim was wrong, and every test mock in the repo
copied it -- which is exactly how a real production bug (a genuinely
paid transaction parsing as `"unknown"`) shipped without any test
catching it. See the entry below for the shape actually confirmed by a
real capture, and the "Testing discipline" note at the end of this
section for how we're making sure that doesn't happen again.

**CONFIRMED (28 Nov 2026, real capture -- a genuinely paid transaction's
status-check response, saved verbatim at
`tests/fixtures/hubtel_status_paid_REAL.json`):**

```json
{
  "message": "Successful",
  "responseCode": "0000",
  "data": {
    "status": "Paid",
    "transactionId": "1cde0454d1bf408cbce2005bc2228111",
    "amount": 1.01,
    "charges": 0.01,
    "amountAfterCharges": 1.0
  }
}
```

(trimmed to the fields that matter here -- see the fixture file for the
full real body). Note everything is **lowercase**, and nested under a
top-level `"data"` key, inside an envelope that also carries `"message"`
and `"responseCode"`. The previous entry's flat, capitalized shape (no
envelope at all) was never real.

- `responseCode` must be exactly `"0000"` for a `"Paid"` status word to
  be trusted at all -- this is Hubtel's own signal that the status-check
  call succeeded and `data` means what it says.
- The amount fields are `amount` (the gross amount the payer was
  actually charged, INCLUDING Hubtel's own fee), `charges` (Hubtel's fee
  alone) and `amountAfterCharges` (the net amount left once Hubtel's fee
  is deducted). For a GH₵1.00 vote fee, the real capture above is
  `amount: 1.01`, `charges: 0.01`, `amountAfterCharges: 1.0`. **The vote
  amount we compare against `Transaction.amount_pesewas` is
  `amountAfterCharges`, never `amount`** -- comparing against `amount`
  was a real bug that made a genuinely paid transaction look like an
  amount mismatch (flagged `needs_review`, stuck `'pending'`, no vote).
  `amount` is still read, as `provider_total_pesewas`, for reporting
  only. `app/providers/hubtel_adapter.py` also cross-checks that
  `amount - charges == amountAfterCharges` exactly, and treats a
  mismatch the same as an unreadable amount.
- The status-check response reports Hubtel's own id for the payment as
  `data.transactionId`, NOT `OrderId` -- `find_order_id_in_status_response`
  checks `OrderId` first (in case a different endpoint or future version
  uses it), then falls back to `transactionId`.
- Field names (`data` vs `Data`, `status` vs `Status`, etc.) are matched
  case-insensitively as a defensive safety net, but the casing above is
  what's actually been seen -- never rely on the case-insensitive
  fallback being the primary path.

**STILL UNKNOWN — VERIFY:**
- Whether the fields above are always present, or sometimes missing/null
  for a status other than `"Paid"` (the `"Unpaid"`/`"Refunded"` fixtures
  under `tests/fixtures/` are explicitly marked `_DOCUMENTED`, not real
  captures, until we see one).
- The fulfilment request body (still just logged, not parsed, beyond
  `SessionId`/`OrderId`).
- The final callback body.
- The maximum length of `ItemName`. We keep it under 40 characters as a
  conservative guess -- still unconfirmed.

**Testing discipline:** tests for Hubtel parsing must use real captured
bodies, never invented ones. A fixture file named `*_REAL*` must be a
genuine capture (or, where part of it genuinely isn't available, say so
honestly in its own `_note` field and leave that part out -- never
invent a plausible-looking placeholder). A fixture that's a stand-in for
something we haven't captured yet must be named `*_ASSUMED*` or
`*_DOCUMENTED*` and say so in its own `_note`. This is enforced by
`tests/test_hubtel_adapter.py::test_fixtures_are_honest`. The reason
this matters: every status-check mock in this repo used to invent the
same wrong, flat, capitalized shape, so nothing ever exercised the real
one -- which is exactly how the response above parsed as `"unknown"` in
production while every test stayed green.

## Service Fulfilment URL

Hubtel POSTs here after the user has paid (the "Service Payment Callback").
We're then meant to give the service value — for us, that means recording
the vote (not built yet; this step only stubs the endpoint).

- Request body fields: **NOT CAPTURED — VERIFY**
- The stub only logs the raw body and changes nothing else.

## Final callback (after fulfilling)

We must `POST` to:

```
https://gs-callback.hubtel.com:9055/callback
```

with exactly these fields:

```json
{"SessionId": "<session id>", "OrderId": "<order id>", "ServiceStatus": "success", "MetaData": null}
```

The example Hubtel gave us shows **no authorization header** -- our
reading is that our static IP being whitelisted (see Security below) is
the identity check here, not a header.

Sent only for a transaction that reached `'success'` (a vote was
recorded), only once, and only once we have its `OrderId` (from the
fulfilment request -- see below). See `app/services/hubtel_fulfilment.py`
for how "only once" is made safe against two overlapping attempts.

**CONFIRMED (26 Nov 2026):** Hubtel requires this callback within **one
hour** of receiving the fulfilment request (`fulfilment_received_at`).
That deadline lives in code as the named constant
`HUBTEL_CALLBACK_DEADLINE_MINUTES = 60`
(`app/services/hubtel_fulfilment.py`). The retry schedule, all measured
from `fulfilment_received_at`:
- Status-check retries (`flask hubtel-sweep`) for a still-pending
  transaction: every sweep run for the first 30 minutes, then every 5
  minutes, until 24 hours (then flagged `needs_review`).
- Final-callback retries for a `'success'` transaction: every sweep run
  for the first 10 minutes, then every 5 minutes, until 55 minutes (a
  5-minute safety margin before the real one-hour cutoff) -- after that,
  `send_final_callback` stops and sets `needs_review` with reason
  `"final callback not sent within one hour"` instead of retrying
  forever.
- `GET /api/admin/transactions` exposes `minutes_since_fulfilment` per
  transaction and a `?callback_overdue=1` filter (`'success'`, no
  `callback_sent_at`, more than 30 minutes since fulfilment) so this is
  visible to an admin before it becomes a real problem.

**STILL UNKNOWN — VERIFY:**
- What to send for a transaction that needed review instead (e.g. an
  amount mismatch, or a refund) -- we currently send nothing at all for
  those. Open question for Hubtel.
- Other `ServiceStatus` values besides `"success"` (what do we send when
  we *can't* fulfil?).
- The maximum time Hubtel waits for our fulfilment reply before it gives
  up / retries.
- Whether `OrderId` is present in the fulfilment request body itself, or
  only obtainable some other way.
- What actually happens on Hubtel's side to a payment if we never manage
  to send the final callback within the hour.

## Transaction Status Check

If we get no final status or callback within 5 minutes, we must verify by
sending a `GET` to Hubtel's Transaction Status Check endpoint, filling in
our Hubtel POS Sales ID and the `sessionId`.

- Full URL and response fields: **NOT CAPTURED — VERIFY**
- Not called by this stub.

## AddToCart `Item` structure

Fields for item name, quantity, price: **NOT CAPTURED — VERIFY**. Not
needed for this stub (it never returns `Type: "AddToCart"`).

## Security and testing

- Ask the assigned Hubtel engineer to whitelist our static IP so we can
  reach both of Hubtel's endpoints (the final callback and the status
  check).
- Testing: Hubtel's Simulator for the user flow, and a Hubtel POS device or
  a USSD code for the full purchase flow.
- **Incoming side (Service Fulfilment URL):** every Hubtel request is
  logged with its source IP (`HubtelLog.source_ip`, see
  `GET /api/admin/hubtel-log`). An optional allowlist,
  `HUBTEL_FULFILMENT_ALLOWED_IPS`, can restrict the Service Fulfilment
  URL to Hubtel's documented fulfilment IPs -- `52.50.116.54`,
  `18.202.122.131` and `52.31.15.68`. **Enable this only after confirming
  from the log that real requests actually show those addresses** --
  behind a proxy the visible address may differ, and a wrong setting
  here would block real payments. (`HUBTEL_TRUST_PROXY_HEADERS` controls
  whether `X-Forwarded-For` is trusted for this at all; off by default.)
  The same note applies to `docs/DEPLOY.md` if/when one exists -- there
  currently isn't a separate deploy-notes file in this repo.

## Open items (VERIFY before going live)

- [ ] What happens, on Hubtel's side, to a payment if the final callback
      is not sent within the one hour deadline
- [ ] Other `ServiceStatus` values besides `"success"`, and what to send
      when we can't fulfil a paid order
- [ ] The maximum time Hubtel waits for our fulfilment reply before it
      gives up / retries
- [ ] Whether the test/simulator credentials we've been given talk to a
      sandbox or to Hubtel's live system
- [ ] The maximum length of `ItemName` in the `AddToCart` response
- [ ] The charge rate Hubtel applies on top of small amounts (e.g. the
      default GH₵1.00 vote fee) -- needed so the confirm screen's "Hubtel
      may add a small charge" warning can eventually say how much
- [ ] Whether `isFulfilled` becomes `true` on Hubtel's side only after we
      send the final callback, or already once we reply to the
      fulfilment request
- [ ] For later web voting: Hubtel's rule on unsolicited payment prompts
      -- whether it requires the phone number to belong to a Hubtel user
      who can't edit it, or whether we must confirm an unregistered
      number before charging it
- [x] The exact field names carrying the status-check's status word and
      amount -- CONFIRMED 28 Nov 2026, real capture (see above)
- [ ] The fulfilment request body's fields beyond `SessionId`/`OrderId`
- [ ] The final callback body beyond the four fields already confirmed
- [ ] Whether `clientReference` in the status check is really the USSD `SessionId`
- [ ] Whether `OrderId` is present in the fulfilment request body itself, or
      only obtainable some other way
