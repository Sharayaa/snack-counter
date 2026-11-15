# Snack Counter Automation: Design

**Goal:** an empty box gets one named buyer quickly, nobody double-buys, the work and the out-of-pocket cost are shared fairly, volunteers are paid back without chasing, and management gets one monthly spend report. Volunteers keep buying in person; the system handles coordination, money and follow-up through the chat tool people already use.

## How a refill moves from "empty" to "reimbursed"

1. **Empty reported.** Anyone posts "empty" in the office's snack channel. If a refill is already open for that office, the report joins it instead of opening a second one.
2. **Budget check.** The system sets a spending cap from what's left this month, or **blocks** the refill for the office admin to decide (assumption 3).
3. **One person is asked.** A named volunteer is messaged directly (not "someone please"), chosen fairly from people in that office today. They reply *commit* or *pass*; no answer in 2 office hours passes it to the next person. If nobody is left to ask, the channel is asked, and asking starts over the next working day.
4. **Commit.** The first person to commit becomes the buyer; everyone else is told not to buy. The cap is **reserved** in the budget.
5. **Hand-over.** If the buyer hasn't uploaded a receipt within one working day, the commitment is released, the money is un-reserved and the next person is asked. A box still empty after two working days is escalated to the office admin.
6. **Bought and restocked.** The buyer uploads the receipt with the amount, what they bought and what was left uneaten. The reservation becomes the actual spend.
7. **Claim sent to HR** automatically with amount, currency, description, receipt and employee ID. If HR is unreachable, it's retried.
8. **Reimbursed / rejected.** The system checks HR's status regularly and tells the buyer; a rejection, or a claim HR has sat on for more than 10 days, goes to the office admin to chase.

States: `open → committed → purchased → claim_submitted → reimbursed`, with `blocked` (reopens when the next month's budget arrives) and `claim_rejected` as side paths.

## Main parts and their data

| Part | Keeps |
|---|---|
| **Refill service** (lifecycle) | Each refill: office, reporter, status, who was asked and until when, buyer, commit deadline, spend cap, budget month, people who passed, purchase, HR claim ID, history log |
| **Buyer selection** | Nothing of its own; reads volunteers' daily location, recent refills, unpaid claims |
| **Budget ledger** | Per office per month, in local currency: reserved amounts and actual spend per refill |
| **Volunteers** | Employee ID, name, home office, payroll currency, where they are each day |
| **Chat and HR adapters** | Thin wrappers; simulated here (`FakeChat`, `FakeHR`) |
| **Monthly report** | Computed from the ledger and refills: spend per office, refills per person, time from empty to restocked, items bought and left over, claims still unpaid, days to reimburse, total in NOK |

## How each problem is prevented

| Problem | Prevention |
|---|---|
| Box sits empty, everyone assumes someone else | A **named** person is asked, with a 2-hour reply window and a one-working-day completion window; stalls are handed on automatically, restarted each working day, and escalated to the admin after two |
| Two people buy on the same day | Only **one open refill per office**; commit is a single locked check, so only one person can ever succeed, and others are told not to buy |
| A few people do most refills and wait weeks | **Rotation**: whoever has refilled least in 30 days is asked first; anyone waiting on **2 unpaid claims** isn't asked; claims are filed the moment the receipt arrives, and one stuck at HR beyond 10 days is chased by the admin, not the volunteer |
| Nobody knows spend or what's eaten | Budget ledger per office/month; monthly report with totals per office and in NOK, plus items bought, items left uneaten and how fast boxes are refilled |

## Assumptions (and why)

I asked about the first four before starting and was told to choose and state them.

1. **The combined report is in NOK, converted at one month-end rate supplied by finance.** The company reports from Norway, and one rate per month means the report can be re-run and always gives the same figure; purchase-date rates would need a rate feed for little gain on amounts this small. Budget checks never use exchange rates, so a currency swing can't break a budget.
2. **A visitor's purchase counts against the office that was refilled, and is claimed in that office's currency.** The budget is for the box, not the person, and the receipt is from a local shop. So a Bengaluru employee buying in Oslo claims in NOK; HR converts to their payroll currency, as the brief says it does.
3. **The budget is checked before buying, not after.** The buyer is given a cap: the usual maximum (1 200 NOK / 3 000 INR), lowered to what's left. If less than the smallest typical purchase is left, the refill is blocked and the **office admin** decides. A receipt over the cap is still claimed in full but flagged to the admin: the volunteer has already paid and must never be left out of pocket.
4. **There is no existing consumption data, so the buyer reports it with the receipt:** what they bought and, optionally, what was still in the box. Items that keep being left over are the ones nobody eats. It costs the buyer a few seconds and needs no stock counting.
5. **One snack counter per office, one budget per calendar month** by the office's local date. The cap is reserved at commit and settled on receipt, so two refills can't plan to spend the same money.
6. **"Available" means physically in that office today**, visitors included. In practice this comes from the desk-booking tool or a chat status.
7. **Timeouts: 2 office hours to reply, one working day to complete, counted Mon–Fri 09:00–17:00 office time.** Long enough for a lunchtime or after-work shop, and nobody is timed out overnight or over a weekend. All are settings; public holidays are not known to the system.
8. **A volunteer may commit without being asked** while the refill is open; the rota decides who is asked, not who may help.
9. **The employee ID HR needs is the company login ID**, so no identity mapping is needed.

## Trade-offs

- **Ask one person vs. broadcast.** Asking one named person beats the "someone else will do it" problem but is slower if they're busy; the 2-hour timeout limits that cost.
- **Reserve the full cap.** Near month-end this can block a refill that would have fit; shrinking the cap to what's left keeps that rare.
- **In-memory storage with one lock.** Simple and fully testable here; in production the same "only one buyer" rule becomes a conditional database update, which also works across several servers.
- **"What gets eaten" is self-reported**, from items bought and left over, not counted stock. Rough, and the left-over list is optional so it never blocks a claim.
- **Known gap:** a buyer who shopped but missed the receipt deadline can re-commit only while the refill is still open; if someone else has taken it, the admin has to sort out their claim by hand. A reminder before the deadline is the next thing I'd add.

## Deliberately not built

Real chat or HR integrations (only the adapters), a user interface, a database, login, automatic exchange rates, inventory sensors or stock counting, a snack-ordering or delivery service, an approval workflow for extra budget (the admin decides manually), a public-holiday calendar, and payment cards. Each adds cost or complexity before we know the simple version works.
