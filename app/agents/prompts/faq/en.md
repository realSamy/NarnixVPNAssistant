# Narnix — FAQ (base knowledge for the AI assistant)

> This file is the assistant's source of truth. Edit freely; nothing else in
> the codebase depends on its structure.

## Plans & purchasing
- Subscriptions are bought through the bot's "🛒 Shop" menu.
- Pricing lives on **packages** (e.g. 30GB / 30 days), not on servers. A
  package can be issued across one or more locations/servers.
- During purchase the user may add extra locations beyond the package's
  mandatory ones; extras affect the final price.
- Renewals go through the same purchase flow (a "Renew" button on the user's
  config), always at current prices.

## Wallet & payments
- Orders are paid **from wallet balance only** — the wallet must be charged
  before submitting an order.
- Current top-up method: card-to-card transfer. The user sends the transfer
  receipt as a photo; an admin approves it manually and the balance is
  credited. Approval is not instant.
- Deposit status and transaction history are visible in the bot's wallet
  section.

## Free test
- Every user can claim a one-time free test subscription (limited quota and
  duration, on the same locations as real packages).
- It is never re-issued. If the user already used it, guide them to purchase
  or support instead of promising a second test.

## Referrals
- Each user has a personal invite link ("🎁 Invite Friends").
- For every friend who joins through the link and buys a subscription, the
  inviter receives **1 GB of free quota**. No cap on invitations.
- Credit only lands when the friend actually joined via the link.

## Subscriptions & configs
- After purchase the bot issues a **subscription link**; all configs update
  through it.
- Individual v2ray config URLs and a QR code per config are also available.
- "My Configs" shows each config's traffic, expiry, and a renew button.
- The subscription link is a secret: sharing it grants access to the configs.

## Connection guide (importing links)
- **V2rayNG (Android):** "+" → Import config from clipboard / QR code. For the
  subscription link: Subscription tab → add URL → Update subscription.
- **V2Box (iOS/Android):** "+" → Import from clipboard; subscriptions via the
  Subscription option.
- **Hiddify (all platforms):** just paste — it detects the link. For
  subscriptions: New → Subscription.
- **Streisand (iOS):** "+" → Import from Clipboard, or scan the QR.
- If nothing connects: update the subscription first, then try another
  server. If every server fails, report it via ticket — it may be a new block
  on the user's ISP.

## Renewals
- Renewal uses the purchase path and current package prices.
- A renewal replaces the location set with the current catalogue; manual edits
  made in the panel to bot-issued configs are not preserved.

## Support & tickets
- To reach a human, open a ticket from "💬 Support" (or the button the
  assistant creates). The conversation continues in its own forum topic.
- Photos and files can be sent in tickets. Keep the subject short and clear.
- There is no guaranteed response time; follow progress in the ticket topic.

## Bot language
- Users switch the bot language (fa/en) in the "🌐 Language" section; the
  assistant answers in the same language.
