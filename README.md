# Snack Counter Automation

Core logic for automating snack-counter refills in Framsikt's Oslo and Bengaluru offices: the refill lifecycle, choosing who buys, and the budget check, with simulated chat and HR systems.

The design, assumptions and trade-offs are in **[DESIGN.md](DESIGN.md)**.

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

- Two people can't both commit to the same refill, even at the same instant (threaded test).
- A second "empty" report joins the open refill instead of creating another.
- A refill nobody completes in one working day is handed to someone else, and its reserved money is released.
- An offer nobody answers in 2 office hours moves to the next volunteer.
- Deadlines pause overnight and over weekends, in each office's own time zone.
- If everyone passes, asking starts over the next working day; a box empty for two working days goes to the admin, once.
- Only volunteers in that office today are asked; visitors from the other office count; people with 2 unpaid claims are skipped; the rota prefers whoever has refilled least.
- Budgets are reserved at commit and settled on receipt, kept separately in NOK and INR; a refill is blocked when the budget is used up and reopens when the new month starts.
- Over-cap purchases are still reimbursed in full but flagged to the admin.
- The monthly report totals both offices correctly in NOK, and shows refills per person, what is still owed, and which snacks are bought and left uneaten.
- The claim reaches HR with the right details, is retried if HR is down, and approval or rejection is reported back; a claim pending more than 10 days is flagged to the admin.
