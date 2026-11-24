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

- Body fields: **NOT CAPTURED — VERIFY**
- Not called by this stub (there is nothing to fulfil yet).

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

- [ ] Service Fulfilment URL request body fields
- [ ] Final callback URL request body fields
- [ ] Transaction Status Check: full URL and response fields
- [ ] Whether `release` responses need `Label`/`DataType`/`FieldType` populated
- [ ] `AddToCart` `Item` structure (name, quantity, price fields)
