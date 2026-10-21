"""
Test cases for Review 3. Run with:   python -m pytest -v

They use a separate database (green_campus_test) that gets rebuilt from
sql/01_schema.sql + sql/02_seed.sql before every test, so your real data is never touched.
The TC numbers match the test case table in the report.
"""
import os
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["GC_DB_NAME"] = "green_campus_test"

import config  # noqa: E402
config.DB_NAME = "green_campus_test"

import db  # noqa: E402
import init_db  # noqa: E402
from app import app  # noqa: E402


@pytest.fixture
def client():
    init_db.load("green_campus_test")
    db.reset_pool()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def page(resp):
    return resp.get_data(as_text=True)


def reading_form(**over):
    data = {"meter_id": "1001", "reading_date": "2026-09-04",
            "consumption_value": "5000", "cost_incurred": "700"}
    data.update(over)
    return data


# ---------------- UI and connectivity ----------------

def test_tc01_dashboard_loads_with_correct_total(client):
    r = client.get("/")
    assert r.status_code == 200
    # 47,745.5 kg is the campus total from Review 2 section 7.8
    assert 'aria-label="47,745.5 kilograms' in page(r)


def test_tc02_every_page_opens(client):
    for url in ["/departments/", "/buildings/", "/factors/", "/meters/", "/readings/",
                "/initiatives/", "/carbon-logs/", "/buildings/101", "/search", "/queries", "/report"]:
        assert client.get(url).status_code == 200, url


# ---------------- CRUD ----------------

def test_tc03_create_department(client):
    r = client.post("/departments/new", data={
        "dept_name": "Electrical Engineering", "head_of_dept": "Dr. S. Iyer",
        "budget_allocated": "8000000", "contact_emails": "eee@greenuniv.edu"}, follow_redirects=True)
    assert "New department added" in page(r)
    assert db.scalar("SELECT COUNT(*) FROM departments") == 4


def test_tc04_read_list_shows_seed_rows(client):
    html = page(client.get("/meters/"))
    for code in ["ELEC-MAB-01", "SOLAR-HSA-01", "STEAM-CL-01"]:
        assert code in html


def test_tc05_update_building(client):
    r = client.post("/buildings/106/edit", data={
        "building_name": "Administration Block", "dept_id": "3",
        "floors": "4", "total_area_sqft": "42000"}, follow_redirects=True)
    assert "Saved changes" in page(r)
    assert db.scalar("SELECT floors FROM buildings WHERE building_id = 106") == 4


def test_tc06_delete_initiative(client):
    r = client.post("/initiatives/3005/delete", follow_redirects=True)
    assert "Deleted initiative #3005" in page(r)
    assert db.scalar("SELECT COUNT(*) FROM audit_initiatives") == 4


# ---------------- trigger ----------------

def test_tc07_new_reading_creates_carbon_log(client):
    r = client.post("/readings/new", data=reading_form(), follow_redirects=True)
    assert "Reading #2016 saved" in page(r)
    log = db.scalar("SELECT calculated_co2e_kg FROM carbon_logs WHERE reading_id = 2016")
    assert log == Decimal("4100.000")          # 5000 kWh x 0.82


def test_tc08_editing_reading_recalculates_log(client):
    client.post("/readings/2001/edit", data=reading_form(reading_date="2026-09-01",
                                                          consumption_value="1000", cost_incurred="140"))
    log = db.scalar("SELECT calculated_co2e_kg FROM carbon_logs WHERE reading_id = 2001")
    assert log == Decimal("820.000")


# ---------------- input validation ----------------

def test_tc09_negative_consumption_rejected(client):
    r = client.post("/readings/new", data=reading_form(consumption_value="-50"))
    assert "Consumption can&#39;t be negative" in page(r)
    assert db.scalar("SELECT COUNT(*) FROM energy_readings") == 15


def test_tc10_zero_floors_rejected(client):
    r = client.post("/buildings/new", data={"building_name": "Sports Complex", "dept_id": "",
                                            "floors": "0", "total_area_sqft": "30000"})
    assert "Floors must be at least 1" in page(r)


def test_tc11_future_date_rejected(client):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    r = client.post("/readings/new", data=reading_form(reading_date=tomorrow))
    assert "can&#39;t be in the future" in page(r)


def test_tc12_duplicate_reading_same_day_rejected(client):
    r = client.post("/readings/new", data=reading_form(reading_date="2026-09-01"))
    assert "already has a reading for that day (#2001)" in page(r)


def test_tc13_reading_on_inactive_meter_rejected(client):
    r = client.post("/readings/new", data=reading_form(meter_id="1008"))
    assert "STEAM-CL-01 is marked Inactive" in page(r)


def test_tc14_duplicate_meter_code_rejected(client):
    r = client.post("/meters/new", data={"meter_code": "elec-mab-01", "building_id": "101",
                                         "factor_id": "2", "status": "Active"})
    assert "ELEC-MAB-01 is already used" in page(r)


