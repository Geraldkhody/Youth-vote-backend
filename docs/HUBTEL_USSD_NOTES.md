# Hubtel Programmable Services (USSD) — notes

Source: pasted by the project owner from Hubtel's developer docs
(`api-reference-prog-services` and the `Programmable Services` reference
page). These notes are the source of truth for the stub endpoints in
`app/routes/hubtel.py`. Anything Hubtel's docs didn't give us is listed
under **Open items** below and must be verified before real voting logic
is built on top of this stub.

## Request Hubtel sends to our Service Interaction URL

`POST` with a JSON body:

| Field | Meaning |
|---|---|
| `Type` | `"initiation"` (first message of a session), `"response"` (later message), `"release"` (user ended the session), `"AddToCart"` (user is being sent to checkout) |
| `Message` | What the user typed. On `initiation` over USSD, this is the dialed string |
| `ServiceCode` | The dialed short code, or a service id |
| `Operator` | For USSD: one of `"tigo"`, `"airtel"`, `"mtn"`, `"vodafone"` |
| `ClientState` | Data we asked Hubtel to echo back from our previous reply. Arrives only on the *next* request, then is discarded |
| `Mobile` | The user's phone number, e.g. `233200585542` |
| `SessionId` | Unique id of the session |
| `Sequence` | Integer — position of the message in the session |
| `Platform` | `"USSD"`, `"HUBTEL APP"`, `"HUBTEL POS"` or `"WEB"` |

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

**STILL UNKNOWN — VERIFY:**
- The status-check response format (status words and amount fields). Our
  client (`app/providers/hubtel.py`) makes a conservative best guess at
  parsing it and defaults to `"unknown"` for anything unrecognised --
  `"unknown"` is never treated as `"paid"`.
- The fulfilment request body (still just logged, not parsed).
- The final callback body.
- The maximum length of `ItemName`. We keep it under 40 characters as a
  conservative guess.

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

**STILL UNKNOWN — VERIFY:**
- What to send for a transaction that needed review instead (e.g. an
  amount mismatch) -- we currently send nothing at all for those. Open
  question for Hubtel.
- Other `ServiceStatus` values besides `"success"` (what do we send when
  we *can't* fulfil?).
- The maximum time Hubtel waits for our fulfilment reply before it gives
  up / retries.
- Whether `OrderId` is present in the fulfilment request body itself, or
  only obtainable some other way.

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

## Open items (VERIFY before building real voting/payment logic)

- [ ] Service Fulfilment URL request body fields (what `app/providers/hubtel_adapter.py`'s
      `parse_fulfilment_request` guesses at -- `SessionId` and `OrderId` only, nothing else trusted)
- [ ] Transaction Status Check: the response format (status words, amount fields)
- [ ] Whether `clientReference` in the status check is really the USSD `SessionId`
- [ ] The maximum length of `ItemName` in the `AddToCart` response
- [ ] Whether `release` responses need `Label`/`DataType`/`FieldType` populated
- [ ] What to send as the final callback for a `needs_review` transaction
- [ ] Other `ServiceStatus` values, and what to send when we can't fulfil
- [ ] The maximum time Hubtel waits for our fulfilment reply
- [ ] Whether `OrderId` is present in the fulfilment request body
