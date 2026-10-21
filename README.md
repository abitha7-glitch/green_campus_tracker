# Green Campus Carbon Footprint & Energy Audit Tracker

DBMS (BACSE202) project, Review 3: working prototype.

Abitha Laxmi P (25BCE0535), Vishnunarayan Praveen (25BCE0761), Daksh Bharath Singoor (25BDS0319)

Repo: https://github.com/abitha7-glitch/green_campus_tracker

A small web app on top of the MySQL database from Review 2. You log meter readings,
the database works out the CO₂e on its own (trigger), and the app shows which buildings
and which energy sources are responsible for most of the emissions.

## What's in here

```
green-campus/
├── app.py              routes / pages
├── db.py               MySQL connection pool + helpers
├── validation.py       server-side input checks
├── config.py           database login (edit this)
├── init_db.py          loads the .sql files for you
├── sql/
│   ├── 01_schema.sql   7 tables, 2 triggers, 2 views, 1 stored procedure
│   ├── 02_seed.sql     sample data (same as Review 2)
│   └── 03_queries.sql  every Review 2 query (the SQL queries page reads this file)
├── templates/          HTML (Jinja)
├── static/             CSS, JS, icon
└── tests/test_app.py   30 test cases (pytest)
```



| Requirement | Where |
|---|---|
| Simple user interface | every page, start at Overview |
| Database connectivity | `db.py` (connection pool, parameterised queries) |
| CRUD operations | Departments, Buildings, Emission factors, Meters, Readings, Initiatives |
| Search / retrieval | Search page, building detail page, filter box on every list |
| Important SQL queries through the app | SQL queries page (all of Review 2 + read-only console), Audit report (stored procedure), Overview (views) |
| Input validation | HTML/JS in the browser, `validation.py` on the server, constraints in MySQL |
| Test cases | `tests/test_app.py`, table in the report |
| Final database | `sql/01_schema.sql` + `sql/02_seed.sql` |

## Changes since Review 2

- `trg_after_energy_reading_update`: once readings could be edited, the carbon log needed
  to follow the new value. It only fires when the consumption or meter changes. Changing
  an emission factor still leaves old logs alone (they're the audit record).
- `sp_GetCampusAuditReport(from, to)`: the stored procedure from our Review 1 slides, now
  actually written. The Audit report page calls it.
- Rules the table constraints can't express are checked in the app: no readings dated in
  the future, one reading per meter per day, no new readings on an Inactive meter.

## Demo order we're using

1. Overview: total CO₂e, building ratings, scope split
2. Log a reading for ELEC-HSA-01 and show the carbon log appear (trigger)
3. Try to log -50, a future date, and a second reading for the same day (validation)
4. Edit that reading and show the log value change (update trigger)
5. Delete Hostel Block A's confirm page (cascade list), then try deleting Grid Electricity (RESTRICT)
6. Search: readings on 2 Sep with consumption ≥ 5000
7. SQL queries page, then the audit report for 1–2 Sep and download the CSV
8. `python -m pytest -v`

To reset after the demo: `python init_db.py`.