def test_tc15_bad_email_and_bad_status_rejected(client):
    r = client.post("/departments/new", data={"dept_name": "Civil", "head_of_dept": "X",
                                              "budget_allocated": "10", "contact_emails": "civil-at-uni"})
    assert "doesn&#39;t look like an email" in page(r)
    r = client.post("/initiatives/new", data={"title": "Test", "building_id": "101",
                                              "target_co2_reduction_kg": "10", "status": "Cancelled"})
    assert "Pick a valid status" in page(r)


# ---------------- referential actions ----------------

def test_tc16_delete_factor_in_use_is_blocked(client):
    r = client.post("/factors/2/delete", follow_redirects=True)
    assert "foreign key RESTRICT" in page(r)
    assert db.scalar("SELECT COUNT(*) FROM emission_factors WHERE factor_id = 2") == 1


def test_tc17_delete_building_cascades(client):
    client.post("/buildings/105/delete")
    # hostel had 2 meters, 3 readings, 3 logs and 1 initiative
    assert db.scalar("SELECT COUNT(*) FROM meters WHERE building_id = 105") == 0
    assert db.scalar("SELECT COUNT(*) FROM energy_readings") == 12
    assert db.scalar("SELECT COUNT(*) FROM carbon_logs") == 12
    assert db.scalar("SELECT COUNT(*) FROM audit_initiatives WHERE building_id = 105") == 0


def test_tc18_delete_department_sets_null(client):
    client.post("/departments/1/delete")
    assert db.scalar("SELECT COUNT(*) FROM buildings WHERE dept_id IS NULL") == 2
    assert db.scalar("SELECT COUNT(*) FROM buildings") == 6


# ---------------- search / retrieval ----------------

def test_tc19_search_by_text(client):
    html = page(client.get("/search?q=DG"))
    assert "DG-MW-01" in html and "DG-FAC-01" in html
    assert "ELEC-MAB-01" not in html


def test_tc20_search_by_date_and_value(client):
    html = page(client.get("/search?date_from=2026-09-02&date_to=2026-09-02&min_value=5000"))
    # only 2002 (5100) and 2010 (6400) are on 2 Sep with >= 5000
    assert "<strong>2</strong> matches" in html


def test_tc21_search_with_reversed_dates_warns(client):
    html = page(client.get("/search?date_from=2026-09-03&date_to=2026-09-01"))
    assert "after the" in html


# ---------------- queries / report ----------------

def test_tc22_review2_queries_give_review2_answers(client):
    html = page(client.get("/queries"))
    assert "12,792" in html and "0.1706" in html and "36,722" in html


def test_tc23_audit_report_procedure(client):
    html = page(client.get("/report?from=2026-09-01&to=2026-09-01"))
    # 1 Sep only: 8 readings (2001, 2004, 2006, 2008, 2009, 2011, 2012, 2013)
    cols, rows = db.call_proc("sp_GetCampusAuditReport", ("2026-09-01", "2026-09-01"))
    assert sum(r[cols.index("readings")] for r in rows) == 8
    assert "Campus total" in html
    csv = client.get("/report.csv?from=2026-09-01&to=2026-09-03")
    assert csv.mimetype == "text/csv" and "Main Academic Block" in page(csv)


def test_tc24_console_blocks_writes(client):
    html = page(client.post("/queries", data={"sql": "DELETE FROM meters"}))
    assert "Only SELECT" in html
    html = page(client.post("/queries", data={"sql": "SELECT * FROM meters; DROP TABLE meters"}))
    assert "One statement at a time" in html
    assert db.scalar("SELECT COUNT(*) FROM meters") == 8


# ---------------- the database on its own (Review 2 section 4.1) ----------------

@pytest.mark.parametrize("sql, codes", [
    ("INSERT INTO energy_readings VALUES (2099, 1001, '2026-09-05', -50, 10)", db.CHECK_FAILED),
    ("INSERT INTO buildings VALUES (199, 'Test Block', 1, 0, 1000)", db.CHECK_FAILED),
    ("INSERT INTO energy_readings VALUES (2099, 9999, '2026-09-05', 10, 10)", (1452,)),
    ("INSERT INTO meters VALUES (1099, 'ELEC-MAB-01', 101, 2, 'Active')", (1062,)),
    ("INSERT INTO audit_initiatives VALUES (3099, 101, 'X', 10, 'Cancelled')", (1265,)),
    ("DELETE FROM emission_factors WHERE factor_id = 2", (1451,)),
])
def test_tc25_constraints_reject_bad_sql(client, sql, codes):
    import mysql.connector
    with pytest.raises(mysql.connector.Error) as exc:
        db.execute(sql)
    assert exc.value.errno in codes
