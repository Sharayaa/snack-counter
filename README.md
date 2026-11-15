# Snack Counter Automation

This is the core logic for automating snack-counter refills in Framsikt's Oslo and Bengaluru offices. It covers the refill lifecycle, choosing who buys, and the budget check. The chat tool and the HR system are simulated.

The design, the assumptions and the trade-offs are in [DESIGN.md](DESIGN.md), with a PDF copy in [DESIGN.pdf](DESIGN.pdf).

## Run it

Requires Python 3.9+.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -v      # run the tests
python demo.py           # walk through one week and see the chat messages
```

## What's where

```
snack_counter/
  models.py      Offices, volunteers, refills and refill states
  service.py     The refill lifecycle: report, offer, commit, hand over, purchase, claim, report
  selection.py   Who gets asked to buy (fair rotation among people in the office today)
  budget.py      Monthly budget per office: reservations and actual spend
  working_hours.py  Deadlines that count office hours only (Mon-Fri 09-17, office time)
  fakes.py       Simulated clock, chat tool and HR system
  setup_data.py  The two offices with the budgets from the brief
tests/           Automated tests for the important rules
demo.py          Example run printing the chat messages
```

## Rules the tests prove

Who buys:

- Two people can't both commit to the same refill, even at the same instant.
- A second "empty" report joins the open refill and does not create another.
- Only volunteers who are in that office today are asked, including visitors from the other office.
- The person who has refilled least recently is asked first, and anyone with 2 unpaid claims is skipped.

Deadlines:

- An offer nobody answers within 2 office hours moves to the next volunteer.
- A refill the buyer doesn't complete within one working day is handed to someone else, and its reserved money is freed.
- The buyer is reminded once, 2 office hours before the deadline.
- A buyer who replies "bought" keeps the refill past the deadline, and nobody else can commit to it.
- If that buyer's receipt is late, the buyer and the admin are each told once, and the late receipt is still claimed.
- Deadlines pause overnight and over weekends, in each office's own time zone.
- If everyone passes, the asking starts again the next working day.
- A box that is still empty after two working days is reported to the admin once.

Money:

- The cap is reserved when someone commits and replaced by the real amount when the receipt arrives.
- Budgets are kept separately in NOK and INR.
- A refill is blocked when the budget is used up, and reopens when the new month starts.
- A purchase over the cap is still reimbursed in full, and the admin is told.
- The monthly report adds up both offices correctly in NOK. It also shows refills per person, what is still owed, and which snacks were bought and left uneaten.

Reimbursement:

- The claim reaches HR with the right amount, currency, receipt and employee ID.
- If HR is down, the claim is sent again later.
- If HR saves the claim but the reply is lost, the retry finds the same claim and no duplicate is created.
- The buyer is told when the claim is approved or rejected.
- A claim still pending after 10 days is reported to the admin.
