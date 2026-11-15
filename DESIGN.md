# Snack counter automation: design

When a snack box is empty, the system asks one volunteer by name to refill it, makes sure only one person buys, sends the receipt to HR for them, and tracks the budget. Volunteers still buy the snacks in person. Everything else happens in the chat tool they already use.

## How a refill moves from "empty" to "reimbursed"

1. Someone reports the box empty in the office's snack channel. If a refill is already open for that office, the second report joins it and no new refill is created.
2. The system checks the budget and works out how much the buyer may spend (the cap). If too little is left this month, the refill is blocked and the office admin decides what to do (assumption 3).
3. The system messages one volunteer who is in that office today and asks them to buy. They reply "commit" or "pass". If they don't answer within 2 office hours, the next person is asked. When nobody is left to ask, the request goes to the whole channel, and the asking starts again the next working day.
4. The first person to commit becomes the buyer. Anyone who tries after that is told not to buy. The cap is reserved in the budget.
5. The buyer has one working day to upload the receipt. After that, the refill is handed to the next person and the reserved money is freed. If the box is still empty after two working days, the office admin is told.
6. The buyer uploads the receipt with the amount, what they bought, and what was still in the box. The real amount replaces the reservation.
7. The system sends the claim to HR straight away, with the amount, currency, description, receipt and employee ID. If HR can't be reached, it tries again later.
8. The system checks the claim with HR regularly and tells the buyer when it is approved. If HR rejects it, or hasn't decided after 10 days, the office admin is asked to follow up.

A refill is always in one of five states: open, committed, purchased, claim submitted, or reimbursed. Two more cover the exceptions: blocked (the budget ran out; it reopens when the next month starts) and claim rejected.

## Main parts and the data each keeps

| Part | Data it keeps |
|---|---|
| Refill service | One record per refill: office, who reported it, state, who was asked, the buyer, both deadlines, the cap, the budget month, who has passed, the purchase, the HR claim ID, and a log of what happened |
| Buyer selection | No data of its own. It reads volunteers' locations, recent refills and unpaid claims |
| Budget ledger | Per office and month, in the office's currency: money reserved and money spent |
| Volunteers | Employee ID, name, home office, payroll currency, and where they are each day |
| Chat and HR connectors | No data. In this version they are simulated (`FakeChat`, `FakeHR`) |
| Monthly report | Calculated from the ledger and the refills: spend per office, refills per person, hours from empty to restocked, items bought and left over, unpaid claims, days to reimburse, total in NOK |

## How each problem is prevented

| Problem | What prevents it |
|---|---|
| The box sits empty because everyone assumes someone else will refill it | One person is asked by name and has 2 office hours to answer. A buyer has one working day to finish. If either deadline passes, the next person is asked. The admin is told after two working days |
| Two people buy on the same day | Each office can have only one open refill. Committing is a single locked step, so only the first person succeeds, and everyone else is told not to buy |
| A few people do most refills and wait weeks for their money | The person who has refilled least in the last 30 days is asked first. Anyone with 2 unpaid claims is skipped. The claim goes to HR as soon as the receipt is uploaded, and the admin chases any claim older than 10 days |
| Nobody knows the monthly spend or which snacks get eaten | The ledger records every purchase. The monthly report shows spend per office and in total, what was bought, and what was left uneaten |

## Assumptions and why

I asked about the first four before starting and was told to choose them myself and explain why.

1. The combined report is in NOK, using one month-end exchange rate that finance provides. I assumed head office is in Oslo. With one rate per month, running the report again gives the same total. Using the rate on each purchase date would need a daily rate feed, which is too much work for amounts this small. Budget checks stay in each office's own currency, so a rate change can't push an office over budget.
2. A visitor's purchase counts against the office they refilled, and the claim is in that office's currency. The budget belongs to the box, and the receipt comes from a local shop. A Bengaluru employee who buys in Oslo claims in NOK, and HR pays them in INR, which the brief says HR already does.
3. The budget is checked before anyone buys. The buyer is told a cap, which is the largest typical purchase (1 200 NOK or 3 000 INR) or whatever is left this month if that is less. If less than the smallest typical purchase is left (300 NOK or 500 INR), the refill is blocked and the office admin decides. If a receipt is over the cap, it is still claimed in full and the admin is told, because the volunteer has already paid and should get all of it back.
4. There is no existing data on what gets eaten, so the buyer reports it with the receipt: what they bought and, if they want, what was still in the box. Snacks that keep being left over are the ones nobody eats. This takes the buyer a few seconds and nobody has to count stock.
5. Each office has one snack counter and one budget per calendar month, using the office's local date. The cap is reserved when someone commits and replaced by the real amount when the receipt arrives, so two refills can't both plan to spend the same money.
6. A volunteer is available if they are in that office today, including visitors from the other office. I assumed this comes from a desk-booking tool or a chat status.
7. Deadlines count office hours only: Monday to Friday, 09:00 to 17:00, in the office's time zone. Two office hours to reply and one working day to buy leaves time for a lunchtime or after-work shop, and nobody loses their turn overnight or over a weekend. The system does not know about public holidays.
8. A volunteer can commit without being asked, as long as the refill is still open. The rota only decides who gets asked first.
9. The employee ID that HR needs is the same as the company login ID.

## Trade-offs

- Asking one person is slower than posting to the whole channel when that person is busy. I chose it anyway because posting to everyone is how the box ends up empty for days. The 2-hour deadline limits the delay.
- Reserving the full cap can block a refill near the end of the month that would have fitted. Lowering the cap to what is left makes this rare.
- Everything is kept in memory behind one lock, which is simple and easy to test. A real version would keep the same "only one buyer" rule as a conditional update in a database, which also works across several servers.
- What gets eaten is reported by buyers and nobody checks it against the box, so it is rough. Reporting what was left over is optional so it can never delay a claim.
- Known gap: a buyer who has already shopped but missed the receipt deadline can commit again only while the refill is still open. If someone else has taken it by then, the admin has to sort out their claim by hand. A reminder before the deadline is the next thing I would add.

## Deliberately not built

Real chat and HR integrations, a user interface, a database, login, automatic exchange rates, stock counting or sensors, snack ordering or delivery, an approval process for extra budget (the admin decides by hand), a public-holiday calendar, and company payment cards. Each of these adds cost before we know whether the simple version works.
